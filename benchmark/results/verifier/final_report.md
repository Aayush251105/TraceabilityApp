# Verifier — Model Benchmark Report
_Generated: 2026-11-18 04:35_

> **PROVISIONAL.** Ground truth comes from the DRAFT gold workbooks (AI-drafted 2026-11-15, not yet reviewed by the two annotators). Raw outputs are saved, so the objective metrics can be re-scored without re-running any model once the golds are frozen.

## Models Evaluated

- **yi-coder-9b** (`yi-coder:9b`) — verification time: 1h 10m 11s
- **codegemma-7b** (`codegemma:7b`) — verification time: 1h 01m 21s
- **mistral-7b** (`mistral:7b`) — verification time: 1h 00m 55s
- **qwen3-8b** (`qwen3:8b`) — verification time: 7h 36m 18s
- **qwen2.5-coder-7b** (`qwen2.5-coder:7b`) — verification time: 19m 30s
- **codellama-7b** (`codellama:7b`) — verification time: 1h 21m 59s
- **deepseek-coder-6.7b** (`deepseek-coder:6.7b`) — verification time: 1h 07m 49s
- **llama3.1-8b** (`llama3.1:8b`) — verification time: 2h 36m 50s

> **Judge protocol:** Leave-one-out. When model X is evaluated, judges are all other models.

---

## 1. Pairwise Win Rate Ranking

Primary metric. Each matchup is judged by the 6 remaining models.
Position bias is controlled by running each pair in both orderings;
a win is only counted when the judge agrees across both orderings.

| Rank | Model | Win Rate | W | L | T | Total Decisions |
| ---- | ----- | -------- | --- | --- | --- | --------------- |
| 1 | yi-coder-9b | **26.4%** | 111 | 46 | 263 | 420 |
| 2 | codegemma-7b | **19.0%** | 80 | 73 | 267 | 420 |
| 3 | mistral-7b | **18.1%** | 76 | 32 | 312 | 420 |
| 4 | qwen3-8b | **18.1%** | 76 | 57 | 287 | 420 |
| 5 | qwen2.5-coder-7b | **17.1%** | 72 | 69 | 279 | 420 |
| 6 | codellama-7b | **16.7%** | 70 | 126 | 224 | 420 |
| 7 | deepseek-coder-6.7b | **16.4%** | 69 | 77 | 274 | 420 |
| 8 | llama3.1-8b | **10.5%** | 44 | 118 | 258 | 420 |

---

## 2. Verification Time

Wall-clock time to verify all 196 cases (claim splitting + verification calls, with retries).

| Model | Ollama Tag | Verification Time |
| ----- | ---------- | ----------------- |
| yi-coder-9b | `yi-coder:9b` | 1h 10m 11s |
| codegemma-7b | `codegemma:7b` | 1h 01m 21s |
| mistral-7b | `mistral:7b` | 1h 00m 55s |
| qwen3-8b | `qwen3:8b` | 7h 36m 18s |
| qwen2.5-coder-7b | `qwen2.5-coder:7b` | 19m 30s |
| codellama-7b | `codellama:7b` | 1h 21m 59s |
| deepseek-coder-6.7b | `deepseek-coder:6.7b` | 1h 07m 49s |
| llama3.1-8b | `llama3.1:8b` | 2h 36m 50s |

---

## 3. Pairwise Head-to-Head Results

Each cell shows `W / L / T` (wins, losses, ties) for the **row model** against the **column model**.

| Model | yi-coder-9b | codegemma-7b | mistral-7b | qwen3-8b | qwen2.5-coder-7b | codellama-7b | deepseek-coder-6.7b | llama3.1-8b |
| ----- | ----------- | ------------ | ---------- | -------- | ---------------- | ------------ | ------------------- | ----------- |
| **yi-coder-9b** | — | 13/7/40 | 7/8/45 | 10/5/45 | 15/8/37 | 24/6/30 | 16/8/36 | 26/4/30 |
| **codegemma-7b** | 7/13/40 | — | 3/9/48 | 9/12/39 | 9/15/36 | 23/4/33 | 12/10/38 | 17/10/33 |
| **mistral-7b** | 8/7/45 | 9/3/48 | — | 11/4/45 | 5/3/52 | 18/9/33 | 11/5/44 | 14/1/45 |
| **qwen3-8b** | 5/10/45 | 12/9/39 | 4/11/45 | — | 9/5/46 | 20/10/30 | 12/7/41 | 14/5/41 |
| **qwen2.5-coder-7b** | 8/15/37 | 15/9/36 | 3/5/52 | 5/9/46 | — | 15/14/31 | 15/11/34 | 11/6/43 |
| **codellama-7b** | 6/24/30 | 4/23/33 | 9/18/33 | 10/20/30 | 14/15/31 | — | 5/14/41 | 22/12/26 |
| **deepseek-coder-6.7b** | 8/16/36 | 10/12/38 | 5/11/44 | 7/12/41 | 11/15/34 | 14/5/41 | — | 14/6/40 |
| **llama3.1-8b** | 4/26/30 | 10/17/33 | 1/14/45 | 5/14/41 | 6/11/43 | 12/22/26 | 6/14/40 | — |

