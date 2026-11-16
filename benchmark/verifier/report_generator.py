"""
Compile results/verifier/final_report.md from the result JSONs (standalone re-run is safe):

    SRS_to_code_traceability/.venv/bin/python TraceabilityApp/benchmark/verifier/report_generator.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from common.config import load_config, ws_path  # noqa: E402
from common.report import f3, md_table, pct, standard_report  # noqa: E402
from verifier import prompts  # noqa: E402
from verifier.objective import CLASSES  # noqa: E402

OBJECTIVE_COLS = [
    ("Exact Acc.", "exact_accuracy", f3),
    ("Macro-F1", "macro_f1", f3),
    ("Support Acc.", "support_accuracy", f3),
    ("False Support ↓", "false_support_rate", pct),
    ("Impl. Recall", "implemented_recall", pct),
    ("Abstain", "abstain_rate", pct),
    ("Citation Valid.", "citation_validity", f3),
]

SHORT = {"supported": "sup", "partially_supported": "part", "not_supported_by_candidate": "not",
         "insufficient_evidence": "insuf", "not_found": "nf"}


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def write_report(cfg, root: Path, models, cases, sample) -> None:
    objective = _load(root / "objective" / "objective.json") or {}
    pointwise = _load(root / "llm_judgments" / "pointwise" / "pointwise_summary.json")
    pairwise = _load(root / "llm_judgments" / "pairwise" / "pairwise_summary.json")
    seconds = {m: o.get("seconds") for m, o in objective.items()}
    order = [r["model"] for r in pairwise["ranking"]] if pairwise else [m["name"] for m in models]
    kinds = Counter(c["kind"] for c in cases)
    exp = Counter(c["expected"] for c in cases)

    conf = ["## 5b. Verdict Confusion (expected → predicted)", "",
            "Counts per expected class: `sup` supported, `part` partially_supported, `not` "
            "not_supported_by_candidate, `insuf` insufficient_evidence (abstain / model failure).", ""]
    conf += md_table(["Model"] + [f"{SHORT[e]}→{SHORT[p]}" for e in CLASSES for p in
                                  ("supported", "partially_supported", "not_supported_by_candidate",
                                   "insufficient_evidence")] + ["Failures", "Per-class F1 (sup/part/not)"],
                     [[m] + [objective.get(m, {}).get("confusion", {}).get(e, {}).get(p, 0) for e in CLASSES
                             for p in ("supported", "partially_supported", "not_supported_by_candidate",
                                       "insufficient_evidence")] +
                      [objective.get(m, {}).get("model_failures", "—"),
                       " / ".join(f3(objective.get(m, {}).get("f1_per_class", {}).get(k)) for k in CLASSES)]
                      for m in order])
    text = standard_report(
        title="Verifier — Model Benchmark Report",
        models=models, time_label="Verification Time",
        time_desc=(f"Wall-clock time to verify all {len(cases)} cases (claim splitting + verification calls, "
                   "with retries)."),
        seconds=seconds, pairwise=pairwise, n_judges_pair=len(models) - 2, objective=objective,
        objective_cols=OBJECTIVE_COLS, objective_title="Objective Verdict Metrics (no LLM)",
        objective_desc=(
            f"{len(cases)} cases: {kinds['gold']} *gold* (requirement + its gold primary/supporting code; "
            f"expected supported for implemented, partially_supported for partial), {kinds['distractor']} "
            f"*distractor* (same requirement + the 2 most similar unlinked components) and {kinds['absent']} "
            f"*absent* (not-implemented requirement + its 2 most similar components); expected classes: "
            f"{exp['supported']} supported, {exp['partially_supported']} partial, "
            f"{exp['not_supported_by_candidate']} not supported. *False Support* = negative cases judged "
            "supported/partial (lower is better; the costliest error). *Impl. Recall* = implemented requirements "
            "with their gold code judged supported/partial. *Abstain* = insufficient_evidence. *Citation Valid.* = "
            "evidence references that passed the quote-anchored check."),
        pointwise=pointwise, rubrics=prompts.RUBRICS, extra_sections=["\n".join(conf)],
        methodology=[
            "**Cases:** built once from the draft gold (`build_cases.py`); search and mapping are bypassed so only "
            "the verifier model varies. The requirement text is the gold (verbatim SRS) text.",
            "**Verifier code:** the unmodified `traceability.verification.Verifier` (prompt verify-v2.3, clause "
            "splitting, quote-anchored citation validation, aggregation) and `OllamaClient` (temperature 0, "
            "seed 42, num_ctx 8192). Only database reads/writes are replaced.",
            f"**Items sampled for LLM judging:** {len(sample)} cases (half gold, half negative), seed "
            f"{cfg['sampling']['seed']}; the same cases for every model and pair. The judge sees the requirement, "
            f"the code shown to the verifier (truncated at {prompts.MAX_CODE_CHARS} chars) and the report.",
            "**Judging:** Leave-one-out. Point-wise: judges are the other N−1 models. Pairwise: the other N−2.",
            "**Pairwise position bias control:** each pair run twice with A/B swapped; a win needs agreement "
            "across both orderings, otherwise TIE.",
            f"**Point-wise scoring:** {len(prompts.RUBRICS)} dimensions ({', '.join(prompts.RUBRICS)}), 1–5, all "
            "scored in one call per item (DocAgent used one call per dimension).",
            "**Judges are the same 7B–9B models being compared;** the objective verdict metrics are the more "
            "reliable signal for choosing the verifier.",
        ])
    (root / "final_report.md").write_text(text, encoding="utf-8")


def main():
    cfg = load_config()
    root = ws_path(cfg["paths"]["verifier_results"])
    cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    models = [m for m in cfg["models"] if (root / "raw_generations" / f"{m['name']}.json").exists()]
    write_report(cfg, root, models, cases, _load(root / "sample_items.json") or [])
    print(root / "final_report.md")


if __name__ == "__main__":
    main()
