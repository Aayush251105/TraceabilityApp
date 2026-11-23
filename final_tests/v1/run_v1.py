"""
FINAL TESTING V1 — step 2: run Tracelight end to end on each test pair.

    SRS_to_code_traceability/.venv/bin/python final_tests/v1/run_v1.py [--pairs A B ...] [--force]

Per pair (smallest first):
  1. `git -C code rev-parse HEAD` must equal the workbook's repo_info commit_sha (else stop);
  2. Tracelight CLI: run --folder <code> --srs <srs> --auto-approve (+ the V1 models);
  3. check that the stored component IDs match the gold's (prefix mismatch => all scores 0);
  4. record run ID, document/repo IDs, stage timings, models and settings in runs.json.
Pairs already recorded as completed are skipped (resumable); --force re-runs them.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent.parent
BACKEND = WS / "TraceabilityApp" / "backend"
PY = WS / "SRS_to_code_traceability" / ".venv" / "bin" / "python"
DATA = WS / "datasets" / "Data"
RUNS = HERE / "runs.json"
LOGS = HERE / "results" / "logs"
LABEL = "V1 - human-annotated gold"

PAIRS = ["Travel-Agency-Automation-System", "Books-Recommender-System", "Virtual-clinic", "ProClinic"]
MODELS = {"docagent": "yi-coder:9b", "srs": "qwen3:8b", "judge": "qwen3:4b", "verifier": "qwen2.5-coder:7b"}
OLLAMA_HOST = None      # --ollama-host
SEQUENTIAL = False      # --sequential

sys.path.insert(0, str(BACKEND))


def repo_info(pair: str) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(DATA / pair / f"{pair}_gold.xlsx", read_only=True, data_only=True)
    info = {str(r[0]).strip(): r[1] for r in wb["repo_info"].iter_rows(values_only=True) if r and r[0]}
    links = wb["links"]
    rows = list(links.iter_rows(values_only=True))
    head = [str(c).strip().lower() if c else "" for c in rows[0]]
    ci = head.index("component")
    # row 1 = header, row 2 = the instruction row ("pick from the dropdown ...")
    info["gold_components"] = sorted({str(r[ci]).strip() for r in rows[2:] if r and r[ci]})
    return info


def stored_components(repo_id: str) -> set:
    from traceability.config import TraceabilityConfig
    import psycopg2
    cfg = TraceabilityConfig()
    with psycopg2.connect(cfg.build_dsn()) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT c.component_id FROM {cfg.table_components} c JOIN {cfg.table_repositories} r "
                    "USING (repo_pk) WHERE r.repo_id = %s", (repo_id,))
        return {r[0] for r in cur.fetchall()}


def run_record(run_id: int) -> dict:
    from traceability.config import TraceabilityConfig
    from tracelight.orchestrator.state import RunStore
    with RunStore(TraceabilityConfig()) as s:
        run = s.get_run(run_id)
        stages = s.stages(run_id)
    return json.loads(json.dumps({"run": run, "stages": stages}, default=str))


def stage_minutes(stages) -> dict:
    out = {}
    for st in stages:
        a, b = st.get("started_at"), st.get("finished_at")
        if a and b:
            from datetime import datetime
            fa = datetime.fromisoformat(str(a)); fb = datetime.fromisoformat(str(b))
            out[st["stage"]] = round((fb - fa).total_seconds() / 60, 2)
    return out


def load_runs() -> dict:
    return json.loads(RUNS.read_text()) if RUNS.exists() else {"label": LABEL, "pairs": {}}


def save_runs(d: dict) -> None:
    RUNS.write_text(json.dumps(d, indent=2, default=str), encoding="utf-8")


PARTS = HERE / "results" / "runs_parts"


def save_pair(pair: str, record: dict) -> None:
    """Record one pair without overwriting the others (several run_v1 processes may run at once):
    reload runs.json, replace this pair, and keep a copy in results/runs_parts/<pair>.json."""
    PARTS.mkdir(parents=True, exist_ok=True)
    (PARTS / f"{pair}.json").write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    d = load_runs()
    d["pairs"][pair] = record
    save_runs(d)


def merge_parts() -> None:
    """Put every results/runs_parts/<pair>.json back into runs.json (newest record per pair)."""
    d = load_runs()
    for p in sorted(PARTS.glob("*.json")):
        d["pairs"][p.stem] = json.loads(p.read_text())
        print(f"merged {p.stem}: run {d['pairs'][p.stem]['run_id']}")
    save_runs(d)


def run_pair(pair: str, runs: dict) -> None:
    code = DATA / pair / "code"
    info = repo_info(pair)
    head = subprocess.run(["git", "-C", str(code), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != str(info["commit_sha"]).strip():
        raise SystemExit(f"STOP {pair}: code HEAD {head} != workbook commit_sha {info['commit_sha']}")
    srs = DATA / pair / str(info["srs_file"]).strip()
    if not srs.is_file():
        raise SystemExit(f"STOP {pair}: SRS file not found: {srs}")
    cmd = [str(PY), "-m", "tracelight.orchestrator.cli", "run", "--folder", str(code), "--srs", str(srs),
           "--auto-approve", "--name", f"v1-{pair}"] + [x for role, m in MODELS.items()
                                                        for x in (f"--model-{role}", m)]
    if SEQUENTIAL:
        cmd.append("--sequential")
    # A run copies the settings when it is created, so a temporary settings file pointing at another
    # Ollama server affects only this run; it is removed as soon as the run exists.
    temp_settings = None
    if OLLAMA_HOST:
        temp_settings = WS / "TraceabilityApp" / "data" / "settings.json"
        if temp_settings.exists():
            raise SystemExit(f"STOP {pair}: {temp_settings} exists; not overwriting saved settings")
        temp_settings.write_text(json.dumps({"ollama_host": OLLAMA_HOST}) + "\n", encoding="utf-8")
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{pair}.log"
    print(f"\n=== {pair}: commit {head[:10]} OK; {info.get('python_components')} components; SRS {srs.name}",
          flush=True)
    t0 = time.time()
    run_id = None
    with log.open("w") as fh:
        proc = subprocess.Popen(cmd, cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            fh.write(line); fh.flush()
            m = re.match(r"Run (\d+) created", line)
            if m:
                run_id = int(m.group(1))
                if temp_settings is not None:
                    temp_settings.unlink(missing_ok=True); temp_settings = None
                print(f"  run {run_id} created (log: {log.relative_to(WS)})", flush=True)
            if re.search(r"(stage|finished|failed|error|Run \d+:)", line, re.I) and len(line) < 300:
                print("  " + line.rstrip(), flush=True)
        rc = proc.wait()
    if temp_settings is not None:
        temp_settings.unlink(missing_ok=True)
    wall = time.time() - t0
    if run_id is None:
        raise SystemExit(f"STOP {pair}: CLI did not create a run (rc={rc}); see {log}")
    rec = run_record(run_id)
    run = rec["run"]
    stored = stored_components(run["repo_id"]) if run.get("repo_id") else set()
    gold = set(info["gold_components"])
    found = sorted(gold & stored)
    missing = sorted(gold - stored)
    id_check = {"gold_components": len(gold), "found": len(found), "missing": missing,
                "stored_components": len(stored),
                "ok": bool(gold) and len(found) / len(gold) >= 0.9}
    if gold and not found:
        id_check["warning"] = "no gold component found in the run: component ID prefix mismatch"
    record = {
        "label": LABEL, "status": run["status"], "error": run.get("error"), "cli_returncode": rc,
        "run_id": run_id, "document_id": run.get("document_id"), "repo_id": run.get("repo_id"),
        "commit_sha": head, "srs_file": srs.name, "python_components": info.get("python_components"),
        "models": run.get("settings", {}).get("models") if isinstance(run.get("settings"), dict) else MODELS,
        "settings": run.get("settings"), "wall_minutes": round(wall / 60, 2),
        "stage_minutes": stage_minutes(rec["stages"]), "stages": rec["stages"], "component_id_check": id_check,
        "log": str(log.relative_to(WS)),
        "ollama_host": OLLAMA_HOST,
    }
    runs["pairs"][pair] = record
    save_pair(pair, record)
    print(f"  -> {run['status']} in {wall / 60:.1f} min; gold components found {len(found)}/{len(gold)}"
          + ("" if id_check["ok"] else "  ** ID CHECK FAILED **"), flush=True)


def eta_before(pair: str, runs: dict) -> None:
    done = [p for p in runs["pairs"].values() if p.get("status") == "completed"]
    rate = [(p["stage_minutes"].get("docstrings", 0), p["python_components"]) for p in done
            if p.get("python_components")]
    mins = sum(r[0] for r in rate); comps = sum(r[1] for r in rate)
    if comps:
        per = mins / comps
        info = repo_info(pair)
        n = int(info.get("python_components") or 0)
        other = sum(p["wall_minutes"] - p["stage_minutes"].get("docstrings", 0) for p in done) / max(len(done), 1)
        print(f"\nETA {pair}: {n} components x {per * 60:.0f} s/component (measured) = {n * per / 60:.1f} h "
              f"docstrings + ~{other:.0f} min other stages", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="*", default=PAIRS)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--recheck", action="store_true", help="only recompute the component ID checks in runs.json")
    ap.add_argument("--merge-parts", action="store_true", help="only merge results/runs_parts/*.json into runs.json")
    ap.add_argument("--ollama-host", help="run on this Ollama server (e.g. a second one, to use the GPU in parallel)")
    ap.add_argument("--sequential", action="store_true", help="SRS lane, then code lane (fewer models loaded at once)")
    args = ap.parse_args()
    global OLLAMA_HOST, SEQUENTIAL
    OLLAMA_HOST, SEQUENTIAL = args.ollama_host, args.sequential
    if args.merge_parts:
        merge_parts()
        return
    runs = load_runs()
    if args.recheck:
        for pair, rec in runs["pairs"].items():
            gold = set(repo_info(pair)["gold_components"])
            stored = stored_components(rec["repo_id"])
            found = gold & stored
            rec["component_id_check"] = {"gold_components": len(gold), "found": len(found),
                                         "missing": sorted(gold - stored), "stored_components": len(stored),
                                         "ok": bool(gold) and len(found) / len(gold) >= 0.9}
            print(f"{pair}: gold components found {len(found)}/{len(gold)}")
        save_runs(runs)
        return
    for pair in args.pairs:
        prev = runs["pairs"].get(pair)
        if prev and prev.get("status") == "completed" and not args.force:
            print(f"skip {pair}: run {prev['run_id']} already completed")
            continue
        eta_before(pair, runs)
        run_pair(pair, runs)
    print("\nall pairs done", flush=True)


if __name__ == "__main__":
    main()
