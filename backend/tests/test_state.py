import pytest

from tracelight.orchestrator.state import STAGE_KEYS, STAGES

from conftest import requires_pg

pytestmark = requires_pg


def _new_run(store, **kw):
    params = dict(name="Run", source_kind="zip", source_ref="repo.zip", srs_filename="srs.docx",
                  workdir="/tmp/run", settings={"models": {"srs": "llama3.1"}})
    params.update(kw)
    return store.create_run(**params)


def test_stage_definitions_are_unique_and_ordered():
    assert len(set(STAGE_KEYS)) == len(STAGE_KEYS)
    assert STAGE_KEYS[0] == "fetch" and STAGE_KEYS[-1] == "results"
    assert {s.lane for s in STAGES} == {"A", "B", None}


def test_create_run_creates_all_stages_queued(run_store):
    run_id = _new_run(run_store)
    run = run_store.get_run(run_id)
    assert run["status"] == "queued"
    assert run["settings"]["models"]["srs"] == "llama3.1"
    stages = run_store.stages(run_id)
    assert [s["stage"] for s in stages] == list(STAGE_KEYS)
    assert all(s["status"] == "queued" and s["done"] == 0 for s in stages)


def test_run_status_timestamps(run_store):
    run_id = _new_run(run_store)
    run_store.set_run_status(run_id, "running")
    run = run_store.get_run(run_id)
    assert run["started_at"] is not None and run["finished_at"] is None
    run_store.set_run_status(run_id, "failed", error="boom")
    run = run_store.get_run(run_id)
    assert run["status"] == "failed" and run["error"] == "boom" and run["finished_at"] is not None
    run_store.set_run_status(run_id, "running")     # resume clears the error
    run = run_store.get_run(run_id)
    assert run["error"] is None and run["finished_at"] is None


def test_unknown_status_rejected(run_store):
    run_id = _new_run(run_store)
    with pytest.raises(AssertionError):
        run_store.set_run_status(run_id, "exploded")


def test_update_run_fields_and_summary(run_store):
    run_id = _new_run(run_store)
    run_store.update_run(run_id, commit_sha="abc123", summary={"supported": 3})
    run = run_store.get_run(run_id)
    assert run["commit_sha"] == "abc123" and run["summary"] == {"supported": 3}


def test_stage_progress_and_detail_merge(run_store):
    run_id = _new_run(run_store)
    run_store.update_stage(run_id, "docstrings", status="running", total=41, detail={"current": "A.f"})
    run_store.update_stage(run_id, "docstrings", done=5, detail={"agent": "writer"})
    st = run_store.stage(run_id, "docstrings")
    assert st["status"] == "running" and st["done"] == 5 and st["total"] == 41
    assert st["detail"] == {"current": "A.f", "agent": "writer"}
    assert st["started_at"] is not None
    run_store.update_stage(run_id, "docstrings", status="done")
    assert run_store.stage(run_id, "docstrings")["finished_at"] is not None
    run_store.update_stage(run_id, "docstrings", reset=True, status="queued")
    st = run_store.stage(run_id, "docstrings")
    assert st["done"] == 0 and st["total"] is None and st["detail"] == {} and st["started_at"] is None


def test_events_paging_and_lane_tail(run_store):
    run_id = _new_run(run_store)
    ids = [run_store.add_event(run_id, f"a{i}", lane="A", stage="docstrings") for i in range(5)]
    run_store.add_event(run_id, "b0", lane="B", level="warn", data={"k": 1})
    run_store.add_event(run_id, "global")
    assert [e["message"] for e in run_store.events(run_id, after=ids[2])] == ["a3", "a4", "b0", "global"]
    assert [e["message"] for e in run_store.last_events(run_id, "A", limit=2)] == ["a3", "a4"]
    assert [e["message"] for e in run_store.last_events(run_id, None)] == ["global"]
    b = run_store.events(run_id, lane="B")[0]
    assert b["level"] == "warn" and b["data"] == {"k": 1}


def test_review_items_replace_and_resolve(run_store):
    run_id = _new_run(run_store)
    run_store.replace_review_items(run_id, [
        {"key": "cand:C-0001", "category": "uncertain", "payload": {"text": "x"}},
        {"key": "req:FR-001", "category": "flagged", "requirement_id": "FR-001"},
        {"key": "skip:1", "category": "uncertain", "resolution": "discarded",
         "resolution_data": {"auto": True}},
    ])
    items = run_store.review_items(run_id)
    assert [i["item_key"] for i in items] == ["cand:C-0001", "req:FR-001", "skip:1"]
    assert items[2]["resolution"] == "discarded" and items[2]["resolved_at"] is not None
    assert run_store.resolve_review_item(run_id, "req:FR-001", "merged", {"into": "FR-002"})
    assert not run_store.resolve_review_item(run_id, "missing", "kept")
    item = {i["item_key"]: i for i in run_store.review_items(run_id)}["req:FR-001"]
    assert item["resolution"] == "merged" and item["resolution_data"] == {"into": "FR-002"}
    run_store.resolve_review_item(run_id, "req:FR-001", None)          # undo
    item = {i["item_key"]: i for i in run_store.review_items(run_id)}["req:FR-001"]
    assert item["resolution"] is None and item["resolved_at"] is None


def test_overrides_latest_wins(run_store):
    run_id = _new_run(run_store)
    run_store.add_override(run_id, "FR-001", "supported", "checked by hand")
    run_store.add_override(run_id, "FR-001", "partially_supported", "missing one rule")
    run_store.add_override(run_id, "FR-002", "not_found", None)
    latest = run_store.latest_overrides(run_id)
    assert latest["FR-001"]["status"] == "partially_supported"
    assert len(run_store.override_history(run_id, "FR-001")) == 2


def test_delete_run_cascades(run_store):
    run_id = _new_run(run_store)
    run_store.add_event(run_id, "x")
    run_store.delete_run(run_id)
    assert run_store.get_run(run_id) is None
    assert run_store.stages(run_id) == [] and run_store.events(run_id) == []


def test_runs_listing(run_store):
    a = _new_run(run_store, name="first")
    b = _new_run(run_store, name="second")
    run_store.set_run_status(b, "running")
    assert [r["run_id"] for r in run_store.list_runs()] == [b, a]
    assert [r["run_id"] for r in run_store.runs_with_status(["running"])] == [b]
