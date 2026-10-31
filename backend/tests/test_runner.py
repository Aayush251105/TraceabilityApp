"""
End-to-end runner tests on a tiny shop repository.

Real: DocAgent (placeholder mode, no LLM), source fetching, the embedding
model, ingestion, search, mapping, the verifier pipeline, the run state.
Fake: the SRS Agent (writes known requirements) and the verifier's LLM
(cites the first line of the first component) — no Ollama needed.

Traceability tables use their own test prefix (test_tlapp_*) in traceability_test.
"""

import json
import re
import threading
from pathlib import Path

import pytest

from tracelight.orchestrator.agents import AgentCancelled, AgentError, AgentResult, check_agents
from tracelight.orchestrator.review import ReviewError
from tracelight.orchestrator.runner import Agents, Orchestrator
from tracelight.settings import AppPaths, SettingsStore

from conftest import TEST_PREFIX, make_cfg, requires_pg

TR_TABLES = dict(
    table_migrations="test_tlapp_tr_migrations", table_srs_documents="test_tlapp_tr_srs_documents",
    table_requirements="test_tlapp_tr_requirements", table_repositories="test_tlapp_tr_repositories",
    table_components="test_tlapp_tr_code_components", table_docstrings="test_tlapp_tr_docstrings",
    table_relationships="test_tlapp_tr_relationships", table_trace_links="test_tlapp_tr_trace_links",
    table_verifications="test_tlapp_tr_verifications")

PATHS = AppPaths.from_env()
_agents = check_agents(PATHS)
pytestmark = [requires_pg, pytest.mark.skipif(
    not (_agents["docagent"]["dir_ok"] and _agents["docagent"]["python_ok"]),
    reason="DocAgent venv not available (placeholder mode is used)")]

CART = '''"""Shopping cart."""


class Cart:
    def __init__(self):
        self.items = []

    def add_item(self, name, price):
        if price < 0:
            raise ValueError("price must not be negative")
        self.items.append((name, price))

    def total(self):
        return sum(price for _, price in self.items)


def apply_discount(total, code):
    if code == "SAVE10":
        return total * 0.9
    return total
'''


def _req(rid, title, text):
    return {"requirement_id": rid, "id_source": "source", "parent_requirement_id": None, "raw_text": text,
            "normalized_text": text, "type": "functional", "subtype": "general", "title": title,
            "candidate_confidence": "high", "candidate_reason": "", "review_required": False,
            "actor": [], "actions": [], "entities": [], "inputs": [], "outputs": [], "preconditions": [],
            "postconditions": [], "conditions": [], "constraints": [], "error_conditions": [],
            "domain_terms": [], "synonyms": [], "sub_requirements": [], "retrieval_text": text,
            "source": {"page": 1, "paragraph": 1}}


REQUIREMENTS = [
    _req("FR-001", "Add an item to the cart", "The system shall add an item with a name and a price to the cart."),
    _req("FR-002", "Cart total", "The system shall compute the cart total as the sum of the item prices."),
    _req("FR-003", "Discount code", "The system shall apply a 10% discount for the code SAVE10."),
    _req("FR-004", "Export orders", "The system shall export all orders to a CSV file every night."),
]
UNCERTAIN = {"candidate_id": "C-0005", "decision": "uncertain", "confidence": "low", "reason": "no shall",
             "text": "Customers usually pay at the till.", "source": {"page": 2}}


