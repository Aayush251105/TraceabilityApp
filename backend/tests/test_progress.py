from datetime import datetime, timedelta, timezone

from tracelight.api.progress import overall, rail, run_progress, stage_view
from tracelight.orchestrator.state import STAGES

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def stage(key, status="queued", done=0, total=None, started=None, finished=None, **kw):
    lane = next(s.lane for s in STAGES if s.key == key)
    return {"stage": key, "lane": lane, "status": status, "done": done, "total": total,
            "started_at": started, "finished_at": finished, "error": None, "detail": {}, **kw}


def all_stages(**overrides):
    return [overrides.get(s.key) or stage(s.key) for s in STAGES]


def test_eta_from_rate():
    v = stage_view(stage("docstrings", "running", done=10, total=40, started=NOW - timedelta(seconds=100)), NOW)
    assert v["elapsed_seconds"] == 100 and v["eta_seconds"] == 300 and v["fraction"] == 0.25


def test_no_eta_before_first_item_or_when_not_running():
    assert stage_view(stage("verify", "running", done=0, total=39, started=NOW), NOW)["eta_seconds"] is None
    done = stage_view(stage("map", "done", done=39, total=39, started=NOW - timedelta(seconds=5), finished=NOW), NOW)
    assert done["eta_seconds"] is None and done["elapsed_seconds"] == 5 and done["fraction"] == 1.0


def test_overall_counts_the_slower_lane():
    views = {s["stage"]: stage_view(s, NOW) for s in all_stages(
        fetch=stage("fetch", "done"), docstrings=stage("docstrings", "running", done=0, total=40, started=NOW),
        extract=stage("extract", "done"), prepare_review=stage("prepare_review", "done"))}
    o = overall(views)
    assert 0 < o["fraction"] < 0.1           # lane B finished, lane A barely started
    finished = {k: stage_view(stage(k, "done"), NOW) for k in views}
    assert overall(finished)["fraction"] == 1.0


def test_remaining_is_the_longest_running_eta():
    views = {s["stage"]: stage_view(s, NOW) for s in all_stages(
        docstrings=stage("docstrings", "running", done=10, total=40, started=NOW - timedelta(seconds=100)),
        extract=stage("extract", "running", done=5, total=10, started=NOW - timedelta(seconds=50)))}
    assert overall(views)["remaining_seconds"] == 300


def test_rail_statuses():
    views = {s["stage"]: stage_view(s, NOW) for s in all_stages(
        fetch=stage("fetch", "done", started=NOW - timedelta(seconds=60), finished=NOW - timedelta(seconds=55)),
        docstrings=stage("docstrings", "running", started=NOW - timedelta(seconds=55)),
        extract=stage("extract", "done"), prepare_review=stage("prepare_review", "done"),
        review=stage("review", "waiting", done=2, total=7))}
    r = {x["group"]: x for x in rail(views)}
    assert r["ingest"]["status"] == "running" and r["review"]["status"] == "waiting"
    assert r["search"]["status"] == "queued" and r["review"]["total"] == 7
    views["verify"] = stage_view(stage("verify", "failed", error="boom"), NOW)
    assert {x["group"]: x for x in rail(views)}["verify"]["status"] == "failed"


def test_run_progress_shape():
    p = run_progress(all_stages(), NOW)
    assert [s["stage"] for s in p["stages"]][0] == "fetch" and len(p["rail"]) == 6
    assert p["overall"]["fraction"] == 0.0
