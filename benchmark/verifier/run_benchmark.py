"""
Verifier benchmark — Step 2: evaluate and report (mirrors DocAgent/benchmark/run_benchmark.py).

  1. objective metrics vs expected verdicts -> objective/objective.json
  2. point-wise LLM judging (leave-one-out)  -> llm_judgments/pointwise/
  3. pairwise LLM judging (leave-one-out)    -> llm_judgments/pairwise/
  4. final_report.md

    SRS_to_code_traceability/.venv/bin/python TraceabilityApp/benchmark/verifier/run_benchmark.py
    ... --skip-objective --skip-pointwise --skip-pairwise     # report only
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from common.config import load_config, ws_path  # noqa: E402
from common import judging  # noqa: E402
from verifier import objective, prompts  # noqa: E402
from verifier.report_generator import write_report  # noqa: E402


def stratified_sample(cases, common, n, seed):
    """Half gold cases, half negative cases, so judges see both kinds of decision."""
    rng = random.Random(seed)
    ok = [c for c in cases if c["case_id"] in common]
    pos = sorted(c["case_id"] for c in ok if c["kind"] == "gold")
    neg = sorted(c["case_id"] for c in ok if c["kind"] != "gold")
    k = min(len(pos), n // 2)
    picked = rng.sample(pos, k) + rng.sample(neg, min(len(neg), n - k))
    return sorted(picked)


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
    root = ws_path(cfg["paths"]["verifier_results"])
    cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    by_id = {c["case_id"]: c for c in cases}
    gens = {}
    for m in cfg["models"]:
        f = root / "raw_generations" / f"{m['name']}.json"
        if f.exists():
            gens[m["name"]] = json.loads(f.read_text(encoding="utf-8"))
    models = [m for m in cfg["models"] if m["name"] in gens]
    names = [m["name"] for m in models]
    items_by_model = {m: g["cases"] for m, g in gens.items()}
    # judge only cases every model completed without a model failure
    common = set.intersection(*({k for k, v in g.items() if not v.get("error")} for g in items_by_model.values()))
    sample = pinned_sample(root / "sample_items.json", common,
                           lambda: stratified_sample(cases, common, cfg["sampling"]["n_samples"], cfg["sampling"]["seed"]))
    ref = next(iter(gens.values()))["cases"]
    contexts = {i: prompts.render_context(by_id[i], ref[i]["context_text"]) for i in sample}
    print(f"{len(models)} models, {len(common)} cases complete for all, sample {len(sample)}")

    if not args.skip_objective:
        print("\n[1/3] objective metrics")
        obj = {m: objective.evaluate(cases, g) for m, g in gens.items()}
        (root / "objective").mkdir(exist_ok=True)
        (root / "objective" / "objective.json").write_text(json.dumps(obj, indent=2), encoding="utf-8")

    kw = dict(models=models, ollama_cfg=cfg["ollama"], items_by_model=items_by_model, item_ids=sample,
              context=lambda i: contexts[i], render=prompts.render_report,
              system=prompts.SYSTEM_PROMPT, task=prompts.TASK)
    pw_dir, pp_dir = root / "llm_judgments" / "pointwise", root / "llm_judgments" / "pairwise"
    if not args.skip_pointwise:
        print("\n[2/3] point-wise judging")
        recs = judging.run_pointwise(rubrics=prompts.RUBRICS, cache_path=pw_dir / "pointwise_results.jsonl", **kw)
        (pw_dir / "pointwise_summary.json").write_text(
            json.dumps(judging.summarize_pointwise(recs, names, list(prompts.RUBRICS)), indent=2), encoding="utf-8")
    if not args.skip_pairwise:
        print("\n[3/3] pairwise judging")
        recs = judging.run_pairwise(criteria=prompts.PAIRWISE_CRITERIA,
                                    cache_path=pp_dir / "pairwise_results.jsonl", **kw)
        (pp_dir / "pairwise_summary.json").write_text(
            json.dumps(judging.summarize_pairwise(recs, names), indent=2), encoding="utf-8")
    if not args.skip_report:
        (root / "sample_items.json").write_text(json.dumps(sample, indent=2), encoding="utf-8")
        write_report(cfg, root, models, cases, sample)
        print(f"\nreport: {root / 'final_report.md'}")


if __name__ == "__main__":
    main()
