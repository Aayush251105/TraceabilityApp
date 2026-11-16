# SRS Agent Candidate Judge — Model Benchmark Report
_Generated: 2026-11-16 12:44_

> **PROVISIONAL.** Ground truth comes from the DRAFT gold workbooks (AI-drafted 2026-11-15, not yet reviewed by the two annotators). Re-score with `--report-only` after the golds are frozen.

## Models Evaluated

- **qwen3-4b** (`qwen3:4b`) — judge time: 13m 24s
- **qwen2.5-coder-1.5b** (`qwen2.5-coder:1.5b`) — judge time: 0m 34s
- **qwen2.5-coder-3b** (`qwen2.5-coder:3b`) — judge time: 0m 45s
- **qwen2.5-3b** (`qwen2.5:3b`) — judge time: 0m 51s

> **Task:** 110 candidates over 4 SRS documents reach the judge (detection confidence medium/low). By the draft gold, 30 are requirements, 63 are not, 17 are ambiguous (not scored). High-confidence candidates bypass the judge and are the same for every model.

---

## 1. Ranking (F1 on judged candidates)

Primary metric. A candidate counts as *kept* only when the judge says `keep` with medium/high confidence — exactly what the SRS Agent sends on to extraction. `uncertain` and low-confidence keeps go to human review only.

| Rank | Model | F1 | Precision | Recall | F2 | Accuracy | Judge Time |
| ---- | ----- | --- | --------- | ------ | --- | -------- | ---------- |
| 1 | qwen3-4b | **0.571** | 0.426 | 0.867 | 0.718 | 0.581 | 13m 24s |
| 2 | qwen2.5-coder-1.5b | **0.540** | 0.515 | 0.567 | 0.556 | 0.688 | 0m 34s |
| 3 | qwen2.5-coder-3b | **0.360** | 0.450 | 0.300 | 0.321 | 0.656 | 0m 45s |
| 4 | qwen2.5-3b | **0.204** | 0.263 | 0.167 | 0.180 | 0.581 | 0m 51s |

---

## 2. Judge Time

Wall-clock time for the judge over all judged candidates of the 4 SRS documents.

| Model | Ollama Tag | Judge Time | Virtual-clinic | Travel-Agency-Automation-System | Books-Recommender-System | ProClinic |
| ----- | ---------- | ---------- | -------------- | ------------------------------- | ------------------------ | --------- |
| qwen3-4b | `qwen3:4b` | 13m 24s | 5m 17s | 3m 38s | 3m 24s | 1m 04s |
| qwen2.5-coder-1.5b | `qwen2.5-coder:1.5b` | 0m 34s | 0m 16s | 0m 06s | 0m 09s | 0m 03s |
| qwen2.5-coder-3b | `qwen2.5-coder:3b` | 0m 45s | 0m 18s | 0m 09s | 0m 14s | 0m 04s |
| qwen2.5-3b | `qwen2.5:3b` | 0m 51s | 0m 22s | 0m 09s | 0m 15s | 0m 04s |

---

## 3. Confusion Counts

TP = requirement kept, FN = requirement not kept (discarded or uncertain), FP = non-requirement kept, TN = non-requirement not kept. *Unc.* = how many of the not-kept items were `uncertain` (sent to review rather than dropped).

| Model | TP | FN | FP | TN | Unc. (req) | Unc. (non-req) | Uncertain Rate | Failed Batches |
| ----- | --- | --- | --- | --- | ---------- | -------------- | -------------- | -------------- |
| qwen3-4b | 26 | 4 | 35 | 28 | 1 | 3 | 4.3% | 0 |
| qwen2.5-coder-1.5b | 17 | 13 | 16 | 47 | 9 | 34 | 46.2% | 0 |
| qwen2.5-coder-3b | 9 | 21 | 11 | 52 | 0 | 0 | 0.0% | 0 |
| qwen2.5-3b | 5 | 25 | 14 | 49 | 2 | 2 | 4.3% | 0 |

---

## 4. Full Metrics Summary

*Gold recall (end to end)* = gold requirements whose text is covered (≥80% of content words) by the candidates retained for extraction (fast-path + judge-kept). Its ceiling is set by the detector, which is the same for all models.

| Model | Judge Time | Precision | Recall | F1 | F2 | Accuracy | Uncertain | Gold Recall (e2e) |
| ----- | ---------- | --------- | ------ | --- | --- | -------- | --------- | ----------------- |
| qwen3-4b | 13m 24s | 0.426 | 0.867 | **0.571** | 0.718 | 0.581 | 4.3% | 126/144 (87.5%) |
| qwen2.5-coder-1.5b | 0m 34s | 0.515 | 0.567 | **0.540** | 0.556 | 0.688 | 46.2% | 121/144 (84.0%) |
| qwen2.5-coder-3b | 0m 45s | 0.450 | 0.300 | **0.360** | 0.321 | 0.656 | 0.0% | 116/144 (80.6%) |
| qwen2.5-3b | 0m 51s | 0.263 | 0.167 | **0.204** | 0.180 | 0.581 | 4.3% | 113/144 (78.5%) |

---

## 5. Per-Document Results

Each cell: `F1 · gold recall (e2e)`.

| Model | Virtual-clinic | Travel-Agency-Automation-System | Books-Recommender-System | ProClinic |
| ----- | -------------- | ------------------------------- | ------------------------ | --------- |
| qwen3-4b | 0.000 · 50/63 | 0.800 · 16/19 | 0.600 · 38/40 | 0.800 · 22/22 |
| qwen2.5-coder-1.5b | 0.000 · 50/63 | 0.600 · 13/19 | 0.593 · 36/40 | 0.667 · 22/22 |
| qwen2.5-coder-3b | 0.000 · 50/63 | 0.632 · 13/19 | 0.000 · 31/40 | 0.750 · 22/22 |
| qwen2.5-3b | 0.000 · 50/63 | 0.471 · 11/19 | 0.111 · 32/40 | 0.000 · 20/22 |

---

## 6. Methodology

- **Input:** each SRS is parsed and segmented once (`prepare_candidates.py`, no LLM); all models judge the identical candidate list.
- **Judge code:** the unmodified `CandidateJudge` (batches of ≤20 candidates / 7000 chars, structured JSON output, temperature 0, seed 42). No fallback model, so failures count against the judge.
- **Labels:** text matching against the draft gold requirement texts (requirement ≥ 0.80 of the candidate's content words inside one gold requirement; not a requirement < 0.50; otherwise ambiguous and not scored). Matching is by text, not ID, because gold IDs were renamed for some pairs.
- **No LLM-as-judge here:** the judge is a classifier with a ground truth, so it is scored objectively (the leave-one-out LLM judging is used for the extractor and verifier, whose outputs are free text).
- Single run per model (deterministic decoding).
