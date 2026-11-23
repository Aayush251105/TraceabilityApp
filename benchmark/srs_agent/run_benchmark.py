"""
SRS Agent extractor benchmark — Step 2: evaluate and report (mirrors DocAgent/benchmark/run_benchmark.py).

Reads results/srs_agent/extractor/raw_generations/<model>.json (from
generate_extractions.py) and runs:
  1. objective metrics (no LLM)            -> objective/objective.json
  2. point-wise LLM judging (leave-one-out) -> llm_judgments/pointwise/
  3. pairwise LLM judging (leave-one-out)   -> llm_judgments/pairwise/
  4. final_report.md

    SRS_to_code_traceability/.venv/bin/python TraceabilityApp/benchmark/srs_agent/run_benchmark.py
    ... --skip-objective --skip-pointwise --skip-pairwise     # report only

Uses the traceability venv (sentence-transformers for the dense retrieval proxy).
Steps are resumable: judgments already in the JSONL caches are not re-run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from common.config import load_config, ws_path  # noqa: E402
from common import judging  # noqa: E402
from srs_agent import objective, prompts  # noqa: E402
from srs_agent.report_generator import write_report  # noqa: E402


def load_generations(cfg):
    raw = ws_path(cfg["paths"]["srs_results"]) / "extractor" / "raw_generations"
    gens = {}
    for m in cfg["models"]:
        f = raw / f"{m['name']}.json"
        if f.exists():
            gens[m["name"]] = json.loads(f.read_text(encoding="utf-8"))
    return gens


def build_items(cfg, gens):
    """item id = '<pair>::<candidate_id>' -> output per model; context = raw text."""
    items_by_model, contexts = {}, {}
    for m, g in gens.items():
        items = {}
        for pair in cfg["pairs"]:
            for r in g["pairs"][pair["id"]]["requirements"]:
                iid = f"{pair['id']}::{r['candidate_id']}"
                items[iid] = r
                src = r.get("source") or {}
                contexts.setdefault(iid, prompts.render_context(r["raw_text"], src.get("section")))
        items_by_model[m] = items
    common = set.intersection(*(set(v) for v in items_by_model.values())) if items_by_model else set()
    return items_by_model, contexts, sorted(common)


def pinned_sample(path, valid, fresh):
    """Reuse the saved sample when every item is still valid for all models, so
    re-running one model does not change the items the other models were judged on."""
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved and all(i in valid for i in saved):
            return saved
        print(f"saved sample {path.name} no longer valid for all models; drawing a new one")
    return fresh()


def main() -> None:
    ap = argparse.ArgumentParser()
    for s in ("objective", "pointwise", "pairwise", "report"):
        ap.add_argument(f"--skip-{s}", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    out = ws_path(cfg["paths"]["srs_results"]) / "extractor"
    gens = load_generations(cfg)
    if not gens:
        sys.exit("no raw generations: run generate_extractions.py --all first")
    models = [m for m in cfg["models"] if m["name"] in gens]
    names = [m["name"] for m in models]
    items_by_model, contexts, common = build_items(cfg, gens)
    sample = pinned_sample(out / "sample_items.json", common,
                           lambda: judging.sample_items(common, cfg["sampling"]["n_samples"], cfg["sampling"]["seed"]))
    print(f"{len(models)} models, {len(common)} items extracted by all, sample {len(sample)}")

    if not args.skip_objective:
        print("\n[1/3] objective metrics")
        objective.evaluate(cfg, gens, out / "objective" / "objective.json")

    common_kw = dict(models=models, ollama_cfg=cfg["ollama"], items_by_model=items_by_model, item_ids=sample,
                     context=lambda i: contexts[i], render=prompts.render_record,
                     system=prompts.SYSTEM_PROMPT, task=prompts.TASK)
    pw_dir = out / "llm_judgments" / "pointwise"
    pp_dir = out / "llm_judgments" / "pairwise"
    if not args.skip_pointwise:
        print("\n[2/3] point-wise judging")
        recs = judging.run_pointwise(rubrics=prompts.RUBRICS, cache_path=pw_dir / "pointwise_results.jsonl",
                                     **common_kw)
        summ = judging.summarize_pointwise(recs, names, list(prompts.RUBRICS))
        (pw_dir / "pointwise_summary.json").write_text(json.dumps(summ, indent=2), encoding="utf-8")
    if not args.skip_pairwise:
        print("\n[3/3] pairwise judging")
        recs = judging.run_pairwise(criteria=prompts.PAIRWISE_CRITERIA,
                                    cache_path=pp_dir / "pairwise_results.jsonl", **common_kw)
        summ = judging.summarize_pairwise(recs, names)
        (pp_dir / "pairwise_summary.json").write_text(json.dumps(summ, indent=2), encoding="utf-8")
    if not args.skip_report:
        (out / "sample_items.json").write_text(json.dumps(sample, indent=2), encoding="utf-8")
        write_report(cfg, out, models, len(common), sample)
        print(f"\nreport: {out / 'final_report.md'}")


if __name__ == "__main__":
    main()
