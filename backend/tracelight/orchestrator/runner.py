"""
The pipeline runner: executes a run stage by stage and records everything in
the run state (state.py) for the UI.

    lane A (code)   fetch → docstrings (DocAgent) → index_code
    lane B (SRS)    extract (SRS Agent) → prepare_review
                    ── both lanes in parallel (or B then A when sequential) ──
    review          pauses the run until the user resolves the review items
    then            index_srs → search → map → verify → results

Design
------
- Deterministic workflow, no LLM "manager": the LLMs live inside the agents.
- Every stage is idempotent and recorded; execute() skips stages already
  done, so resume = execute again (after a failure, a cancel or a restart).
- The review stage opens as soon as lane B is done, so the user can review
  while DocAgent is still running.  The run pauses only when both lanes are
  done and items are still open.
- Cancel: an in-process flag; agent subprocesses are terminated, in-process
  loops check it between requirements.
- Each thread uses its own database connections.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from traceability.config import TraceabilityConfig

from ..settings import AppPaths, SettingsStore, effective_settings
from . import agents as agent_mod
from .agents import AgentCancelled, AgentError
from .ollama import OllamaUnavailable, check_models
from .review import (ReviewError, SRSOutputs, add_extracted, apply_review, build_review_items,
                     embedder_fn, review_counts)
from .source import SourceError, fetch_source, make_working_copy, validate_srs_file
from .state import STAGE_BY_KEY, RunStore

logger = logging.getLogger(__name__)

LANE_A = ("fetch", "docstrings", "index_code")
LANE_B = ("extract", "prepare_review")
AFTER_REVIEW = ("index_srs", "search", "map", "verify", "results")
MAX_CONSECUTIVE_MODEL_FAILURES = 3


class RunCancelled(Exception):
    pass


class StageFailed(Exception):
    """A stage failed (stage=None: the run could not start, e.g. a model is missing)."""

    def __init__(self, stage: Optional[str], message: str) -> None:
        super().__init__(f"{STAGE_BY_KEY[stage].label}: {message}" if stage else message)
        self.stage = stage
        self.message = message


@dataclass
class Agents:
    """The agent launchers (replaceable in tests)."""
    run_docagent: Callable[..., Any] = agent_mod.run_docagent
    run_srs: Callable[..., Any] = agent_mod.run_srs


@dataclass
class RunContext:
    run_id: int
    run_dir: Path
    settings: Dict[str, Any]
    cancel: threading.Event
    auto_approve: bool = False
    extras: Dict[str, Any] = field(default_factory=dict)

    @property
    def srs_dir(self) -> Path:
        return self.run_dir / "srs"

    @property
    def logs_dir(self) -> Path:
        return self.run_dir / "logs"

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise RunCancelled()


def _short(component_id: str) -> str:
    parts = (component_id or "").split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else component_id


class Orchestrator:
    def __init__(self, cfg: TraceabilityConfig, paths: Optional[AppPaths] = None, *,
                 prefix: str = "app_", settings_store: Optional[SettingsStore] = None,
                 agents: Optional[Agents] = None,
                 llm_factory: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 embedder_factory: Optional[Callable[[], Any]] = None,
                 docagent_test_mode: str = "none", preflight: bool = True,
                 on_event: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self.cfg = cfg
        self.paths = paths or AppPaths.from_env()
        self.prefix = prefix
        self.settings_store = settings_store or SettingsStore(self.paths.settings_file)
        self.agents = agents or Agents()
        self.llm_factory = llm_factory or self._ollama_client
        self.embedder_factory = embedder_factory or self._embedder
        self.docagent_test_mode = docagent_test_mode
        self.preflight = preflight
        self.on_event = on_event
        self._cancel: Dict[int, threading.Event] = {}
        self._threads: Dict[int, threading.Thread] = {}
        self._lock = threading.Lock()
        self._embedder_instance = None

    # ------------------------------------------------------------------
    # Public API (used by the HTTP API and the CLI)
    # ------------------------------------------------------------------

    def store(self) -> RunStore:
        return RunStore(self.cfg, prefix=self.prefix)

    def init(self) -> None:
        with self.store() as s:
            s.init_schema()

    def create_run(self, *, source_kind: str, source_ref: str, srs_path: str,
                   git_ref: Optional[str] = None, name: Optional[str] = None,
                   overrides: Optional[Dict[str, Any]] = None) -> int:
        """Register a run and copy its uploaded inputs into the run folder (not started)."""
        settings = effective_settings(self.settings_store, overrides)
        srs = Path(srs_path)
        validate_srs_file(srs, settings["limits"]["max_upload_mb"])
        if source_kind == "zip" and not Path(source_ref).is_file():
            raise SourceError(f"ZIP file not found: {source_ref}")
        if source_kind == "folder" and not Path(source_ref).is_dir():
            raise SourceError(f"Folder not found: {source_ref}")
        if source_kind not in ("zip", "folder", "git"):
            raise SourceError(f"Unknown source kind: {source_kind!r}")
        display = Path(source_ref.rstrip("/")).stem if source_kind != "git" else source_ref.rstrip("/").rsplit("/", 1)[-1]
        with self.store() as s:
            run_id = s.create_run(name=name or f"{display} · {srs.stem}", source_kind=source_kind,
                                  source_ref=source_ref, srs_filename=srs.name, workdir="",
                                  settings=settings, git_ref=git_ref)
            run_dir = self.paths.runs_dir / f"run-{run_id}"
            inputs = run_dir / "input"
            inputs.mkdir(parents=True, exist_ok=True)
            shutil.copy2(srs, inputs / srs.name)
            if source_kind == "zip":
                shutil.copy2(source_ref, inputs / Path(source_ref).name)
                source_ref_stored = str(inputs / Path(source_ref).name)
                s.update_run(run_id, source_ref=source_ref_stored)
            s.update_run(run_id, workdir=str(run_dir))
            s.add_event(run_id, f"Run created: {source_kind} {display}, SRS {srs.name}")
        return run_id

    def start(self, run_id: int, *, auto_approve: bool = False) -> threading.Thread:
        """Run (or resume) in a background thread; a no-op if it is already running."""
        with self._lock:
            thread = self._threads.get(run_id)
            if thread is not None and thread.is_alive():
                return thread
            thread = threading.Thread(target=self.execute, args=(run_id,),
                                      kwargs={"auto_approve": auto_approve},
                                      name=f"run-{run_id}", daemon=True)
            self._threads[run_id] = thread
            thread.start()
            return thread

    def is_active(self, run_id: int) -> bool:
        thread = self._threads.get(run_id)
        return thread is not None and thread.is_alive()

    def cancel(self, run_id: int) -> bool:
        """Request cancellation.  Returns False if the run is not executing here."""
        event = self._cancel.get(run_id)
        with self.store() as s:
            run = s.get_run(run_id)
            if run and run["status"] == "paused":
                self._finish_cancel(s, run_id)
                return True
        if event is None or not self.is_active(run_id):
            return False
        event.set()
        return True

    def recover_interrupted(self) -> List[int]:
        """At startup: runs left 'running' by a stopped server are marked failed (resumable)."""
        recovered = []
        with self.store() as s:
            for run in s.runs_with_status(["running"]):
                if self.is_active(run["run_id"]):
                    continue
                for st in s.stages(run["run_id"]):
                    if st["status"] == "running":
                        s.update_stage(run["run_id"], st["stage"], status="failed",
                                       error="interrupted (server stopped)")
                s.set_run_status(run["run_id"], "failed",
                                 error="Interrupted: the server stopped while this run was running. Resume to continue.")
                recovered.append(run["run_id"])
        return recovered

    def start_reverify(self, run_id: int, requirement_ids: List[str]) -> threading.Thread:
        """Re-run verification for some requirements of a completed run (the verifier
        appends new rows; the latest one is shown), then refresh the summary."""
        with self._lock:
            thread = self._threads.get(run_id)
            if thread is not None and thread.is_alive():
                raise RuntimeError(f"Run {run_id} is busy")
            thread = threading.Thread(target=self._reverify, args=(run_id, list(requirement_ids)),
                                      name=f"run-{run_id}-reverify", daemon=True)
            self._threads[run_id] = thread
            thread.start()
            return thread

    def _reverify(self, run_id: int, requirement_ids: List[str]) -> None:
        cancel = threading.Event()
        self._cancel[run_id] = cancel
        with self.store() as s:
            run = s.get_run(run_id)
            ctx = RunContext(run_id=run_id, run_dir=Path(run["workdir"]), settings=run["settings"], cancel=cancel)
            self._log(s, ctx, "verify", f"Re-verifying {len(requirement_ids)} requirement(s): "
                                        f"{', '.join(requirement_ids)}")
            try:
                self._stage_verify(s, ctx, requirement_ids=requirement_ids)
                self._stage_results(s, ctx)
                self._log(s, ctx, "verify", "Re-verification done", level="ok")
            except RunCancelled:
                self._log(s, ctx, "verify", "Re-verification cancelled", level="warn")
            except Exception as exc:
                logger.exception("Re-verification of run %s failed", run_id)
                self._log(s, ctx, "verify", f"Re-verification failed: {exc}", level="error")

    # Review -------------------------------------------------------------

    def review_state(self, run_id: int) -> Dict[str, Any]:
        with self.store() as s:
            items = s.review_items(run_id)
        return {"items": items, "counts": review_counts([{**i, "key": i["item_key"]} for i in items])}

    def skip_remaining(self, run_id: int) -> int:
        """Resolve every open item as 'unreviewed' (kept, marked in the results)."""
        with self.store() as s:
            open_items = [i for i in s.review_items(run_id) if not i["resolution"]]
            for i in open_items:
                s.resolve_review_item(run_id, i["item_key"], "unreviewed", {})
        return len(open_items)

    def complete_review(self, run_id: int) -> Dict[str, Any]:
        """
        Validate the resolutions (raises ReviewError with the offending item
        keys) and mark the review stage done.  The caller then start()s the run.
        """
        with self.store() as s:
            run = s.get_run(run_id)
            if s.stage(run_id, "prepare_review")["status"] != "done":
                raise ReviewError("The requirements are not ready for review yet.")
            items = s.review_items(run_id)
            out = SRSOutputs.load(Path(run["workdir"]) / "srs")
            result = apply_review(out, [{**i, "key": i["item_key"]} for i in items])
            s.update_stage(run_id, "review", status="done", total=len(items), done=len(items),
                           detail={"summary": result.summary, "to_extract": len(result.to_extract),
                                   "requirements": len(result.requirements)})
            s.add_event(run_id, f"Review complete: {len(result.requirements)} requirement(s) kept, "
                                f"{len(result.to_extract)} to extract", stage="review", level="ok")
        return {"summary": result.summary, "requirements": len(result.requirements),
                "to_extract": len(result.to_extract)}

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, run_id: int, *, auto_approve: bool = False) -> str:
        """Run every stage not yet done.  Returns the final run status."""
        cancel = threading.Event()
        self._cancel[run_id] = cancel
        with self.store() as s:
            run = s.get_run(run_id)
            if run is None:
                raise ValueError(f"Run {run_id} not found")
            if run["status"] in ("completed", "cancelled"):
                return run["status"]
            ctx = RunContext(run_id=run_id, run_dir=Path(run["workdir"]), settings=run["settings"],
                             cancel=cancel, auto_approve=auto_approve)
            s.set_run_status(run_id, "running")
            self._log(s, ctx, None, "Run started" if not run["started_at"] else "Run resumed")
            try:
                if self.preflight:
                    self._preflight(s, ctx)
                self._run_lanes(ctx)
                if not self._review_gate(s, ctx):
                    s.set_run_status(run_id, "paused")
                    return "paused"
                for key in AFTER_REVIEW:
                    self._stage(s, ctx, key)
                s.set_run_status(run_id, "completed")
                self._log(s, ctx, None, "Run completed", level="ok")
                return "completed"
            except RunCancelled:
                self._finish_cancel(s, run_id)
                return "cancelled"
            except StageFailed as exc:
                s.set_run_status(run_id, "failed", error=str(exc))
                return "failed"
            except Exception as exc:          # a bug, not a stage failure: keep the trace
                logger.exception("Run %s crashed", run_id)
                s.set_run_status(run_id, "failed", error=f"{type(exc).__name__}: {exc}")
                self._log(s, ctx, None, f"Run crashed: {exc}", level="error",
                          data={"traceback": traceback.format_exc()})
                return "failed"

    def _finish_cancel(self, s: RunStore, run_id: int) -> None:
        for st in s.stages(run_id):
            if st["status"] in ("running", "waiting"):
                s.update_stage(run_id, st["stage"], status="cancelled")
        s.set_run_status(run_id, "cancelled")
        s.add_event(run_id, "Run cancelled", level="warn")

    def _log(self, s: RunStore, ctx: RunContext, stage: Optional[str], message: str, *,
             level: str = "info", data: Optional[Dict[str, Any]] = None) -> None:
        lane = STAGE_BY_KEY[stage].lane if stage else None
        s.add_event(ctx.run_id, message, stage=stage, lane=lane, level=level, data=data)
        if self.on_event:
            self.on_event({"run_id": ctx.run_id, "stage": stage, "lane": lane, "level": level,
                           "message": message})

    def _stage(self, s: RunStore, ctx: RunContext, key: str) -> None:
        st = s.stage(ctx.run_id, key)
        if st["status"] in ("done", "skipped"):
            return
        ctx.check_cancel()
        s.update_stage(ctx.run_id, key, reset=True, status="running")
        label = STAGE_BY_KEY[key].label
        self._log(s, ctx, key, f"{label} started")
        started = time.monotonic()
        try:
            getattr(self, f"_stage_{key}")(s, ctx)
        except (RunCancelled, AgentCancelled):
            s.update_stage(ctx.run_id, key, status="cancelled")
            raise RunCancelled()
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            s.update_stage(ctx.run_id, key, status="failed", error=message)
            data = {} if isinstance(exc, (AgentError, SourceError, ReviewError, OllamaUnavailable)) \
                else {"traceback": traceback.format_exc()}
            self._log(s, ctx, key, f"{label} failed: {message}", level="error", data=data)
            raise StageFailed(key, message) from exc
        s.update_stage(ctx.run_id, key, status="done")
        self._log(s, ctx, key, f"{label} done in {time.monotonic() - started:.0f} s", level="ok")

    # Lanes ----------------------------------------------------------------

    def _run_lanes(self, ctx: RunContext) -> None:
        errors: List[BaseException] = []

        def lane(keys) -> None:
            try:
                with self.store() as s:
                    for key in keys:
                        self._stage(s, ctx, key)
            except BaseException as exc:      # collected and re-raised in the run thread
                errors.append(exc)

        if ctx.settings["ingest"].get("parallel", True):
            threads = [threading.Thread(target=lane, args=(keys,), name=f"run-{ctx.run_id}-lane-{n}", daemon=True)
                       for n, keys in (("A", LANE_A), ("B", LANE_B))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        else:
            lane(LANE_B)              # the SRS lane first: the review can start sooner
            if not errors:
                lane(LANE_A)
        if errors:
            cancelled = [e for e in errors if isinstance(e, RunCancelled)]
            raise cancelled[0] if cancelled else errors[0]

    def _review_gate(self, s: RunStore, ctx: RunContext) -> bool:
        """True when the review is done (possibly just now); False = pause for the user."""
        if s.stage(ctx.run_id, "review")["status"] == "done":
            return True
        if ctx.auto_approve:
            skipped = self.skip_remaining(ctx.run_id)
            self._log(s, ctx, "review", f"Auto-approve: {skipped} open item(s) kept as unreviewed")
            self.complete_review(ctx.run_id)
            return True
        counts = review_counts([{**i, "key": i["item_key"]} for i in s.review_items(ctx.run_id)])
        s.update_stage(ctx.run_id, "review", status="waiting", total=counts["total"], done=counts["resolved"])
        self._log(s, ctx, "review", f"Waiting for your review: {counts['open']} open item(s)", level="warn")
        return False

    # Preflight --------------------------------------------------------------

    def _preflight(self, s: RunStore, ctx: RunContext) -> None:
        status = {st["stage"]: st["status"] for st in s.stages(ctx.run_id)}
        todo = lambda key: status.get(key) not in ("done", "skipped")   # noqa: E731
        problems = []
        checks = agent_mod.check_agents(self.paths)
        if todo("docstrings") and not (checks["docagent"]["dir_ok"] and checks["docagent"]["python_ok"]):
            problems.append(f"DocAgent not found at {checks['docagent']['dir']} (or its .venv is missing)")
        if (todo("extract") or todo("index_srs")) and not (checks["srsagent"]["dir_ok"] and checks["srsagent"]["python_ok"]):
            problems.append(f"SRS Agent not found at {checks['srsagent']['dir']} (or its .venv is missing)")
        models = ctx.settings["models"]
        needed = {}
        if todo("docstrings") and self.docagent_test_mode == "none":
            needed["docagent"] = models["docagent"]
        if todo("extract"):
            needed.update(srs=models["srs"], judge=models["judge"])
        if todo("verify"):
            needed["verifier"] = models["verifier"]
        if needed:
            try:
                pulled = check_models(ctx.settings["ollama_host"], needed)
            except OllamaUnavailable as exc:
                problems.append(str(exc))
            else:
                problems += [f"Model {needed[role]} ({role}) is not pulled: run `ollama pull {needed[role]}`"
                             for role, ok in pulled.items() if not ok]
        if problems:
            message = "; ".join(problems)
            self._log(s, ctx, None, f"Cannot start: {message}", level="error")
            raise StageFailed(None, f"Cannot start: {message}")

    # Stages: lane A -----------------------------------------------------------

    def _stage_fetch(self, s: RunStore, ctx: RunContext) -> None:
        run = s.get_run(ctx.run_id)
        info = fetch_source(run["source_kind"], run["source_ref"], ctx.run_dir, ctx.settings,
                            git_ref=run["git_ref"])
        for w in info.warnings:
            self._log(s, ctx, "fetch", w["message"], level="error" if w["level"] == "error" else "warn")
        if any(w["level"] == "error" for w in info.warnings):
            raise SourceError(next(w["message"] for w in info.warnings if w["level"] == "error"))
        repo_id = f"run-{ctx.run_id}-{info.name}"
        s.update_run(ctx.run_id, commit_sha=info.commit_sha, repo_id=repo_id)
        s.update_stage(ctx.run_id, "fetch", done=info.stats.files, total=info.stats.files,
                       detail={"source": info.to_dict()})
        where = f" @ {info.commit_sha[:7]}" if info.commit_sha else ""
        self._log(s, ctx, "fetch", f"{info.name}{where}: {info.stats.python_files} Python file(s), "
                                   f"{info.stats.components} components")

    def _stage_docstrings(self, s: RunStore, ctx: RunContext) -> None:
        src = s.stage(ctx.run_id, "fetch")["detail"]["source"]["root"]
        work = make_working_copy(Path(src), ctx.run_dir / "work")
        state = {"done": 0}

        def on_event(e: Dict[str, Any]) -> None:
            kind = e["event"]
            if kind == "plan":
                s.update_stage(ctx.run_id, "docstrings", total=e["total"], detail={"types": e.get("types", {})})
                self._log(s, ctx, "docstrings", f"Parsed {e['total']} components; generating docstrings in "
                                                f"dependency order")
            elif kind == "graph_saved":
                s.update_stage(ctx.run_id, "docstrings", detail={"graph_path": e["path"]})
            elif kind == "component":
                status = e["status"]
                if status == "processing":
                    s.update_stage(ctx.run_id, "docstrings", detail={"current": e["id"], "agent": None})
                    return
                state["done"] = e.get("done", state["done"] + 1)
                s.update_stage(ctx.run_id, "docstrings", done=state["done"])
                if status == "completed":
                    self._log(s, ctx, "docstrings", f"Docstring written for {_short(e['id'])}", level="ok")
                elif status == "error":
                    self._log(s, ctx, "docstrings", f"Could not write the docstring for {_short(e['id'])}",
                              level="warn")
            elif kind == "agent":
                s.update_stage(ctx.run_id, "docstrings", detail={"agent": e.get("agent")})
                comp = _short(e.get("component") or "")
                self._log(s, ctx, "docstrings", f"{(e.get('agent') or '').capitalize()}: {e.get('message')}"
                                                + (f" ({comp})" if comp else ""))

        self.agents.run_docagent(self.paths, ctx.settings, repo_path=work, out_dir=ctx.run_dir / "docagent",
                                 log_path=ctx.logs_dir / "docagent.log", test_mode=self.docagent_test_mode,
                                 on_event=on_event, cancel=ctx.cancel)

    def _stage_index_code(self, s: RunStore, ctx: RunContext) -> None:
        from traceability.pipeline import Pipeline

        run = s.get_run(ctx.run_id)
        graph_path = s.stage(ctx.run_id, "docstrings")["detail"].get("graph_path")
        if not graph_path or not Path(graph_path).exists():
            raise AgentError("DocAgent did not produce a dependency graph")
        work = ctx.run_dir / "work"
        report = Pipeline(self.cfg).ingest_graph(graph_path, repo_id=run["repo_id"], repo_path=str(work),
                                                 repo_snapshot=run["commit_sha"], source_root=work, embed=True)
        s.update_stage(ctx.run_id, "index_code", done=report["components"], total=report["components"],
                       detail={"report": report})
        self._log(s, ctx, "index_code", f"Indexed {report['components']} components, "
                                        f"{report.get('relationships', 0)} relationships, "
                                        f"{report['docstrings']['generated']} generated docstrings")

    # Stages: lane B -------------------------------------------------------------

    def _stage_extract(self, s: RunStore, ctx: RunContext) -> None:
        run = s.get_run(ctx.run_id)
        srs_path = ctx.run_dir / "input" / run["srs_filename"]

        def on_event(e: Dict[str, Any]) -> None:
            kind = e["event"]
            if kind == "stage":
                self._log(s, ctx, "extract", e.get("message", ""))
            elif kind == "segmentation":
                s.update_stage(ctx.run_id, "extract", detail={"phase": "detect", "segmentation": {
                    k: e.get(k) for k in ("candidates", "labelled", "skipped_sections", "skipped_tables")}})
                for w in e.get("warnings") or []:
                    self._log(s, ctx, "extract", f"{w.get('requirement_id') or 'Unlabelled'}: {w.get('message')}",
                              level="warn")
            elif kind == "candidates":
                s.update_stage(ctx.run_id, "extract", detail={"candidates": e.get("count"),
                                                              "confidence": e.get("confidence")})
                self._log(s, ctx, "extract", f"Detected {e.get('count')} candidate statement(s)")
            elif kind == "judge_batch_start":
                s.update_stage(ctx.run_id, "extract", detail={"phase": "judge", "judge": {
                    "batch": e.get("batch"), "batches": e.get("batches")}})
            elif kind == "judge_batch_done":
                s.update_stage(ctx.run_id, "extract", detail={"judge": {"batch": e.get("batch"),
                                                                        "batches": e.get("batches"), "done": True}})
                self._log(s, ctx, "extract", f"Judge batch {e.get('batch')}/{e.get('batches')}: kept {e.get('kept')}, "
                                             f"discarded {e.get('discarded')}, uncertain {e.get('uncertain')}")
                for d in e.get("decisions") or []:
                    if d.get("decision") == "uncertain":
                        self._log(s, ctx, "extract", f"Judge: {d.get('candidate_id')} → uncertain, queued for "
                                                     f"review ({d.get('reason')})", level="warn")
            elif kind == "requirement_start":
                s.update_stage(ctx.run_id, "extract", total=e.get("total"), done=(e.get("index") or 1) - 1,
                               detail={"phase": "extract", "current": e.get("requirement_id")})
            elif kind == "requirement_done":
                s.update_stage(ctx.run_id, "extract", done=e.get("index"))
                self._log(s, ctx, "extract", f"Extracted {e.get('requirement_id')} “{e.get('title')}”",
                          level="warn" if e.get("review_required") else "info")
            elif kind == "requirement_error":
                self._log(s, ctx, "extract", f"Candidate {e.get('index')} failed: {e.get('error')}", level="warn")

        result = self.agents.run_srs(self.paths, ctx.settings, "extract", out_dir=ctx.srs_dir,
                                     log_path=ctx.logs_dir / "srs.log", input_path=srs_path,
                                     on_event=on_event, cancel=ctx.cancel)
        finished = result.last("finished") or {}
        s.update_stage(ctx.run_id, "extract", detail={"phase": "done", "result": finished})
        if not finished.get("requirements") and not finished.get("uncertain"):
            raise AgentError("No requirements were found in the SRS document")

    def _stage_prepare_review(self, s: RunStore, ctx: RunContext) -> None:
        out = SRSOutputs.load(ctx.srs_dir)
        embed = embedder_fn(self.embedder_factory()) if len(out.requirements) > 1 else None
        items = build_review_items(out, embed=embed,
                                   duplicate_threshold=ctx.settings["review"]["duplicate_threshold"])
        s.replace_review_items(ctx.run_id, items)
        counts = review_counts(items)
        s.update_stage(ctx.run_id, "prepare_review", done=counts["total"], total=counts["total"],
                       detail={"counts": counts, "requirements": len(out.requirements)})
        if s.stage(ctx.run_id, "review")["status"] != "done":
            s.update_stage(ctx.run_id, "review", status="waiting", total=counts["total"], done=counts["resolved"])
        self._log(s, ctx, "prepare_review", f"{len(out.requirements)} requirement(s) extracted; "
                                            f"{counts['open']} item(s) need your review",
                  level="warn" if counts["open"] else "ok")

    # Stages: after review ---------------------------------------------------------

    def _stage_index_srs(self, s: RunStore, ctx: RunContext) -> None:
        from traceability.pipeline import Pipeline

        run = s.get_run(ctx.run_id)
        out = SRSOutputs.load(ctx.srs_dir)
        items = [{**i, "key": i["item_key"]} for i in s.review_items(ctx.run_id)]
        result = apply_review(out, items)
        requirements = result.requirements
        if result.to_extract:
            self._log(s, ctx, "index_srs", f"Extracting {len(result.to_extract)} item(s) kept at review")
            review_dir = ctx.run_dir / "srs_review"
            review_dir.mkdir(parents=True, exist_ok=True)
            cand_path = review_dir / "candidates_to_extract.json"
            cand_path.write_text(json.dumps(result.to_extract, indent=2, ensure_ascii=False), encoding="utf-8")
            self.agents.run_srs(self.paths, ctx.settings, "extract-candidates", out_dir=review_dir,
                                log_path=ctx.logs_dir / "srs_review.log", candidates_path=cand_path,
                                cancel=ctx.cancel)
            extracted = SRSOutputs.load(review_dir).requirements
            requirements = add_extracted(requirements, extracted, result.to_extract)
            missing = len(result.to_extract) - len(extracted)
            if missing:
                self._log(s, ctx, "index_srs", f"{missing} kept item(s) could not be extracted", level="warn")
        if not requirements:
            raise ReviewError("No requirements are left to trace after the review.")
        reviewed = ctx.run_dir / "reviewed_requirements.json"
        reviewed.write_text(json.dumps(requirements, indent=2, ensure_ascii=False), encoding="utf-8")
        document_id = f"run-{ctx.run_id}-{Path(run['srs_filename']).stem}"
        report = Pipeline(self.cfg).ingest_srs(reviewed, document_id=document_id, embed=True)
        s.update_run(ctx.run_id, document_id=document_id)
        s.update_stage(ctx.run_id, "index_srs", done=report["requirements"], total=report["requirements"],
                       detail={"report": report})
        self._log(s, ctx, "index_srs", f"Indexed {report['requirements']} requirement(s)")

    def _stage_search(self, s: RunStore, ctx: RunContext) -> None:
        from traceability.candidates import PIPELINE_VERSION, CandidateSearch
        from traceability.query import QueryResolver
        from traceability.retrieval import Retriever
        from traceability.store import Store

        run = s.get_run(ctx.run_id)
        cfg = ctx.settings["search"]
        with Store(self.cfg) as store:
            resolver = QueryResolver(store)
            queries = resolver.document_requirements(run["document_id"], repo_id=run["repo_id"])
            s.update_stage(ctx.run_id, "search", total=len(queries))
            search = CandidateSearch(store, resolver, Retriever(store))
            without = []
            for i, q in enumerate(queries, start=1):
                ctx.check_cancel()
                r = search.run_one(q, top_n=cfg["top_n"], candidate_k=cfg["candidate_k"],
                                   pipeline_version=PIPELINE_VERSION)
                if not r["candidates"]:
                    without.append(r["requirement_id"])
                s.update_stage(ctx.run_id, "search", done=i, detail={"current": r["requirement_id"]})
        s.update_stage(ctx.run_id, "search", detail={"without_candidates": without, "current": None})
        self._log(s, ctx, "search", f"{len(queries) - len(without)} requirement(s) with candidates"
                                    + (f", {len(without)} with none ({', '.join(without)})" if without else ""))

    def _stage_map(self, s: RunStore, ctx: RunContext) -> None:
        from traceability.mapping import Mapper, MappingConfig
        from traceability.query import QueryResolver
        from traceability.store import Store

        run = s.get_run(ctx.run_id)
        m = ctx.settings["mapping"]
        with Store(self.cfg) as store:
            report = Mapper(store, QueryResolver(store), MappingConfig(
                max_direct_rank=m["max_direct_rank"], max_supporting=m["max_supporting"],
                use_source_references=m["use_source_references"])).run(run["document_id"], run["repo_id"])
        links = report["links"]
        s.update_stage(ctx.run_id, "map", done=report["requirements"], total=report["requirements"],
                       detail={"links": links, "without_candidates": report["without_candidates"]})
        self._log(s, ctx, "map", f"{links['direct']} direct links, {links['supporting']} supporting links")

    def _stage_verify(self, s: RunStore, ctx: RunContext,
                      requirement_ids: Optional[List[str]] = None) -> None:
        """Verify every requirement, or only `requirement_ids` (a re-run; the stage counters are left alone)."""
        from traceability.query import QueryResolver
        from traceability.store import Store
        from traceability.verification import Verifier, VerifierConfig

        run = s.get_run(ctx.run_id)
        llm = self.llm_factory(ctx.settings)
        failures = {"consecutive": 0}

        def progress(i: int, n: int, r: Dict[str, Any]) -> None:
            if requirement_ids is None:
                s.update_stage(ctx.run_id, "verify", done=i, total=n, detail={"current": r["requirement_id"]})
            supported = sum(c.get("verdict") == "supported" for c in r.get("claims") or [])
            claims = len(r.get("claims") or [])
            note = f" ({supported}/{claims} claims)" if claims else ""
            level = {"supported": "ok", "partially_supported": "warn"}.get(r["status"], "info")
            if r.get("error"):
                level = "error"
                note += f" — model error: {r['error']}"
            self._log(s, ctx, "verify", f"{r['requirement_id']} → {r['status'].replace('_', ' ')}{note}",
                      level=level, data={"requirement_id": r["requirement_id"], "status": r["status"]})
            failures["consecutive"] = failures["consecutive"] + 1 if r.get("error") else 0
            if failures["consecutive"] >= MAX_CONSECUTIVE_MODEL_FAILURES:
                raise AgentError(f"the verifier model failed {failures['consecutive']} times in a row "
                                 f"(last error: {r['error']}). Check Ollama, then resume.")
            ctx.check_cancel()

        with Store(self.cfg) as store:
            report = Verifier(store, QueryResolver(store), llm,
                              VerifierConfig(claim_splitting=ctx.settings["verification"]["claims"])
                              ).run(run["document_id"], requirement_ids=requirement_ids, progress=progress)
        if requirement_ids is None:
            s.update_stage(ctx.run_id, "verify", detail={"status_counts": report["status_counts"], "current": None,
                                                         "model": report["model"],
                                                         "prompt_version": report["prompt_version"]})

    def _stage_results(self, s: RunStore, ctx: RunContext) -> None:
        from traceability.query import QueryResolver
        from traceability.store import Store
        from traceability.verification.verifier import PIPELINE_VERSION

        run = s.get_run(ctx.run_id)
        with Store(self.cfg) as store:
            doc_pk = QueryResolver(store).document_pk(run["document_id"])
            latest = store.latest_verifications(document_pk=doc_pk, pipeline_version=PIPELINE_VERSION)
        counts: Dict[str, int] = {}
        for row in latest.values():
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        reviewed = json.loads((ctx.run_dir / "reviewed_requirements.json").read_text(encoding="utf-8"))
        unreviewed = sorted(r["requirement_id"] for r in reviewed
                            if (r.get("review") or {}).get("status") == "unreviewed")
        stages = {st["stage"]: st for st in s.stages(ctx.run_id)}
        summary = {
            "requirements": len(latest),
            "status_counts": counts,
            "unreviewed": unreviewed,
            "components": (stages["index_code"]["detail"].get("report") or {}).get("components"),
            "links": stages["map"]["detail"].get("links"),
            "verifier_model": stages["verify"]["detail"].get("model"),
        }
        s.update_run(ctx.run_id, summary=summary)
        s.update_stage(ctx.run_id, "results", done=len(latest), total=len(latest))
        self._log(s, ctx, "results", f"{counts.get('supported', 0)}/{len(latest)} supported, "
                                     f"{counts.get('partially_supported', 0)} partially supported, "
                                     f"{counts.get('not_supported_by_candidate', 0)} not supported, "
                                     f"{counts.get('not_found', 0)} not found")

    # Defaults -------------------------------------------------------------------

    def _ollama_client(self, settings: Dict[str, Any]):
        from traceability.verification import OllamaClient
        return OllamaClient(settings["models"]["verifier"], host=settings["ollama_host"])

    def _embedder(self):
        if self._embedder_instance is None:
            from traceability.embedder import Embedder
            self._embedder_instance = Embedder(self.cfg)
        return self._embedder_instance