class FakeSRS:
    """Stands in for agents.run_srs: writes the SRS Agent's output files and emits events."""

    def __init__(self, *, fail_with=None, uncertain=True):
        self.calls = []
        self.fail_with = fail_with
        self.uncertain = uncertain

    def __call__(self, paths, settings, mode, *, out_dir, log_path, input_path=None, candidates_path=None,
                 on_event=None, cancel=None):
        self.calls.append(mode)
        if self.fail_with:
            raise self.fail_with
        out_dir.mkdir(parents=True, exist_ok=True)
        emit = on_event or (lambda e: None)
        if mode == "extract-candidates":
            cands = json.loads(Path(candidates_path).read_text(encoding="utf-8"))
            reqs = [{**_req("REQ-001", "Pay at the till", c["text"]), "id_source": "generated",
                     "candidate_id": c["candidate_id"]} for c in cands]
            (out_dir / "requirements.json").write_text(json.dumps(reqs), encoding="utf-8")
            return AgentResult(0, [{"event": "finished", "requirements": len(reqs)}])
        emit({"event": "candidates", "count": 5, "confidence": {"high": 4, "low": 1}})
        emit({"event": "judge_batch_done", "batch": 1, "batches": 1, "kept": 4, "discarded": 0,
              "uncertain": 1 if self.uncertain else 0, "decisions": [UNCERTAIN] if self.uncertain else []})
        for i, r in enumerate(REQUIREMENTS, start=1):
            emit({"event": "requirement_start", "index": i, "total": 4, "requirement_id": r["requirement_id"]})
            emit({"event": "requirement_done", "index": i, "total": 4, "requirement_id": r["requirement_id"],
                  "title": r["title"]})
        (out_dir / "requirements.json").write_text(json.dumps(REQUIREMENTS), encoding="utf-8")
        report = {"segmentation": {"skipped_sections": [], "skipped_tables": [], "warnings": []},
                  "candidate_review": [UNCERTAIN] if self.uncertain else [], "extraction_failures": []}
        (out_dir / "extraction_report.json").write_text(json.dumps(report), encoding="utf-8")
        (out_dir / "candidates.json").write_text(json.dumps([{"text": r["raw_text"]} for r in REQUIREMENTS]
                                                            + [{"text": UNCERTAIN["text"]}]), encoding="utf-8")
        finished = {"event": "finished", "requirements": 4, "uncertain": int(self.uncertain)}
        emit(finished)
        return AgentResult(0, [finished])


class FakeLLM:
    """Verifier model: 'supported', citing the first shown line of C1 — except for export requirements."""
    model = "fake-verifier"

    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def chat_json(self, system, user, schema):
        self.calls += 1
        if self.error:
            raise self.error
        n = len(re.findall(r"^\s+\d+\. ", user.split("Source code")[0], flags=re.M))
        m = re.search(r"\[C1\][^\n]*\n\s*(\d+) \| (.*)", user)
        line, code = int(m.group(1)), m.group(2).strip()
        if "export" in user.split("Claims to verify")[0].lower():
            claims = [{"claim_index": i, "verdict": "not_supported", "evidence": [], "rationale": "no export code"}
                      for i in range(1, n + 1)]
        else:
            claims = [{"claim_index": i, "verdict": "supported", "rationale": "shown",
                       "evidence": [{"component": "C1", "start_line": line, "end_line": line, "quote": code}]}
                      for i in range(1, n + 1)]
        return {"claims": claims, "summary": "fake"}


@pytest.fixture()
def env(tmp_path):
    import psycopg2

    cfg = make_cfg()
    cfg_tr = type(cfg)(pg_dbname=cfg.pg_dbname, pg_user=cfg.pg_user, pg_password=cfg.pg_password, **TR_TABLES)
    conn = psycopg2.connect(cfg.build_dsn())
    conn.autocommit = True
    with conn.cursor() as cur:
        for t in list(TR_TABLES.values()) + [f"{TEST_PREFIX}{n}" for n in
                                             ("overrides", "review_items", "run_events", "run_stages", "runs")]:
            assert t.startswith("test_")
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    conn.close()

    repo = tmp_path / "shop"
    (repo / "shop").mkdir(parents=True)
    (repo / "shop" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "shop" / "cart.py").write_text(CART, encoding="utf-8")
    srs = tmp_path / "Shop_SRS.md"
    srs.write_text("# Shop SRS\nFR-001 The system shall add items.\n", encoding="utf-8")
    paths = AppPaths(workspace=PATHS.workspace, data_dir=tmp_path / "data", docagent_dir=PATHS.docagent_dir,
                     docagent_python=PATHS.docagent_python, srsagent_dir=PATHS.srsagent_dir,
                     srsagent_python=PATHS.srsagent_python)
    settings = SettingsStore(paths.settings_file)
    settings.save({"verification": {"claims": "rules"}})
    return {"cfg": cfg_tr, "paths": paths, "settings": settings, "repo": repo, "srs": srs}


def make_orch(env, *, srs=None, llm=None, docagent=None, **kw):
    agents = Agents(run_srs=srs or FakeSRS())
    if docagent:
        agents.run_docagent = docagent
    o = Orchestrator(env["cfg"], env["paths"], prefix=TEST_PREFIX, settings_store=env["settings"],
                     agents=agents, llm_factory=lambda s: llm or FakeLLM(), docagent_test_mode="placeholder",
                     preflight=False, **kw)
    o.init()
    return o


