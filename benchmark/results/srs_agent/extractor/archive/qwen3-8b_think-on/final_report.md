# SRS Agent Extractor — Model Benchmark Report
_Generated: 2026-11-18 02:46_

> **PROVISIONAL.** Ground truth comes from the DRAFT gold workbooks (AI-drafted 2026-11-15, not yet reviewed by the two annotators). Raw outputs are saved, so the objective metrics can be re-scored without re-running any model once the golds are frozen.

## Models Evaluated

- **qwen3-8b** (`qwen3:8b`) — extraction time: 11h 44m 21s
- **mistral-7b** (`mistral:7b`) — extraction time: 16m 18s
- **codegemma-7b** (`codegemma:7b`) — extraction time: 15m 47s
- **qwen2.5-coder-7b** (`qwen2.5-coder:7b`) — extraction time: 14m 31s
- **deepseek-coder-6.7b** (`deepseek-coder:6.7b`) — extraction time: 1h 09m 12s
- **codellama-7b** (`codellama:7b`) — extraction time: 1h 35m 01s
- **yi-coder-9b** (`yi-coder:9b`) — extraction time: 1h 48m 14s
- **llama3.1-8b** (`llama3.1:8b`) — extraction time: 12m 24s

> **Judge protocol:** Leave-one-out. When model X is evaluated, judges are all other models.

---

## 1. Pairwise Win Rate Ranking

Primary metric. Each matchup is judged by the 6 remaining models.
Position bias is controlled by running each pair in both orderings;
a win is only counted when the judge agrees across both orderings.

| Rank | Model | Win Rate | W | L | T | Total Decisions |
| ---- | ----- | -------- | --- | --- | --- | --------------- |
| 1 | qwen3-8b | **22.1%** | 93 | 9 | 318 | 420 |
| 2 | mistral-7b | **12.9%** | 54 | 24 | 342 | 420 |
| 3 | codegemma-7b | **9.5%** | 40 | 36 | 344 | 420 |
| 4 | qwen2.5-coder-7b | **9.0%** | 38 | 24 | 358 | 420 |
| 5 | deepseek-coder-6.7b | **9.0%** | 38 | 50 | 332 | 420 |
| 6 | codellama-7b | **7.6%** | 32 | 68 | 320 | 420 |
| 7 | yi-coder-9b | **6.0%** | 25 | 63 | 332 | 420 |
| 8 | llama3.1-8b | **5.2%** | 22 | 68 | 330 | 420 |

---

## 2. Extraction Time

Wall-clock time for `SRSAgent.extract` over the same 160 retained candidates (4 SRS documents), including retries.

| Model | Ollama Tag | Extraction Time |
| ----- | ---------- | --------------- |
| qwen3-8b | `qwen3:8b` | 11h 44m 21s |
| mistral-7b | `mistral:7b` | 16m 18s |
| codegemma-7b | `codegemma:7b` | 15m 47s |
| qwen2.5-coder-7b | `qwen2.5-coder:7b` | 14m 31s |
| deepseek-coder-6.7b | `deepseek-coder:6.7b` | 1h 09m 12s |
| codellama-7b | `codellama:7b` | 1h 35m 01s |
| yi-coder-9b | `yi-coder:9b` | 1h 48m 14s |
| llama3.1-8b | `llama3.1:8b` | 12m 24s |

---

## 3. Pairwise Head-to-Head Results

Each cell shows `W / L / T` (wins, losses, ties) for the **row model** against the **column model**.

| Model | qwen3-8b | mistral-7b | codegemma-7b | qwen2.5-coder-7b | deepseek-coder-6.7b | codellama-7b | yi-coder-9b | llama3.1-8b |
| ----- | -------- | ---------- | ------------ | ---------------- | ------------------- | ------------ | ----------- | ----------- |
| **qwen3-8b** | — | 6/4/50 | 15/2/43 | 8/0/52 | 11/1/48 | 17/1/42 | 20/0/40 | 16/1/43 |
| **mistral-7b** | 4/6/50 | — | 6/3/51 | 4/3/53 | 8/3/49 | 11/2/47 | 13/6/41 | 8/1/51 |
| **codegemma-7b** | 2/15/43 | 3/6/51 | — | 3/6/51 | 6/5/49 | 9/1/50 | 7/2/51 | 10/1/49 |
| **qwen2.5-coder-7b** | 0/8/52 | 3/4/53 | 6/3/51 | — | 8/4/48 | 7/2/51 | 6/1/53 | 8/2/50 |
| **deepseek-coder-6.7b** | 1/11/48 | 3/8/49 | 5/6/49 | 4/8/48 | — | 10/9/41 | 6/2/52 | 9/6/45 |
| **codellama-7b** | 1/17/42 | 2/11/47 | 1/9/50 | 2/7/51 | 9/10/41 | — | 7/7/46 | 10/7/43 |
| **yi-coder-9b** | 0/20/40 | 6/13/41 | 2/7/51 | 1/6/53 | 2/6/52 | 7/7/46 | — | 7/4/49 |
| **llama3.1-8b** | 1/16/43 | 1/8/51 | 1/10/49 | 2/8/50 | 6/9/45 | 7/10/43 | 4/7/49 | — |

