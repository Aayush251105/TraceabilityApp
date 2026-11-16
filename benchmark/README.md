# Benchmark — SRS Agent and Verifier Multi-Model Evaluation

This directory benchmarks the two LLM agents of Tracelight other than DocAgent —
the **SRS Agent** (requirement extraction) and the **verifier** — across the same
8 local models compared in `DocAgent/benchmark`. It follows the same design and
report layout as the DocAgent benchmark, and adds objective scores against the
gold annotations of the test pairs.

> **The golds are DRAFT** (AI-drafted 2026-11-15, not yet reviewed by the two
> annotators). Every report is marked provisional. All raw model outputs are
> saved, so the objective metrics can be re-scored from them once the golds are
> frozen (`common/gold.py`, then the `--skip-pointwise --skip-pairwise` /
> `--report-only` runs) without re-running any model.

---

## Design Principles

- **Agent code is never modified.** The benchmark imports and calls the real
  `CandidateJudge`, `SRSAgent.extract` and `Verifier`; only the model name changes.
- **Identical inputs per model.** SRS documents are parsed and segmented once;
  extractors all get the candidates kept by the default judge; verifiers all get
  the same fixed cases.
- **Objective metrics first.** Each agent is scored against the gold (no LLM).
- **Leave-one-out judging** (as in DocAgent). No model judges its own output.
- **Position bias control.** Each pairwise item is judged in both A/B orders; a
  win counts only when the judge agrees across both, otherwise TIE.
- **Win rate is the primary LLM-judged metric.**
- **Resumable.** Generations checkpoint per case; judgments are appended to JSONL caches.

---

## What is benchmarked

| Benchmark | Models | What changes | Objective ground truth |
|---|---|---|---|
| SRS candidate judge | 4 small models (`srs_judge_models`) | the judge that decides keep / discard / uncertain for ambiguous candidates | which candidates are gold requirements (text match) |
| SRS extractor | the 8 models (`models`) | the model that turns each candidate into the structured `Requirement` | requirement text + gold links (field grounding, values, list items, retrieval MRR) |
| Verifier | the 8 models (`models`) | the model inside `Verifier` | expected verdicts from the gold (gold code / distractor code / not implemented) |

The pipeline, not the extractor, sets `requirement_id` and `raw_text`, so *which*
requirements are found depends on detection + the judge; the extractor only
affects the structured fields. That is why the judge has its own benchmark.

---

## Directory Structure

```
benchmark/
├── README.md                      ← this file
├── config.yaml                    ← models, judge models, Ollama, sampling, pairs, paths
├── common/
│   ├── config.py                  ← config loader, workspace paths
│   ├── gold.py                    ← gold workbook (.xlsx) → data/gold/<pair>.json
│   ├── ollama_chat.py             ← stdlib Ollama client for judge calls
│   ├── judging.py                 ← leave-one-out point-wise + pairwise engine (DocAgent protocol)
│   ├── textmatch.py               ← token coverage for text matching
│   ├── codeindex.py               ← pair components + source, BM25
│   └── report.py                  ← DocAgent-style report sections
├── srs_agent/
│   ├── prepare_candidates.py      ← Step 0: parse + detect each SRS once (no LLM)
│   ├── judge_benchmark.py         ← candidate-judge benchmark (+ its report)
│   ├── generate_extractions.py    ← Step 1: extraction per model
│   ├── objective.py               ← no-LLM extraction metrics + retrieval proxy
│   ├── prompts.py                 ← extractor judge rubrics
│   ├── run_benchmark.py           ← Step 2: objective + point-wise + pairwise + report
│   └── report_generator.py
├── verifier/
│   ├── build_cases.py             ← Step 0: fixed cases from the gold
│   ├── generate_verdicts.py       ← Step 1: verification per model (DB-free Verifier)
│   ├── objective.py               ← no-LLM verdict metrics
│   ├── prompts.py                 ← verifier judge rubrics
│   ├── run_benchmark.py           ← Step 2: objective + point-wise + pairwise + report
│   └── report_generator.py
├── data/gold/                     ← converted golds (draft)
└── results/
    ├── srs_agent/
    │   ├── candidates/<pair>.json
    │   ├── judge/{raw_decisions/, judge_metrics.json, final_report.md}
    │   └── extractor/{raw_generations/, objective/, llm_judgments/, final_report.md}
    └── verifier/
        ├── cases.json
        └── {raw_generations/, objective/, llm_judgments/, final_report.md}
```

---

## How to Run

