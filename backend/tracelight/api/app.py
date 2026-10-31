"""
Tracelight HTTP API (FastAPI).

Runs
  POST   /api/inspect                      size check of a ZIP/folder/URL before starting
  POST   /api/runs                         create (multipart: SRS + ZIP | folder | Git URL) and start
  GET    /api/runs                         list (with progress and summary)
  GET    /api/runs/{id}                    detail: stages, rail, lanes, overall progress, review counts
  GET    /api/runs/{id}/events             activity log (?after=, ?lane=, ?limit=)
  GET    /api/runs/{id}/stream             live updates (server-sent events: log, run)
  POST   /api/runs/{id}/cancel | /resume
  DELETE /api/runs/{id}                    run state, files and its traceability rows

Review checkpoint
  GET    /api/runs/{id}/review             items, counts
  GET    /api/runs/{id}/document           the parsed SRS (source context for items)
  GET    /api/runs/{id}/review/targets     merge targets for an item, by similarity
  PUT    /api/runs/{id}/review/items/{key} resolve one item {resolution, data}
  DELETE /api/runs/{id}/review/items/{key} undo
  POST   /api/runs/{id}/review/bulk        {keys, resolution}
  POST   /api/runs/{id}/review/skip-remaining
  POST   /api/runs/{id}/review/complete    validate, then run search → map → verify

Settings and health
  GET    /api/settings | PUT /api/settings (partial; nested keys merge)
  GET    /api/health                       database, Ollama, models pulled, agents found

Single-user and local: bind to 127.0.0.1.  No authentication.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import math
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from traceability.config import TraceabilityConfig

from ..orchestrator.agents import check_agents
from ..orchestrator.ollama import OllamaUnavailable, has_model, model_details, server_version
from ..orchestrator.review import (RESOLUTIONS, ReviewError, SRSOutputs, review_counts)
from ..orchestrator.runner import Orchestrator
from ..orchestrator.source import (SourceError, extract_zip, inspect_tree, size_warnings,
                                   validate_git_url)
from ..settings import DEFAULTS
from .progress import run_progress
from .results import OVERRIDE_STATUSES, ResultsReader
from .search import search_run

TERMINAL = ("completed", "failed", "cancelled")


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class Resolution(BaseModel):
    resolution: str
    data: Dict[str, Any] = {}


class BulkResolution(BaseModel):
    keys: List[str]
    resolution: str


class Override(BaseModel):
    status: str
    note: Optional[str] = None


class Reverify(BaseModel):
    requirement_ids: List[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{**i, "key": i["item_key"]} for i in items]


def _run_card(run: Dict[str, Any], stages: List[Dict[str, Any]], counts: Dict[str, Any]) -> Dict[str, Any]:
    prog = run_progress(stages)
    return {
        "run_id": run["run_id"], "name": run["name"], "status": run["status"], "error": run["error"],
        "source": {"kind": run["source_kind"], "ref": run["source_ref"], "git_ref": run["git_ref"],
                   "commit_sha": run["commit_sha"]},
        "srs_filename": run["srs_filename"], "document_id": run["document_id"], "repo_id": run["repo_id"],
        "created_at": run["created_at"], "started_at": run["started_at"], "finished_at": run["finished_at"],
        "summary": run["summary"], "models": (run["settings"] or {}).get("models"),
        "progress": prog["overall"], "rail": prog["rail"], "review": counts,
    }


def _lanes(prog_stages: List[Dict[str, Any]], store, run_id: int) -> List[Dict[str, Any]]:
    lanes = []
    for lane, title in (("A", "Code"), ("B", "SRS")):
        members = [s for s in prog_stages if s["lane"] == lane]
        lanes.append({"lane": lane, "title": title, "stages": members,
                      "log": store.last_events(run_id, lane, limit=60)})
    return lanes


def _save_upload(upload: UploadFile, dest_dir: Path, max_mb: int) -> Path:
    name = Path(upload.filename or "upload").name
    if not name or name in (".", ".."):
        raise SourceError("Invalid file name")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    limit = max_mb * 1024 * 1024
    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise SourceError(f"{name} is larger than {max_mb} MB")
            out.write(chunk)
    return dest


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def create_app(orchestrator: Optional[Orchestrator] = None, *, recover: bool = True,
               poll_seconds: float = 1.0) -> FastAPI:
    orch = orchestrator or Orchestrator(TraceabilityConfig())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        orch.init()
        if recover:
            orch.recover_interrupted()      # runs left 'running' by a stopped server
        yield

    app = FastAPI(title="Tracelight", version="0.1.0", lifespan=lifespan)
    app.state.orch = orch
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])
    vectors_cache: Dict[int, Dict[str, Any]] = {}

    @app.exception_handler(SourceError)
    async def _source_error(_: Request, exc: SourceError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(ReviewError)
    async def _review_error(_: Request, exc: ReviewError):
        return JSONResponse({"detail": str(exc), "keys": exc.keys}, status_code=409)

    def _run_or_404(s, run_id: int) -> Dict[str, Any]:
        run = s.get_run(run_id)
        if run is None:
            raise HTTPException(404, f"Run {run_id} not found")
        return run

    def _snapshot(s, run_id: int) -> Dict[str, Any]:
        run = _run_or_404(s, run_id)
        stages = s.stages(run_id)
        counts = review_counts(_items(s.review_items(run_id)))
        card = _run_card(run, stages, counts)
        prog = run_progress(stages)
        card["stages"] = prog["stages"]
        card["active"] = orch.is_active(run_id)
        return card

    # -- health and settings ------------------------------------------------

    @app.get("/api/health")
    def health(host: Optional[str] = None) -> Dict[str, Any]:
        """host: test another Ollama endpoint than the saved one (Settings → Test connection)."""
        settings = orch.settings_store.load()
        ollama_host = (host or settings["ollama_host"]).strip()
        if not ollama_host.startswith(("http://", "https://")):
            raise HTTPException(400, "The Ollama endpoint must start with http:// or https://")
        cfg = orch.cfg
        out: Dict[str, Any] = {"agents": check_agents(orch.paths), "ollama_host": ollama_host,
                               "embeddings": {"model": cfg.embed_model, "dim": cfg.embed_dim, "local": True}}
        try:
            started = time.perf_counter()
            with orch.store() as s:
                with s._cursor() as cur:
                    cur.execute("SELECT current_database() AS db, pg_database_size(current_database()) AS bytes, "
                                "(SELECT extversion FROM pg_extension WHERE extname = 'vector') AS pgvector, "
                                "current_setting('server_version') AS postgres")
                    row = cur.fetchone()
            out["database"] = {"ok": True, "connection": f"postgresql://{cfg.pg_user}@{cfg.pg_host}:{cfg.pg_port}/{row['db']}",
                               "postgres": row["postgres"], "pgvector": row["pgvector"], "bytes": row["bytes"],
                               "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
        except Exception as exc:          # report, do not fail the health call
            out["database"] = {"ok": False, "error": str(exc)}
        try:
            details = model_details(ollama_host)
            available = [str(m["name"]) for m in details]
            sizes = {str(m["name"]): m["size"] for m in details}
            out["ollama"] = {"ok": True, "models": available, "details": details, "version": server_version(ollama_host)}

            def size_of(name: str):
                return sizes.get(name) or sizes.get(f"{name}:latest")

            out["models"] = {role: {"name": name, "pulled": has_model(name, available), "size": size_of(name)}
                             for role, name in settings["models"].items()}
        except OllamaUnavailable as exc:
            out["ollama"] = {"ok": False, "error": str(exc)}
            out["models"] = {role: {"name": name, "pulled": None} for role, name in settings["models"].items()}
        return out

    @app.get("/api/settings")
    def get_settings() -> Dict[str, Any]:
        return {"settings": orch.settings_store.load(), "defaults": DEFAULTS}

    @app.put("/api/settings")
    def put_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
        unknown = set(changes) - set(DEFAULTS)
        if unknown:
            raise HTTPException(400, f"Unknown settings: {', '.join(sorted(unknown))}")
        return {"settings": orch.settings_store.save(changes)}

    # -- runs -----------------------------------------------------------------

    @app.post("/api/inspect")
    def inspect(source_kind: str = Form(...), zip: Optional[UploadFile] = File(None),
                folder: Optional[str] = Form(None), git_url: Optional[str] = Form(None),
                exclude_dirs: Optional[str] = Form(None)) -> Dict[str, Any]:
        """exclude_dirs: JSON list overriding the saved exclusions (what the run will use)."""
        settings = orch.settings_store.load()
        exclude = settings["source"]["exclude_dirs"]
        if exclude_dirs:
            try:
                exclude = [str(x) for x in json.loads(exclude_dirs)]
            except (json.JSONDecodeError, TypeError) as exc:
                raise HTTPException(400, f"exclude_dirs is not a JSON list: {exc}") from exc
        if source_kind == "git":
            return {"kind": "git", "url": validate_git_url(git_url or ""), "stats": None,
                    "warnings": [], "note": "The repository is cloned and measured when the run starts."}
        with tempfile.TemporaryDirectory(prefix="tracelight-inspect-") as tmp:
            if source_kind == "zip":
                if zip is None:
                    raise SourceError("Upload a ZIP file")
                archive = _save_upload(zip, Path(tmp) / "upload", settings["limits"]["max_upload_mb"])
                root = extract_zip(archive, Path(tmp) / "x", exclude)
            elif source_kind == "folder":
                root = Path(folder or "")
                if not folder or not root.is_dir():
                    raise SourceError(f"Folder not found: {folder}")
            else:
                raise SourceError(f"Unknown source kind: {source_kind!r}")
            stats = inspect_tree(root, exclude)
        out = stats.__dict__.copy()
        out["components"] = stats.components
        return {"kind": source_kind, "stats": out, "warnings": size_warnings(stats, settings["limits"])}

    @app.post("/api/runs", status_code=201)
    def create_run(source_kind: str = Form(...), srs: UploadFile = File(...),
                   zip: Optional[UploadFile] = File(None), folder: Optional[str] = Form(None),
                   git_url: Optional[str] = Form(None), git_ref: Optional[str] = Form(None),
                   name: Optional[str] = Form(None), overrides: Optional[str] = Form(None),
                   start: bool = Form(True)) -> Dict[str, Any]:
        settings = orch.settings_store.load()
        max_mb = settings["limits"]["max_upload_mb"]
        try:
            run_overrides = json.loads(overrides) if overrides else None
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"overrides is not valid JSON: {exc}") from exc
        upload_dir = orch.paths.data_dir / "uploads" / uuid.uuid4().hex
        try:
            srs_path = _save_upload(srs, upload_dir / "srs", max_mb)
            if source_kind == "zip":
                if zip is None:
                    raise SourceError("Upload a ZIP file of the code")
                ref = str(_save_upload(zip, upload_dir / "code", max_mb))
            elif source_kind == "folder":
                ref = folder or ""
            elif source_kind == "git":
                ref = validate_git_url(git_url or "")
            else:
                raise SourceError(f"Unknown source kind: {source_kind!r}")
            run_id = orch.create_run(source_kind=source_kind, source_ref=ref, srs_path=str(srs_path),
                                     git_ref=git_ref or None, name=name or None, overrides=run_overrides)
        finally:
            shutil.rmtree(upload_dir, ignore_errors=True)      # create_run copied what it needs
        if start:
            orch.start(run_id)
        with orch.store() as s:
            return jsonable_encoder(_snapshot(s, run_id))

    @app.get("/api/runs")
    def list_runs(limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
        with orch.store() as s:
            runs = []
            for run in s.list_runs(limit):
                counts = review_counts(_items(s.review_items(run["run_id"])))
                runs.append(_run_card(run, s.stages(run["run_id"]), counts))
        return jsonable_encoder({"runs": runs})

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: int) -> Dict[str, Any]:
        with orch.store() as s:
            snap = _snapshot(s, run_id)
            snap["lanes"] = _lanes(snap["stages"], s, run_id)
            snap["log"] = s.last_events(run_id, None, limit=60)
        return jsonable_encoder(snap)

    @app.get("/api/runs/{run_id}/events")
    def get_events(run_id: int, after: int = 0, lane: Optional[str] = None,
                   limit: int = Query(500, ge=1, le=5000)) -> Dict[str, Any]:
        with orch.store() as s:
            _run_or_404(s, run_id)
            return jsonable_encoder({"events": s.events(run_id, after=after, limit=limit, lane=lane)})

    @app.get("/api/runs/{run_id}/stream")
    async def stream(run_id: int, request: Request, after: int = 0):
        store = await asyncio.to_thread(orch.store)
        try:
            await asyncio.to_thread(_run_or_404, store, run_id)
        except HTTPException:
            store.close()
            raise

        async def gen():
            last_event = after
            last_snapshot = None
            idle = 0.0
            try:
                while not await request.is_disconnected():
                    events = await asyncio.to_thread(store.events, run_id, after=last_event, limit=500)
                    for e in events:
                        last_event = e["event_id"]
                        yield f"id: {last_event}\nevent: log\ndata: {json.dumps(jsonable_encoder(e))}\n\n"
                    snap = await asyncio.to_thread(_snapshot, store, run_id)
                    encoded = json.dumps(jsonable_encoder(snap))
                    if encoded != last_snapshot:
                        last_snapshot = encoded
                        yield f"event: run\ndata: {encoded}\n\n"
                        idle = 0.0
                    else:
                        idle += poll_seconds
                        if idle >= 15:              # keep proxies from closing the connection
                            idle = 0.0
                            yield ": keep-alive\n\n"
                    await asyncio.sleep(poll_seconds)
            finally:
                store.close()

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: int) -> Dict[str, Any]:
        with orch.store() as s:
            run = _run_or_404(s, run_id)
            if run["status"] in TERMINAL:
                raise HTTPException(409, f"Run {run_id} is already {run['status']}")
        if not orch.cancel(run_id):
            raise HTTPException(409, f"Run {run_id} is not executing in this server; nothing to cancel")
        return {"run_id": run_id, "cancelling": True}

    @app.post("/api/runs/{run_id}/resume")
    def resume_run(run_id: int) -> Dict[str, Any]:
        with orch.store() as s:
            run = _run_or_404(s, run_id)
            if run["status"] == "completed":
                raise HTTPException(409, "The run is already completed")
            if orch.is_active(run_id):
                raise HTTPException(409, "The run is already executing")
            if run["status"] == "cancelled":
                s.set_run_status(run_id, "failed", error="cancelled; resumed by the user")
        orch.start(run_id)
        return {"run_id": run_id, "started": True}

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: int) -> Dict[str, Any]:
        if orch.is_active(run_id):
            raise HTTPException(409, "Cancel the run before deleting it")
        with orch.store() as s:
            run = _run_or_404(s, run_id)
            _purge_traceability(orch.cfg, run["document_id"], run["repo_id"])
            s.delete_run(run_id)
        if run["workdir"]:
            shutil.rmtree(run["workdir"], ignore_errors=True)
        vectors_cache.pop(run_id, None)
        return {"run_id": run_id, "deleted": True}

    # -- review -----------------------------------------------------------------

    @app.get("/api/runs/{run_id}/review")
    def get_review(run_id: int) -> Dict[str, Any]:
        with orch.store() as s:
            run = _run_or_404(s, run_id)
            items = s.review_items(run_id)
            stage = s.stage(run_id, "review")
            prepared = s.stage(run_id, "prepare_review")["status"] == "done"
        requirements = []
        if prepared:
            out = SRSOutputs.load(Path(run["workdir"]) / "srs")
            requirements = [{"index": i, "requirement_id": r.get("requirement_id"), "title": r.get("title"),
                             "type": r.get("type"), "subtype": r.get("subtype"),
                             "location": {k: v for k, v in (r.get("source") or {}).items()
                                          if k in ("section", "page", "paragraph", "table", "row") and v is not None}}
                            for i, r in enumerate(out.requirements)]
        return jsonable_encoder({"ready": prepared, "status": stage["status"],
                                 "counts": review_counts(_items(items)), "items": items,
                                 "requirements": requirements, "resolutions": RESOLUTIONS})

    @app.get("/api/runs/{run_id}/document")
    def get_document(run_id: int) -> Dict[str, Any]:
        with orch.store() as s:
            run = _run_or_404(s, run_id)
        path = Path(run["workdir"]) / "srs" / "document_blocks.json"
        if not path.exists():
            raise HTTPException(404, "The SRS has not been parsed yet")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/runs/{run_id}/review/targets")
    def merge_targets(run_id: int, item: str, limit: int = Query(6, ge=1, le=50)) -> Dict[str, Any]:
        with orch.store() as s:
            run = _run_or_404(s, run_id)
            items = {i["item_key"]: i for i in s.review_items(run_id)}
        if item not in items:
            raise HTTPException(404, f"No review item {item!r}")
        out = SRSOutputs.load(Path(run["workdir"]) / "srs")
        dropped = {i["payload"].get("index") for i in items.values()
                   if i["payload"].get("kind") == "requirement" and i["resolution"] in ("discarded", "merged")}
        own = items[item]["payload"].get("index")
        reqs = [(i, r) for i, r in enumerate(out.requirements)
                if i not in dropped and i != own and r.get("requirement_id")]
        cache = vectors_cache.setdefault(run_id, {})
        embedder = orch.embedder_factory()
        missing = {str(i): (r.get("normalized_text") or r.get("raw_text") or "") for i, r in reqs
                   if str(i) not in cache}
        missing = {k: t for k, t in missing.items() if t.strip()}
        if missing:
            cache.update({k: v.vector for k, v in embedder.embed_batch(missing).items()})
        p = items[item]["payload"]
        text = p.get("normalized_text") or p.get("source_text") or ""
        if not text.strip():
            return {"targets": []}
        q = embedder.embed(text).vector
        ranked = sorted(((round(_cosine(q, cache[str(i)]), 3), r) for i, r in reqs if str(i) in cache),
                        key=lambda x: -x[0])[:limit]
        suggestion = (p.get("suggestion") or {}).get("target")
        return {"targets": [{"requirement_id": r["requirement_id"], "title": r.get("title"), "similarity": sim,
                             "suggested": r["requirement_id"] == suggestion} for sim, r in ranked]}

    def _check_resolution(resolution: str) -> None:
        if resolution not in RESOLUTIONS:
            raise HTTPException(400, f"resolution must be one of {', '.join(RESOLUTIONS)}")

    def _review_open(s, run_id: int) -> Dict[str, Any]:
        run = _run_or_404(s, run_id)
        if s.stage(run_id, "review")["status"] == "done":
            raise HTTPException(409, "The review is already complete")
        return run

    @app.put("/api/runs/{run_id}/review/items/{item_key:path}")
    def resolve_item(run_id: int, item_key: str, body: Resolution) -> Dict[str, Any]:
        _check_resolution(body.resolution)
        if body.resolution == "merged" and not body.data.get("into"):
            raise HTTPException(400, "A merge needs data.into (the target requirement ID)")
        if body.resolution == "edited" and not str(body.data.get("text") or "").strip():
            raise HTTPException(400, "An edit needs data.text")
        with orch.store() as s:
            _review_open(s, run_id)
            if not s.resolve_review_item(run_id, item_key, body.resolution, body.data):
                raise HTTPException(404, f"No review item {item_key!r}")
            counts = review_counts(_items(s.review_items(run_id)))
            s.update_stage(run_id, "review", done=counts["resolved"])
        return {"key": item_key, "resolution": body.resolution, "counts": counts}

    @app.delete("/api/runs/{run_id}/review/items/{item_key:path}")
    def undo_item(run_id: int, item_key: str) -> Dict[str, Any]:
        with orch.store() as s:
            _review_open(s, run_id)
            if not s.resolve_review_item(run_id, item_key, None):
                raise HTTPException(404, f"No review item {item_key!r}")
            counts = review_counts(_items(s.review_items(run_id)))
            s.update_stage(run_id, "review", done=counts["resolved"])
        return {"key": item_key, "resolution": None, "counts": counts}

    @app.post("/api/runs/{run_id}/review/bulk")
    def bulk(run_id: int, body: BulkResolution) -> Dict[str, Any]:
        if body.resolution not in ("kept", "discarded", "unreviewed"):
            raise HTTPException(400, "Bulk actions support kept, discarded and unreviewed")
        with orch.store() as s:
            _review_open(s, run_id)
            missing = [k for k in body.keys if not s.resolve_review_item(run_id, k, body.resolution, {})]
            counts = review_counts(_items(s.review_items(run_id)))
            s.update_stage(run_id, "review", done=counts["resolved"])
        return {"resolved": len(body.keys) - len(missing), "missing": missing, "counts": counts}

    @app.post("/api/runs/{run_id}/review/skip-remaining")
    def skip_remaining(run_id: int) -> Dict[str, Any]:
        with orch.store() as s:
            _review_open(s, run_id)
        n = orch.skip_remaining(run_id)
        with orch.store() as s:
            counts = review_counts(_items(s.review_items(run_id)))
            s.update_stage(run_id, "review", done=counts["resolved"])
        return {"skipped": n, "counts": counts}

    @app.post("/api/runs/{run_id}/review/complete")
    def complete_review(run_id: int) -> Dict[str, Any]:
        with orch.store() as s:
            run = _review_open(s, run_id)
            if run["status"] in ("cancelled",):
                raise HTTPException(409, "The run was cancelled")
        result = orch.complete_review(run_id)          # ReviewError -> 409 with item keys
        orch.start(run_id)                              # no-op while the lanes are still running
        return {"run_id": run_id, **result}

    # -- results ------------------------------------------------------------------

    def _reader(run_id: int) -> ResultsReader:
        with orch.store() as s:
            run = _run_or_404(s, run_id)
            overrides = s.latest_overrides(run_id)
            source = (s.stage(run_id, "fetch")["detail"].get("source") or {}).get("root")
        return ResultsReader(orch.cfg, run, overrides, Path(source) if source else None)

    @app.get("/api/runs/{run_id}/results")
    def results(run_id: int) -> Dict[str, Any]:
        with _reader(run_id) as r:
            if not r.ready:
                return {"ready": False, "summary": None, "requirements": []}
            rows = r.table()
            return jsonable_encoder({"ready": True, "summary": r.summary(rows), "requirements": rows})

    @app.get("/api/runs/{run_id}/requirements/{requirement_id}")
    def requirement_detail(run_id: int, requirement_id: str) -> Dict[str, Any]:
        with _reader(run_id) as r:
            detail = r.detail(requirement_id) if r.ready else None
        if detail is None:
            raise HTTPException(404, f"No requirement {requirement_id!r} in run {run_id}")
        with orch.store() as s:
            overrides = s.override_history(run_id, requirement_id)
        detail["history"] = sorted(
            detail["history"] + [{"kind": "override", "status": o["status"], "note": o["note"], "at": o["created_at"]}
                                 for o in overrides],
            key=lambda h: h["at"], reverse=True)
        return jsonable_encoder(detail)

    @app.post("/api/runs/{run_id}/requirements/{requirement_id}/override")
    def override(run_id: int, requirement_id: str, body: Override) -> Dict[str, Any]:
        if body.status not in OVERRIDE_STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(OVERRIDE_STATUSES)}")
        with _reader(run_id) as r:
            if not r.ready or not any(x["requirement_id"] == requirement_id for x in r.requirements()):
                raise HTTPException(404, f"No requirement {requirement_id!r} in run {run_id}")
        with orch.store() as s:
            s.add_override(run_id, requirement_id, body.status, (body.note or "").strip() or None)
            s.add_event(run_id, f"{requirement_id}: verdict "
                                + ("override cleared" if body.status == "cleared"
                                   else f"set to {body.status.replace('_', ' ')} by a reviewer"),
                        stage="results")
        with _reader(run_id) as r:
            row = next(x for x in r.table() if x["requirement_id"] == requirement_id)
        return jsonable_encoder({"requirement_id": requirement_id, "verdict": row["verdict"]})

    @app.post("/api/runs/{run_id}/verify")
    def reverify(run_id: int, body: Reverify) -> Dict[str, Any]:
        if not body.requirement_ids:
            raise HTTPException(400, "Select at least one requirement")
        with _reader(run_id) as r:
            if r.run["status"] != "completed":
                raise HTTPException(409, "Re-verification needs a completed run")
            known = {x["requirement_id"] for x in r.requirements()}
        unknown = [rid for rid in body.requirement_ids if rid not in known]
        if unknown:
            raise HTTPException(404, f"Unknown requirement(s): {', '.join(unknown)}")
        try:
            orch.start_reverify(run_id, body.requirement_ids)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"run_id": run_id, "verifying": body.requirement_ids}

    @app.get("/api/runs/{run_id}/search")
    def search(run_id: int, q: str = "", limit: int = Query(10, ge=1, le=50)) -> Dict[str, Any]:
        """Find requirements and code by keyword or sentence (hybrid search over this run)."""
        with _reader(run_id) as r:
            if not r.run.get("document_id") and not r.run.get("repo_id"):
                return {"query": q, "mode": "empty", "requirements": [], "components": [],
                        "scope": {"requirements": False, "code": False}}
            return jsonable_encoder(search_run(r, orch.embedder_factory(), q, limit=limit))

    @app.get("/api/runs/{run_id}/code")
    def code_view(run_id: int) -> Dict[str, Any]:
        with _reader(run_id) as r:
            return jsonable_encoder(r.code_view())

    @app.get("/api/runs/{run_id}/code/component")
    def code_component(run_id: int, component_id: str) -> Dict[str, Any]:
        with _reader(run_id) as r:
            comp = r.component(component_id) if r.run["repo_id"] else None
        if comp is None:
            raise HTTPException(404, f"No component {component_id!r}")
        return jsonable_encoder(comp)

    @app.get("/api/runs/{run_id}/files")
    def source_file(run_id: int, path: str) -> Dict[str, Any]:
        with _reader(run_id) as r:
            full = r.safe_source_path(path)
            if full is None or not full.is_file():
                raise HTTPException(404, f"No file {path!r} in the run's source")
            lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"path": path, "lines": [{"n": i, "text": t} for i, t in enumerate(lines, start=1)]}

    @app.get("/api/runs/{run_id}/export.csv")
    def export_csv(run_id: int):
        with _reader(run_id) as r:
            if not r.ready:
                raise HTTPException(409, "No results yet")
            body = r.export_csv()
        return Response(body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="tracelight-run-{run_id}.csv"'})

    @app.get("/api/runs/{run_id}/export.json")
    def export_json(run_id: int):
        with _reader(run_id) as r:
            if not r.ready:
                raise HTTPException(409, "No results yet")
            body = json.dumps(jsonable_encoder(r.export_json()), indent=2, ensure_ascii=False)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="tracelight-run-{run_id}.json"'})

    return app


def _purge_traceability(cfg: TraceabilityConfig, document_id: Optional[str], repo_id: Optional[str]) -> None:
    """Remove a run's document and repository (requirements, components, links and
    verifications cascade)."""
    import psycopg2

    if not document_id and not repo_id:
        return
    conn = psycopg2.connect(cfg.build_dsn())
    try:
        with conn, conn.cursor() as cur:
            for table, col, value in ((cfg.table_srs_documents, "document_id", document_id),
                                      (cfg.table_repositories, "repo_id", repo_id)):
                if not value:
                    continue
                cur.execute("SELECT to_regclass(%s)", (table,))
                if cur.fetchone()[0] is not None:
                    cur.execute(f"DELETE FROM {table} WHERE {col} = %s", (value,))
    finally:
        conn.close()