---

## 4. Full Metrics Summary

Objective metrics need no LLM. LLM-judged scores are 1–5, averaged across leave-one-out judges.

| Model | Extraction Time | Success | Field Fill | Grounding | Values Kept | List Items | Retr. MRR | Faithfulness | Completeness | Field | Normalized | Code-Search | Conciseness | LLM Avg | Win Rate |
| ----- | --------------- | ------- | ---------- | --------- | ----------- | ---------- | --------- | ------------ | ------------ | ----- | ---------- | ----------- | ----------- | ------- | -------- |
| qwen3-8b | 11h 44m 21s | 95.6% | 0.984 | 0.835 | 0.839 | 0.267 | 0.466 | 4.483 | 4.517 | 4.750 | 4.800 | 4.750 | 4.583 | 4.647 | **22.1%** |
| mistral-7b | 16m 18s | 100.0% | 0.958 | 0.780 | 0.604 | 0.467 | 0.496 | 4.365 | 4.492 | 4.667 | 4.667 | 4.714 | 4.532 | 4.573 | **12.9%** |
| codegemma-7b | 15m 47s | 100.0% | 0.986 | 0.877 | 0.503 | 0.119 | 0.525 | 4.475 | 4.475 | 4.683 | 4.803 | 4.607 | 4.492 | 4.589 | **9.5%** |
| qwen2.5-coder-7b | 14m 31s | 100.0% | 0.947 | 0.879 | 0.725 | 0.400 | 0.518 | 4.483 | 4.400 | 4.678 | 4.750 | 4.717 | 4.567 | 4.599 | **9.0%** |
| deepseek-coder-6.7b | 1h 09m 12s | 99.4% | 0.992 | 0.935 | 0.810 | 0.033 | 0.486 | 4.435 | 4.387 | 4.629 | 4.710 | 4.597 | 4.516 | 4.546 | **9.0%** |
| codellama-7b | 1h 35m 01s | 99.4% | 0.972 | 0.949 | 0.773 | 0.167 | 0.507 | 4.529 | 4.557 | 4.729 | 4.729 | 4.686 | 4.551 | 4.630 | **7.6%** |
| yi-coder-9b | 1h 48m 14s | 98.8% | 0.954 | 0.944 | 0.682 | 0.438 | 0.497 | 4.613 | 4.419 | 4.645 | 4.677 | 4.613 | 4.516 | 4.581 | **6.0%** |
| llama3.1-8b | 12m 24s | 100.0% | 0.988 | 0.944 | 0.542 | 0.161 | 0.484 | 4.650 | 4.600 | 4.833 | 4.867 | 4.783 | 4.717 | 4.742 | **5.2%** |

---

## 5. Objective Extraction Metrics (no LLM)

*Success* = schema-valid extractions / candidates. *Field Fill* = share of core fields filled (title, normalized_text, actor, actions, entities, domain_terms, retrieval_text). *Grounding* = share of content words in the descriptive fields that occur in the requirement text (invention proxy). *Values Kept* = numbers in the text that survive into the fields. *List Items* = `- ` list items covered by sub_requirements. *Retr. MRR* = mean of BM25 and dense MRR (section 5b).