---

## 4. Full Metrics Summary

Objective metrics need no LLM. LLM-judged scores are 1–5, averaged across leave-one-out judges.

| Model | Verification Time | Exact Acc. | Macro-F1 | Support Acc. | False Support ↓ | Impl. Recall | Abstain | Citation Valid. | Verdict | Evidence | Consist. | Reason. | Clarity | Concise. | LLM Avg | Win Rate |
| ----- | ----------------- | ---------- | -------- | ------------ | --------------- | ------------ | ------- | --------------- | ------- | -------- | -------- | ------- | ------- | -------- | ------- | -------- |
| yi-coder-9b | 1h 10m 11s | 0.286 | 0.257 | 0.602 | 67.0% | 97.9% | 15.8% | 0.964 | 4.571 | 4.529 | 4.814 | 4.686 | 4.686 | 4.657 | 4.657 | **26.4%** |
| codegemma-7b | 1h 01m 21s | 0.357 | 0.346 | 0.546 | 71.7% | 95.7% | 6.6% | 0.913 | 4.471 | 4.457 | 4.786 | 4.543 | 4.643 | 4.671 | 4.595 | **19.0%** |
| mistral-7b | 1h 00m 55s | 0.541 | 0.501 | 0.668 | 44.3% | 89.4% | 2.0% | 0.953 | 4.271 | 4.429 | 4.600 | 4.514 | 4.600 | 4.586 | 4.500 | **18.1%** |
| qwen3-8b | 7h 36m 18s | 0.459 | 0.507 | 0.730 | 14.2% | 78.7% | 26.5% | 0.882 | 3.429 | 3.886 | 4.057 | 4.086 | 4.243 | 4.171 | 3.979 | **18.1%** |
| qwen2.5-coder-7b | 19m 30s | 0.628 | 0.516 | 0.689 | 12.3% | 59.6% | 1.0% | 0.778 | 3.714 | 4.000 | 4.343 | 4.214 | 4.343 | 4.286 | 4.150 | **17.1%** |
| codellama-7b | 1h 21m 59s | 0.265 | 0.260 | 0.469 | 81.1% | 87.2% | 12.8% | 0.851 | 4.357 | 4.343 | 4.529 | 4.371 | 4.400 | 4.386 | 4.398 | **16.7%** |
| deepseek-coder-6.7b | 1h 07m 49s | 0.276 | 0.245 | 0.464 | 97.2% | 97.9% | 2.0% | 0.956 | 4.414 | 4.429 | 4.686 | 4.586 | 4.514 | 4.486 | 4.519 | **16.4%** |
| llama3.1-8b | 2h 36m 50s | 0.474 | 0.482 | 0.730 | 38.7% | 93.6% | 10.7% | 0.971 | 3.841 | 3.971 | 4.464 | 4.159 | 4.304 | 4.261 | 4.167 | **10.5%** |

---

## 5. Objective Verdict Metrics (no LLM)

196 cases: 90 *gold* (requirement + its gold primary/supporting code; expected supported for implemented, partially_supported for partial), 90 *distractor* (same requirement + the 2 most similar unlinked components) and 16 *absent* (not-implemented requirement + its 2 most similar components); expected classes: 47 supported, 43 partial, 106 not supported. *False Support* = negative cases judged supported/partial (lower is better; the costliest error). *Impl. Recall* = implemented requirements with their gold code judged supported/partial. *Abstain* = insufficient_evidence. *Citation Valid.* = evidence references that passed the quote-anchored check.

| Model | Exact Acc. | Macro-F1 | Support Acc. | False Support ↓ | Impl. Recall | Abstain | Citation Valid. |
| ----- | ---------- | -------- | ------------ | --------------- | ------------ | ------- | --------------- |
| yi-coder-9b | 0.286 | 0.257 | 0.602 | 67.0% | 97.9% | 15.8% | 0.964 |
| codegemma-7b | 0.357 | 0.346 | 0.546 | 71.7% | 95.7% | 6.6% | 0.913 |
| mistral-7b | 0.541 | 0.501 | 0.668 | 44.3% | 89.4% | 2.0% | 0.953 |
| qwen3-8b | 0.459 | 0.507 | 0.730 | 14.2% | 78.7% | 26.5% | 0.882 |
| qwen2.5-coder-7b | 0.628 | 0.516 | 0.689 | 12.3% | 59.6% | 1.0% | 0.778 |
| codellama-7b | 0.265 | 0.260 | 0.469 | 81.1% | 87.2% | 12.8% | 0.851 |
| deepseek-coder-6.7b | 0.276 | 0.245 | 0.464 | 97.2% | 97.9% | 2.0% | 0.956 |
| llama3.1-8b | 0.474 | 0.482 | 0.730 | 38.7% | 93.6% | 10.7% | 0.971 |

