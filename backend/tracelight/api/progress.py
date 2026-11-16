"""
Progress view of a run: elapsed time, ETA and percentages for the pipeline
page, computed from the stored stages (pure functions, no database access).

ETA of a running stage = elapsed / done × remaining (once something is done).
The overall percentage weights stages by their typical share of the run
time; the two ingestion lanes run in parallel, so the ingest step counts the
slower lane.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..orchestrator.state import STAGE_BY_KEY, STAGES

# Typical share of the run time per stage (relative weights).
WEIGHTS = {"fetch": 1, "docstrings": 40, "index_code": 2, "extract": 15, "prepare_review": 1,
           "index_srs": 2, "search": 4, "map": 1, "verify": 30, "results": 1}
LANE_A = ("fetch", "docstrings", "index_code")
LANE_B = ("extract", "prepare_review")

RAIL = (("ingest", "Ingest"), ("review", "Review"), ("search", "Search"), ("map", "Map"),
        ("verify", "Verify"), ("results", "Results"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def stage_view(st: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _now()
    started, finished = st.get("started_at"), st.get("finished_at")
    elapsed = None
    if started:
        elapsed = ((finished or now) - started).total_seconds()
    done, total = st.get("done") or 0, st.get("total")
    fraction = None
    if st["status"] in ("done", "skipped"):
        fraction = 1.0
    elif total:
        fraction = min(1.0, done / total)
    eta = None
    if st["status"] == "running" and elapsed is not None and total and 0 < done < total:
        eta = elapsed / done * (total - done)
    d = STAGE_BY_KEY[st["stage"]]
    return {"stage": st["stage"], "label": d.label, "lane": st.get("lane"), "group": d.group, "unit": d.unit,
            "status": st["status"], "done": done, "total": total, "fraction": fraction,
            "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
            "eta_seconds": round(eta, 1) if eta is not None else None,
            "started_at": started, "finished_at": finished, "error": st.get("error"),
            "detail": st.get("detail") or {}}


def _stage_fraction(v: Dict[str, Any]) -> float:
    if v["status"] in ("done", "skipped"):
        return 1.0
    if v["status"] == "running":
        return v["fraction"] or 0.02
    return 0.0


def overall(views: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Overall fraction and remaining-time estimate (None when unknown)."""
    lane_w = {lane: sum(WEIGHTS[k] for k in keys) for lane, keys in (("A", LANE_A), ("B", LANE_B))}
    ingest_w = max(lane_w.values())
    lane_frac = {lane: sum(WEIGHTS[k] * _stage_fraction(views[k]) for k in keys) / lane_w[lane]
                 for lane, keys in (("A", LANE_A), ("B", LANE_B))}
    ingest_frac = min(lane_frac.values())          # ingest is done when the slower lane is
    rest = [k for k in WEIGHTS if k not in LANE_A + LANE_B]
    total_w = ingest_w + sum(WEIGHTS[k] for k in rest)
    frac = (ingest_w * ingest_frac + sum(WEIGHTS[k] * _stage_fraction(views[k]) for k in rest)) / total_w

    remaining = None
    running = [v for v in views.values() if v["status"] == "running"]
    if running and all(v["eta_seconds"] is not None for v in running):
        remaining = max(v["eta_seconds"] for v in running)
    return {"fraction": round(frac, 4), "remaining_seconds": remaining}


def rail(views: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The six steps of the stage rail with a combined status each."""
    out = []
    for group, label in RAIL:
        members = [v for v in views.values() if v["group"] == group]
        statuses = {v["status"] for v in members}
        if "failed" in statuses:
            status = "failed"
        elif "waiting" in statuses:
            status = "waiting"
        elif "running" in statuses:
            status = "running"
        elif "cancelled" in statuses:
            status = "cancelled"
        elif statuses <= {"done", "skipped"}:
            status = "done"
        elif "done" in statuses:
            status = "running"            # some parts done, the rest queued (e.g. one lane finished)
        else:
            status = "queued"
        started = [v["started_at"] for v in members if v["started_at"]]
        finished = [v["finished_at"] for v in members if v["finished_at"]]
        elapsed = None
        if started:
            end = max(finished) if status == "done" and finished else _now()
            elapsed = (end - min(started)).total_seconds()
        main = max(members, key=lambda v: v["total"] or 0)
        out.append({"group": group, "label": label, "status": status, "done": main["done"],
                    "total": main["total"], "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None})
    return out


def run_progress(stages: List[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, Any]:
    views = {st["stage"]: stage_view(st, now) for st in stages}
    return {"stages": [views[s.key] for s in STAGES if s.key in views],
            "rail": rail(views), "overall": overall(views)}