| Model | Success | Field Fill | Grounding | Values Kept | List Items | Retr. MRR |
| ----- | ------- | ---------- | --------- | ----------- | ---------- | --------- |
| qwen3-8b | 95.6% | 0.984 | 0.835 | 0.839 | 0.267 | 0.466 |
| mistral-7b | 100.0% | 0.958 | 0.780 | 0.604 | 0.467 | 0.496 |
| codegemma-7b | 100.0% | 0.986 | 0.877 | 0.503 | 0.119 | 0.525 |
| qwen2.5-coder-7b | 100.0% | 0.947 | 0.879 | 0.725 | 0.400 | 0.518 |
| deepseek-coder-6.7b | 99.4% | 0.992 | 0.935 | 0.810 | 0.033 | 0.486 |
| codellama-7b | 99.4% | 0.972 | 0.949 | 0.773 | 0.167 | 0.507 |
| yi-coder-9b | 98.8% | 0.954 | 0.944 | 0.682 | 0.438 | 0.497 |
| llama3.1-8b | 100.0% | 0.988 | 0.944 | 0.542 | 0.161 | 0.484 |

---

## 6. Point-wise LLM Judge Scores

Each score is 1–5, averaged across all leave-one-out judges and sampled items.

| Model | Faithfulness (no invention) | Completeness | Field Structure | Normalized Text | Code-Search Usefulness | Conciseness | Judgments | Unparsed |
| ----- | --------------------------- | ------------ | --------------- | --------------- | ---------------------- | ----------- | --------- | -------- |
| qwen3-8b | 4.483 | 4.517 | 4.750 | 4.800 | 4.750 | 4.583 | 70 | 60 |
| mistral-7b | 4.365 | 4.492 | 4.667 | 4.667 | 4.714 | 4.532 | 70 | 43 |
| codegemma-7b | 4.475 | 4.475 | 4.683 | 4.803 | 4.607 | 4.492 | 70 | 55 |
| qwen2.5-coder-7b | 4.483 | 4.400 | 4.678 | 4.750 | 4.717 | 4.567 | 70 | 61 |
| deepseek-coder-6.7b | 4.435 | 4.387 | 4.629 | 4.710 | 4.597 | 4.516 | 70 | 48 |
| codellama-7b | 4.529 | 4.557 | 4.729 | 4.729 | 4.686 | 4.551 | 70 | 1 |
| yi-coder-9b | 4.613 | 4.419 | 4.645 | 4.677 | 4.613 | 4.516 | 70 | 48 |
| llama3.1-8b | 4.650 | 4.600 | 4.833 | 4.867 | 4.783 | 4.717 | 70 | 60 |

---

## 5b. Retrieval Proxy Detail

MRR of the gold **primary** components when the model's fields are used as the search query (the pipeline's own `texts.requirement_text` builder: title, retrieval_text, normalized_text, actions, entities, domain_terms, synonyms, sub_requirements). 91 retained requirements match a gold requirement with primary links; a failed extraction scores 0.

| Model | BM25 MRR | Dense (MiniLM) MRR | Mean |
| ----- | -------- | ------------------ | ---- |
| qwen3-8b | 0.511 | 0.421 | 0.466 |
| mistral-7b | 0.530 | 0.461 | 0.496 |
| codegemma-7b | 0.539 | 0.511 | 0.525 |
| qwen2.5-coder-7b | 0.530 | 0.507 | 0.518 |
| deepseek-coder-6.7b | 0.519 | 0.453 | 0.486 |
| codellama-7b | 0.556 | 0.457 | 0.507 |
| yi-coder-9b | 0.520 | 0.474 | 0.497 |
| llama3.1-8b | 0.529 | 0.438 | 0.484 |

---

## 7. Methodology

- **Input:** the candidates retained by the default judge (`qwen2.5:3b`), identical for every model. Unmodified `SRSAgent.extract` (same prompt, 3 attempts, temperature 0, seed 42).
- **Items sampled for LLM judging:** 10 (from 149 extracted by all models); seed 42. The same items are used for every model and every pair.
- **Judging:** Leave-one-out. Point-wise: judges are the other N−1 models. Pairwise: the other N−2.
- **Pairwise position bias control:** each pair run twice with A/B swapped; a win needs agreement across both orderings, otherwise TIE.
- **Point-wise scoring:** 6 dimensions (faithfulness, completeness, structure, normalized_text, retrieval, conciseness), 1–5. Unlike DocAgent (one call per dimension), all dimensions are scored in one call per item.
- **Judge decoding:** temperature 0.1, max 1024 tokens; qwen3 judges run with thinking disabled.
- **Objective metrics:** pure text matching against the requirement text and the draft gold links; no LLM involved.