---

## 6. Point-wise LLM Judge Scores

Each score is 1–5, averaged across all leave-one-out judges and sampled items.

| Model | Verdict Correctness | Evidence Quality | Rationale Consistency | Code Reasoning | Clarity | Conciseness | Judgments | Unparsed |
| ----- | ------------------- | ---------------- | --------------------- | -------------- | ------- | ----------- | --------- | -------- |
| yi-coder-9b | 4.571 | 4.529 | 4.814 | 4.686 | 4.686 | 4.657 | 70 | 0 |
| codegemma-7b | 4.471 | 4.457 | 4.786 | 4.543 | 4.643 | 4.671 | 70 | 0 |
| mistral-7b | 4.271 | 4.429 | 4.600 | 4.514 | 4.600 | 4.586 | 70 | 0 |
| qwen3-8b | 3.429 | 3.886 | 4.057 | 4.086 | 4.243 | 4.171 | 70 | 0 |
| qwen2.5-coder-7b | 3.714 | 4.000 | 4.343 | 4.214 | 4.343 | 4.286 | 70 | 0 |
| codellama-7b | 4.357 | 4.343 | 4.529 | 4.371 | 4.400 | 4.386 | 70 | 0 |
| deepseek-coder-6.7b | 4.414 | 4.429 | 4.686 | 4.586 | 4.514 | 4.486 | 70 | 0 |
| llama3.1-8b | 3.841 | 3.971 | 4.464 | 4.159 | 4.304 | 4.261 | 70 | 6 |

---

## 5b. Verdict Confusion (expected → predicted)

Counts per expected class: `sup` supported, `part` partially_supported, `not` not_supported_by_candidate, `insuf` insufficient_evidence (abstain / model failure).

| Model | sup→sup | sup→part | sup→not | sup→insuf | part→sup | part→part | part→not | part→insuf | not→sup | not→part | not→not | not→insuf | Failures | Per-class F1 (sup/part/not) |
| ----- | ------- | -------- | ------- | --------- | -------- | --------- | -------- | ---------- | ------- | -------- | ------- | --------- | -------- | --------------------------- |
| yi-coder-9b | 43 | 3 | 1 | 0 | 32 | 5 | 2 | 4 | 56 | 15 | 8 | 27 | 0 | 0.483 / 0.152 / 0.137 |
| codegemma-7b | 41 | 4 | 1 | 1 | 22 | 10 | 10 | 1 | 62 | 14 | 19 | 11 | 0 | 0.477 / 0.282 / 0.279 |
| mistral-7b | 38 | 4 | 4 | 1 | 19 | 11 | 12 | 1 | 24 | 23 | 57 | 2 | 0 | 0.594 / 0.272 / 0.637 |
| qwen3-8b | 30 | 7 | 5 | 5 | 5 | 10 | 22 | 6 | 5 | 10 | 50 | 41 | 1 | 0.690 / 0.286 / 0.546 |
| qwen2.5-coder-7b | 24 | 4 | 18 | 1 | 7 | 7 | 29 | 0 | 7 | 6 | 92 | 1 | 0 | 0.565 / 0.233 / 0.751 |
| codellama-7b | 34 | 7 | 0 | 6 | 22 | 9 | 4 | 8 | 61 | 25 | 9 | 11 | 0 | 0.415 / 0.214 / 0.151 |
| deepseek-coder-6.7b | 40 | 6 | 0 | 1 | 29 | 13 | 0 | 1 | 82 | 21 | 1 | 2 | 0 | 0.404 / 0.313 / 0.019 |
| llama3.1-8b | 33 | 11 | 3 | 0 | 19 | 15 | 8 | 1 | 18 | 23 | 45 | 20 | 2 | 0.564 / 0.326 / 0.556 |

---

## 7. Methodology

- **Cases:** built once from the draft gold (`build_cases.py`); search and mapping are bypassed so only the verifier model varies. The requirement text is the gold (verbatim SRS) text.
- **Verifier code:** the unmodified `traceability.verification.Verifier` (prompt verify-v2.3, clause splitting, quote-anchored citation validation, aggregation) and `OllamaClient` (temperature 0, seed 42, num_ctx 8192). Only database reads/writes are replaced.
- **Items sampled for LLM judging:** 10 cases (half gold, half negative), seed 42; the same cases for every model and pair. The judge sees the requirement, the code shown to the verifier (truncated at 6000 chars) and the report.
- **Judging:** Leave-one-out. Point-wise: judges are the other N−1 models. Pairwise: the other N−2.
- **Pairwise position bias control:** each pair run twice with A/B swapped; a win needs agreement across both orderings, otherwise TIE.
- **Point-wise scoring:** 6 dimensions (verdict, evidence, consistency, reasoning, clarity, conciseness), 1–5, all scored in one call per item (DocAgent used one call per dimension).
- **Judges are the same 7B–9B models being compared;** the objective verdict metrics are the more reliable signal for choosing the verifier.