def new_run(o, env, **overrides):
    return o.create_run(source_kind="folder", source_ref=str(env["repo"]), srs_path=str(env["srs"]),
                        overrides=overrides or None)


def stages(o, run_id):
    with o.store() as s:
        return {st["stage"]: st for st in s.stages(run_id)}


def run_row(o, run_id):
    with o.store() as s:
        return s.get_run(run_id)


# ---------------------------------------------------------------------------


def test_full_run_pauses_for_review_then_completes(env):
    o = make_orch(env)
    run_id = new_run(o, env)
    run_dir = Path(run_row(o, run_id)["workdir"])
    assert (run_dir / "input" / "Shop_SRS.md").exists()

    assert o.execute(run_id) == "paused"
    st = stages(o, run_id)
    assert all(st[k]["status"] == "done" for k in ("fetch", "docstrings", "index_code", "extract", "prepare_review"))
    assert st["review"]["status"] == "waiting"
    assert st["docstrings"]["total"] == 5 and st["docstrings"]["done"] == 5    # Cart, __init__, add_item, total, apply_discount
    assert st["extract"]["done"] == 4 and st["index_code"]["detail"]["report"]["components"] == 5
    assert run_row(o, run_id)["status"] == "paused"
    review = o.review_state(run_id)
    assert review["counts"]["open"] == 1 and review["items"][0]["item_key"] == "cand:C-0005"

    with pytest.raises(ReviewError):
        o.complete_review(run_id)                      # the item is still open
    with o.store() as s:
        s.resolve_review_item(run_id, "cand:C-0005", "discarded")
    assert o.complete_review(run_id)["requirements"] == 4

    assert o.execute(run_id) == "completed"
    run = run_row(o, run_id)
    assert run["document_id"] == f"run-{run_id}-Shop_SRS" and run["repo_id"] == f"run-{run_id}-shop"
    summary = run["summary"]
    assert summary["requirements"] == 4
    assert summary["status_counts"].get("not_supported_by_candidate") == 1      # FR-004 export
    assert summary["status_counts"].get("supported", 0) >= 2
    st = stages(o, run_id)
    assert all(v["status"] == "done" for v in st.values())
    assert st["search"]["done"] == 4 and st["verify"]["done"] == 4
    assert (run_dir / "reviewed_requirements.json").exists()
    assert (run_dir / "source" / "shop" / "cart.py").read_text(encoding="utf-8") == CART   # pristine
    assert (run_dir / "work" / "shop" / "cart.py").read_text(encoding="utf-8") != CART     # DocAgent's copy
    with o.store() as s:
        events = s.events(run_id, limit=10000)
    messages = [e["message"] for e in events]
    assert any("Waiting for your review" in m for m in messages)
    assert any(m.startswith("FR-004 → not supported") for m in messages)
    assert {e["lane"] for e in events} >= {"A", "B", None}
    assert o.execute(run_id) == "completed"            # executing a completed run is a no-op


def test_sequential_kept_candidate_is_extracted(env):
    srs = FakeSRS()
    o = make_orch(env, srs=srs)
    run_id = new_run(o, env, ingest={"parallel": False})
    assert o.execute(run_id) == "paused"
    with o.store() as s:
        s.resolve_review_item(run_id, "cand:C-0005", "kept", {"requirement_id": "FR-005"})
    o.complete_review(run_id)
    assert o.execute(run_id) == "completed"
    assert srs.calls == ["extract", "extract-candidates"]
    reviewed = json.loads((Path(run_row(o, run_id)["workdir"]) / "reviewed_requirements.json").read_text(encoding="utf-8"))
    assert [r["requirement_id"] for r in reviewed][-1] == "REQ-001"
    assert reviewed[-1]["review"]["status"] == "kept"
    assert run_row(o, run_id)["summary"]["requirements"] == 5


def test_auto_approve_keeps_open_items_unreviewed(env):
    o = make_orch(env)
    run_id = new_run(o, env)
    assert o.execute(run_id, auto_approve=True) == "completed"
    summary = run_row(o, run_id)["summary"]
    assert summary["requirements"] == 5 and summary["unreviewed"] == ["REQ-001"]