Run from the workspace root (the folder holding `DocAgent/`, `SRSAgent/`,
`SRS_to_code_traceability/`, `TraceabilityApp/`). Ollama must be running with
the models in `config.yaml` pulled. Two venvs are used: `SRSAgent/.venv` for the
SRS Agent steps that call the agent, `SRS_to_code_traceability/.venv` for the rest.

```bash
SRS=SRSAgent/.venv/bin/python
TR=SRS_to_code_traceability/.venv/bin/python
B=TraceabilityApp/benchmark

# 0. gold workbooks -> JSON; SRS candidates; verifier cases
$TR $B/common/gold.py
$SRS $B/srs_agent/prepare_candidates.py
$TR $B/verifier/build_cases.py

# 1. SRS candidate judge (small models) -> results/srs_agent/judge/final_report.md
$SRS $B/srs_agent/judge_benchmark.py

# 2. SRS extractor (8 models)        -> results/srs_agent/extractor/final_report.md
$SRS $B/srs_agent/generate_extractions.py --all
$TR  $B/srs_agent/run_benchmark.py

# 3. Verifier (8 models)             -> results/verifier/final_report.md
$TR $B/verifier/generate_verdicts.py --all
$TR $B/verifier/run_benchmark.py
```

Single model / redo: `--model <name> [--overwrite]`. Report only:
`run_benchmark.py --skip-objective --skip-pointwise --skip-pairwise`, or the
`report_generator.py` scripts; `judge_benchmark.py --report-only`.

---

## Output — `final_report.md`

Same sections as `DocAgent/benchmark/results/final_report.md`:

1. **Pairwise Win Rate Ranking** — primary LLM-judged result.
2. **Generation time** (extraction / verification time).
3. **Head-to-Head Matrix** — W/L/T for every model pair.
4. **Full Metrics Summary** — objective metrics, the 6 LLM dimensions, win rate.
5. **Objective metrics** (DocAgent's section 5 was AST completeness), plus a detail table.
6. **Point-wise LLM Scores** — per-dimension averages (1–5).
7. **Methodology.**

The candidate-judge report has no LLM judging (it is a classifier with a ground
truth): ranking by F1, time, confusion counts, full metrics, per-document results.

---

## Metrics Reference

**SRS candidate judge** — on candidates the judge actually decides (medium/low
detection confidence): precision, recall, F1 (primary), F2, accuracy, uncertain
rate, failed batches, and end-to-end gold requirement recall.

**SRS extractor**

| Metric | Type | Range | Notes |
|---|---|---|---|
| Success | objective | 0–1 | schema-valid extractions / candidates |
| Field Fill | objective | 0–1 | core fields non-empty |
| Grounding | objective | 0–1 | descriptive-field words found in the requirement text (invention proxy) |
| Values Kept | objective | 0–1 | numbers in the text kept in the fields |
| List Items | objective | 0–1 | `- ` items covered by sub_requirements |
| Retr. MRR | objective | 0–1 | gold primary code found with the fields as the query (BM25 + MiniLM, via `texts.requirement_text`) |
| Faithfulness, Completeness, Structure, Normalized Text, Code-Search Usefulness, Conciseness | LLM-judged | 1–5 | leave-one-out |
| **Win Rate** | pairwise | 0–1 | primary LLM-judged metric |

**Verifier**

| Metric | Type | Range | Notes |
|---|---|---|---|
| Exact Acc. / Macro-F1 | objective | 0–1 | 3 classes: supported, partial, not supported |
| Support Acc. | objective | 0–1 | right code vs wrong code |
| False Support ↓ | objective | 0–1 | wrong code judged supported/partial — the costliest error |
| Impl. Recall | objective | 0–1 | implemented requirements + gold code judged supported/partial |
| Abstain | objective | 0–1 | insufficient_evidence |
| Citation Valid. | objective | 0–1 | citations passing the quote-anchored check |
| Verdict, Evidence, Consistency, Reasoning, Clarity, Conciseness | LLM-judged | 1–5 | leave-one-out |
| **Win Rate** | pairwise | 0–1 | primary LLM-judged metric |

For choosing a model, weigh the objective metrics above the LLM-judged ones: the
judges are the same 7B–9B models being compared.

---

## Changes Made to the Existing Codebase

None. The benchmark only imports `SRSAgent` (app, parsers, detector,
`CandidateJudge`, `SRSAgent`), `traceability.verification` (`Verifier`,
`build_context`, `OllamaClient`) and `SRS_to_code_traceability/texts.py`
(`requirement_text`).
