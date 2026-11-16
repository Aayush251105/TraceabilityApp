"""
Compile results/srs_agent/extractor/final_report.md from the result JSONs.
Run standalone to regenerate the report without re-running evaluations:

    SRS_to_code_traceability/.venv/bin/python TraceabilityApp/benchmark/srs_agent/report_generator.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from common.config import load_config, ws_path  # noqa: E402
from common.report import f3, pct, standard_report  # noqa: E402
from srs_agent import prompts  # noqa: E402

OBJECTIVE_COLS = [
    ("Success", "success", pct),
    ("Field Fill", "field_fill", f3),
    ("Grounding", "grounding", f3),
    ("Values Kept", "values_kept", f3),
    ("List Items", "list_items", f3),
    ("Retr. MRR", "mrr", f3),
]


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def write_report(cfg, out: Path, models, n_common: int, sample) -> None:
    objective = _load(out / "objective" / "objective.json") or {}
    pointwise = _load(out / "llm_judgments" / "pointwise" / "pointwise_summary.json")
    pairwise = _load(out / "llm_judgments" / "pairwise" / "pairwise_summary.json")
    seconds = {m: o.get("seconds") for m, o in objective.items()}
    raw = out / "raw_generations"
    for m in models:
        g = _load(raw / f"{m['name']}.json")
        if g:
            seconds[m["name"]] = g["seconds"]
    n = len(models)
    cand = next(iter(objective.values()), {}).get("candidates", "?")
    targets = next(iter(objective.values()), {}).get("n_retrieval_targets", "?")
    retr_rows = ["## 5b. Retrieval Proxy Detail", "",
                 "MRR of the gold **primary** components when the model's fields are used as the search query "
                 "(the pipeline's own `texts.requirement_text` builder: title, retrieval_text, normalized_text, "
                 f"actions, entities, domain_terms, synonyms, sub_requirements). {targets} retained requirements "
                 "match a gold requirement with primary links; a failed extraction scores 0.", ""]
    from common.report import md_table
    order = [r["model"] for r in pairwise["ranking"]] if pairwise else [m["name"] for m in models]
    retr_rows += md_table(["Model", "BM25 MRR", "Dense (MiniLM) MRR", "Mean"],
                          [[m, f3(objective.get(m, {}).get("mrr_bm25")), f3(objective.get(m, {}).get("mrr_dense")),
                            f3(objective.get(m, {}).get("mrr"))] for m in order])
    text = standard_report(
        title="SRS Agent Extractor — Model Benchmark Report",
        models=models, time_label="Extraction Time",
        time_desc=(f"Wall-clock time for `SRSAgent.extract` over the same {cand} retained candidates "
                   "(4 SRS documents), including retries."),
        seconds=seconds, pairwise=pairwise, n_judges_pair=n - 2, objective=objective,
        objective_cols=OBJECTIVE_COLS, objective_title="Objective Extraction Metrics (no LLM)",
        objective_desc=(
            "*Success* = schema-valid extractions / candidates. *Field Fill* = share of core fields filled "
            "(title, normalized_text, actor, actions, entities, domain_terms, retrieval_text). *Grounding* = "
            "share of content words in the descriptive fields that occur in the requirement text (invention "
            "proxy). *Values Kept* = numbers in the text that survive into the fields. *List Items* = `- ` list "
            "items covered by sub_requirements. *Retr. MRR* = mean of BM25 and dense MRR (section 5b)."),
        pointwise=pointwise, rubrics=prompts.RUBRICS, extra_sections=["\n".join(retr_rows)],
        methodology=[
            f"**Input:** the candidates retained by the default judge (`{cfg['srs_default_judge']}`), identical "
            "for every model. Unmodified `SRSAgent.extract` (same prompt, 3 attempts, temperature 0, seed 42).",
            f"**Items sampled for LLM judging:** {len(sample)} (from {n_common} extracted by all models); "
            f"seed {cfg['sampling']['seed']}. The same items are used for every model and every pair.",
            "**Judging:** Leave-one-out. Point-wise: judges are the other N−1 models. Pairwise: the other N−2.",
            "**Pairwise position bias control:** each pair run twice with A/B swapped; a win needs agreement "
            "across both orderings, otherwise TIE.",
            f"**Point-wise scoring:** {len(prompts.RUBRICS)} dimensions ({', '.join(prompts.RUBRICS)}), 1–5. "
            "Unlike DocAgent (one call per dimension), all dimensions are scored in one call per item.",
            f"**Judge decoding:** temperature {cfg['ollama']['temperature']}, max {cfg['ollama']['max_tokens']} "
            "tokens; qwen3 judges run with thinking disabled.",
            "**Objective metrics:** pure text matching against the requirement text and the draft gold links; "
            "no LLM involved.",
        ])
    (out / "final_report.md").write_text(text, encoding="utf-8")


def main():
    cfg = load_config()
    out = ws_path(cfg["paths"]["srs_results"]) / "extractor"
    models = [m for m in cfg["models"] if (out / "raw_generations" / f"{m['name']}.json").exists()]
    sample = _load(out / "sample_items.json") or []
    write_report(cfg, out, models, len(sample), sample)
    print(out / "final_report.md")


if __name__ == "__main__":
    main()