def test_clean_extraction_still_waits_for_continue(env):
    o = make_orch(env, srs=FakeSRS(uncertain=False))
    run_id = new_run(o, env)
    assert o.execute(run_id) == "paused"
    assert o.review_state(run_id)["counts"]["total"] == 0
    o.complete_review(run_id)
    assert o.execute(run_id) == "completed"


def test_lane_failure_fails_run_and_resume_reuses_done_stages(env):
    o = make_orch(env, srs=FakeSRS(fail_with=AgentError("ConnectionError: Ollama unreachable")))
    run_id = new_run(o, env)
    assert o.execute(run_id) == "failed"
    st = stages(o, run_id)
    assert st["extract"]["status"] == "failed" and "Ollama unreachable" in st["extract"]["error"]
    assert st["index_code"]["status"] == "done"            # the other lane finished
    assert "Extract requirements" in run_row(o, run_id)["error"]
    finished_at = st["docstrings"]["finished_at"]

    o.agents.run_srs = FakeSRS()
    assert o.execute(run_id) == "paused"
    st = stages(o, run_id)
    assert st["docstrings"]["finished_at"] == finished_at  # not re-run
    assert run_row(o, run_id)["error"] is None


def test_cancel_during_docagent_then_resume(env):
    started = threading.Event()

    def slow_docagent(paths, settings, *, cancel, **kw):
        started.set()
        cancel.wait(30)
        raise AgentCancelled("stopped by user")

    o = make_orch(env, docagent=slow_docagent)
    run_id = new_run(o, env)
    thread = o.start(run_id)
    assert started.wait(30)
    assert o.cancel(run_id)
    thread.join(60)
    assert run_row(o, run_id)["status"] == "cancelled"
    assert stages(o, run_id)["docstrings"]["status"] == "cancelled"

    # a cancelled run is final for execute(); resuming means starting the remaining stages again
    with o.store() as s:
        s.set_run_status(run_id, "failed", error="cancelled")
    from tracelight.orchestrator.agents import run_docagent
    o.agents.run_docagent = run_docagent
    assert o.execute(run_id) == "paused"


def test_cancel_paused_run(env):
    o = make_orch(env)
    run_id = new_run(o, env)
    assert o.execute(run_id) == "paused"
    assert o.cancel(run_id)
    assert run_row(o, run_id)["status"] == "cancelled"
    assert stages(o, run_id)["review"]["status"] == "cancelled"


def test_verifier_model_failures_stop_the_stage(env):
    from traceability.verification.llm import LLMError

    o = make_orch(env, llm=FakeLLM(error=LLMError("connection refused")))
    run_id = new_run(o, env)
    assert o.execute(run_id, auto_approve=True) == "failed"
    st = stages(o, run_id)
    assert st["verify"]["status"] == "failed" and "3 times in a row" in st["verify"]["error"]
    assert st["verify"]["done"] == 3


def test_preflight_reports_unreachable_ollama(env):
    o = make_orch(env)
    o.preflight = True
    run_id = new_run(o, env, ollama_host="http://127.0.0.1:9")
    assert o.execute(run_id) == "failed"
    run = run_row(o, run_id)
    assert run["error"].startswith("Cannot start") and "not reachable" in run["error"]
    assert stages(o, run_id)["fetch"]["status"] == "queued"


def test_recover_interrupted(env):
    o = make_orch(env)
    run_id = new_run(o, env)
    with o.store() as s:
        s.set_run_status(run_id, "running")
        s.update_stage(run_id, "docstrings", status="running")
    assert o.recover_interrupted() == [run_id]
    run = run_row(o, run_id)
    assert run["status"] == "failed" and "Interrupted" in run["error"]
    assert stages(o, run_id)["docstrings"]["status"] == "failed"


def test_create_run_validates_inputs(env, tmp_path):
    from tracelight.orchestrator.source import SourceError

    o = make_orch(env)
    with pytest.raises(SourceError, match="Unsupported"):
        o.create_run(source_kind="folder", source_ref=str(env["repo"]), srs_path=str(tmp_path / "x.exe"))
    with pytest.raises(SourceError, match="Folder not found"):
        o.create_run(source_kind="folder", source_ref=str(tmp_path / "nope"), srs_path=str(env["srs"]))
    with pytest.raises(SourceError, match="ZIP file not found"):
        o.create_run(source_kind="zip", source_ref=str(tmp_path / "a.zip"), srs_path=str(env["srs"]))
