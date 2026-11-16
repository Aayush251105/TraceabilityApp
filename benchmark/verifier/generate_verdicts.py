"""
Verifier benchmark — Step 1: run every model on the fixed cases (results/verifier/cases.json).

Uses the unmodified traceability Verifier (prompt verify-v2.3, clause splitting,
quote-anchored citation checks, aggregation) and OllamaClient (temperature 0,
seed 42, num_ctx 8192). Only the database access is replaced: the evidence
context is built from the case's components instead of the components table,
and nothing is persisted. Only the model changes between runs.

    SRS_to_code_traceability/.venv/bin/python TraceabilityApp/benchmark/verifier/generate_verdicts.py --all
    SRS_to_code_traceability/.venv/bin/python TraceabilityApp/benchmark/verifier/generate_verdicts.py --model mistral-7b [--overwrite]

Writes results/verifier/raw_generations/<model>.json (progress is checkpointed
per case, so a stopped run resumes).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from common.codeindex import load_components  # noqa: E402
from common.config import load_config, ws_path  # noqa: E402

from traceability.verification.context import build_context  # noqa: E402
from traceability.verification.llm import OllamaClient  # noqa: E402
from traceability.verification.verifier import Verifier, VerifierConfig  # noqa: E402


class BenchVerifier(Verifier):
    """Verifier without a database: links carry their component dicts."""

    def __init__(self, llm, config: VerifierConfig | None = None):
        self._store = None
        self._resolver = None
        self._llm = llm
        self.config = config or VerifierConfig()
        self.last_context = None

    def _context(self, links):
        items = [{**l["component"], "link_pk": l["link_pk"], "role": l["evidence"]["role"]} for l in links]
        ctx = build_context(items, max_chars=self.config.max_context_chars,
                            max_lines_direct=self.config.max_lines_direct,
                            max_lines_supporting=self.config.max_lines_supporting)
        self.last_context = ctx
        return ctx

    def _persist(self, row, link_rows, pipeline_version):
        pass


def make_links(case: Dict[str, Any], comps: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    links = []
    for i, c in enumerate(case["components"], start=1):
        comp = comps[c["component_id"]]
        links.append({"link_pk": i, "comp_pk": i, "req_pk": 1, "status": "pending_verification",
                      "evidence": {"role": c["role"], "rank": i},
                      "component": {k: comp[k] for k in ("component_id", "component_type", "relative_path",
                                                         "start_line", "end_line", "source_code")} | {"comp_pk": i}})
    return links


def run_model(cfg, entry, cases, comps_by_pair, out: Path) -> None:
    done: Dict[str, Any] = {}
    if out.exists():
        done = json.loads(out.read_text(encoding="utf-8")).get("cases", {})
    llm = OllamaClient(model=entry["ollama_model"], host=cfg["ollama"]["host"], timeout=cfg["ollama"]["timeout_s"])
    verifier = BenchVerifier(llm)
    started = time.time()
    prev = sum(v["seconds"] for v in done.values())
    for n, case in enumerate(cases, 1):
        if case["case_id"] in done:
            continue
        req = {"req_pk": 1, "requirement_id": case["requirement_id"], "title": None,
               "raw_text": case["requirement_text"], "type": None, "conditions": [], "constraints": [],
               "error_conditions": [], "sub_requirements": []}
        t0 = time.time()
        res = verifier.verify_requirement(req, make_links(case, comps_by_pair[case["pair"]]))
        secs = time.time() - t0
        ctx = verifier.last_context
        done[case["case_id"]] = {"seconds": round(secs, 1), "status": res["status"], "error": res["error"],
                                 "claims": res["claims"], "summary": verifier._summary,
                                 "claim_splits": res.get("claim_splits"),
                                 "context_text": ctx.text if ctx else ""}
        print(f"  [{n}/{len(cases)}] {case['case_id']}: {res['status']} (expected {case['expected']}) "
              f"{secs:.0f}s", flush=True)
        if n % 5 == 0 or n == len(cases):
            _save(out, entry, done)
    _save(out, entry, done)
    print(f"  done in {time.time() - started + prev:.0f}s", flush=True)


def _save(out: Path, entry, done) -> None:
    out.write_text(json.dumps({"model": entry["name"], "ollama_model": entry["ollama_model"],
                               "seconds": round(sum(v["seconds"] for v in done.values()), 1),
                               "cases": done}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--model", action="append")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    root = ws_path(cfg["paths"]["verifier_results"])
    cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    comps_by_pair = {}
    for pair in cfg["pairs"]:
        gold = json.loads((ws_path(cfg["paths"]["gold_json"]) / f"{pair['id']}.json").read_text(encoding="utf-8"))
        comps_by_pair[pair["id"]] = {c["component_id"]: c for c in load_components(cfg, pair["id"], gold)}
    out_dir = root / "raw_generations"
    out_dir.mkdir(parents=True, exist_ok=True)
    for m in cfg["models"]:
        if not args.all and m["name"] not in args.model:
            continue
        out = out_dir / f"{m['name']}.json"
        if args.overwrite and out.exists():
            out.unlink()
        if out.exists() and len(json.loads(out.read_text(encoding="utf-8"))["cases"]) >= len(cases):
            print(f"skip {m['name']} (complete)")
            continue
        print(f"\n=== verifier {m['name']} ({m['ollama_model']})", flush=True)
        run_model(cfg, m, cases, comps_by_pair, out)


if __name__ == "__main__":
    main()
