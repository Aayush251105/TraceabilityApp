# Verifier experiment: model × prompt on the V1 runs

Only the verify stage was re-run; requirements, docstrings, candidates and mapping are the V1 ones, scored against the frozen V1 golds. 95% bootstrap CIs over requirements in brackets. `v1` = the verdicts stored by V1 (qwen2.5-coder:7b, strict prompt).

**Selection rule (fixed before running):** best pooled macro-F1 among configurations whose pooled false-support rate is ≤ 10%.

## 1. Pooled over the 4 pairs

| Config | Model | Prompt | Think | Exact acc. | Macro-F1 | Weighted κ | False support ↓ | FS not-impl ↓ | Impl. recall | Impl. recall (code shown) | Partial found (code shown) | Citation valid. | Minutes | McNemar vs v1 (b/c, p) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **v1** | `qwen2.5-coder:7b` | strict | default | 0.261 [0.171, 0.351] | 0.271 [0.185, 0.352] | 0.152 | 3.1% [0.0%, 8.0%] | 6.2% | 29.8% [17.0%, 43.4%] | 44.8% | 15.0% | 0.783 | — | — |
| **7b-strict** | `qwen2.5-coder:7b` | strict | default | 0.279 [0.189, 0.369] | 0.289 [0.202, 0.370] | 0.180 | 3.1% [0.0%, 8.0%] | 6.2% | 34.0% [20.0%, 48.0%] | 44.8% | 15.0% | 0.862 | 19.0 | 0/2, p=0.500 |
| **7b-behavioral** | `qwen2.5-coder:7b` | behavioral | default | 0.387 [0.297, 0.477] | 0.370 [0.288, 0.452] | 0.270 | 17.2% [8.6%, 27.5%] | 25.0% | 59.6% [45.5%, 73.6%] | 72.4% | 20.0% | 0.965 | 37.4 | 4/18, p=0.004 |
| **14b-strict** | `qwen2.5-coder:14b` | strict | default | 0.360 [0.261, 0.450] | 0.380 [0.292, 0.467] | 0.295 | 9.4% [3.1%, 16.9%] | 18.8% | 55.3% [41.0%, 69.6%] | 69.0% | 20.0% | 1.000 | 65.4 | 6/17, p=0.035 |
| **14b-behavioral** | `qwen2.5-coder:14b` | behavioral | default | 0.432 [0.333, 0.532] | 0.430 [0.339, 0.515] | 0.311 | 15.6% [7.4%, 24.6%] | 31.2% | 61.7% [47.9%, 75.5%] | 72.4% | 40.0% | 0.967 | 131.2 | 6/25, p=0.001 |
| **qwen3-14b-strict** | `qwen3:14b` | strict | off | 0.243 [0.162, 0.324] | 0.311 [0.216, 0.399] | 0.176 | 0.0% [0.0%, 0.0%] | 0.0% | 27.7% [15.7%, 40.8%] | 44.8% | 35.0% | 0.993 | 51.2 | 10/8, p=0.815 |
| **qwen3-14b-behavioral** | `qwen3:14b` | behavioral | off | 0.306 [0.216, 0.396] | 0.349 [0.256, 0.437] | 0.234 | 9.4% [2.9%, 16.7%] | 6.2% | 42.6% [28.3%, 56.5%] | 55.2% | 35.0% | 1.000 | 25.7 | 9/14, p=0.405 |

*b* = requirements V1 got right and this configuration got wrong; *c* = the reverse. *Code shown* = the gold primary component was among the mapped components the verifier saw.

**By the selection rule: `14b-strict`** (macro-F1 0.380 vs 0.271 for v1). Check its McNemar p-value and CIs before calling it better.

Determinism check: `7b-strict` (the V1 setting, re-run) gives the same verdict as V1 on 97.3% of the requirements.

## 2. Per pair

| Config | Pair | Judged | Exact acc. | Macro-F1 | False support ↓ | Impl. recall |
|---|---|---|---|---|---|---|
| v1 | Travel-Agency-Automation-System | 13 | 0.308 | 0.248 | 0.0% | 0.0% |
| v1 | Books-Recommender-System | 28 | 0.429 | 0.476 | 0.0% | 50.0% |
| v1 | Virtual-clinic | 52 | 0.154 | 0.139 | 4.8% | 10.0% |
| v1 | ProClinic | 18 | 0.278 | 0.206 | 0.0% | 16.7% |
| 7b-strict | Books-Recommender-System | 28 | 0.429 | 0.476 | 0.0% | 50.0% |
| 7b-strict | ProClinic | 18 | 0.389 | 0.292 | 0.0% | 33.3% |
| 7b-strict | Travel-Agency-Automation-System | 13 | 0.308 | 0.248 | 0.0% | 0.0% |
| 7b-strict | Virtual-clinic | 52 | 0.154 | 0.141 | 4.8% | 10.0% |
| 7b-behavioral | Books-Recommender-System | 28 | 0.571 | 0.520 | 16.7% | 68.2% |
| 7b-behavioral | ProClinic | 18 | 0.500 | 0.333 | 33.3% | 58.3% |
| 7b-behavioral | Travel-Agency-Automation-System | 13 | 0.462 | 0.429 | 20.0% | 33.3% |
| 7b-behavioral | Virtual-clinic | 52 | 0.231 | 0.275 | 14.3% | 50.0% |
| 14b-strict | Books-Recommender-System | 28 | 0.607 | 0.521 | 16.7% | 72.7% |
| 14b-strict | ProClinic | 18 | 0.389 | 0.306 | 16.7% | 41.7% |
| 14b-strict | Travel-Agency-Automation-System | 13 | 0.538 | 0.501 | 20.0% | 33.3% |
| 14b-strict | Virtual-clinic | 52 | 0.173 | 0.270 | 4.8% | 40.0% |
| 14b-behavioral | Books-Recommender-System | 28 | 0.643 | 0.516 | 50.0% | 77.3% |
| 14b-behavioral | ProClinic | 18 | 0.500 | 0.463 | 33.3% | 58.3% |
| 14b-behavioral | Travel-Agency-Automation-System | 13 | 0.538 | 0.400 | 10.0% | 33.3% |
| 14b-behavioral | Virtual-clinic | 52 | 0.269 | 0.329 | 9.5% | 40.0% |
| qwen3-14b-strict | Books-Recommender-System | 28 | 0.393 | 0.438 | 0.0% | 45.5% |
| qwen3-14b-strict | ProClinic | 18 | 0.111 | 0.147 | 0.0% | 8.3% |
| qwen3-14b-strict | Travel-Agency-Automation-System | 13 | 0.615 | 0.563 | 0.0% | 33.3% |
| qwen3-14b-strict | Virtual-clinic | 52 | 0.115 | 0.171 | 0.0% | 10.0% |
| qwen3-14b-behavioral | Books-Recommender-System | 28 | 0.429 | 0.333 | 33.3% | 54.5% |
| qwen3-14b-behavioral | ProClinic | 18 | 0.222 | 0.148 | 33.3% | 33.3% |
| qwen3-14b-behavioral | Travel-Agency-Automation-System | 13 | 0.692 | 0.647 | 10.0% | 33.3% |
| qwen3-14b-behavioral | Virtual-clinic | 52 | 0.173 | 0.273 | 2.4% | 30.0% |

## 3. Verdict confusion, pooled (gold → predicted)

**v1**: implemented → insufficient_evidence 1, not_supported_by_candidate 29, partially_supported 3, supported 14; not_implemented → not_supported_by_candidate 11, partially_supported 1, unverified 4; partial → not_supported_by_candidate 41, partially_supported 4, supported 2, unverified 1

**7b-strict**: implemented → insufficient_evidence 1, not_supported_by_candidate 26, partially_supported 4, supported 16; not_implemented → not_supported_by_candidate 11, partially_supported 1, unverified 4; partial → not_supported_by_candidate 41, partially_supported 4, supported 2, unverified 1

**7b-behavioral**: implemented → not_supported_by_candidate 15, partially_supported 4, supported 28; not_implemented → not_supported_by_candidate 8, partially_supported 2, supported 2, unverified 4; partial → not_supported_by_candidate 31, partially_supported 7, supported 9, unverified 1

**14b-strict**: implemented → insufficient_evidence 6, not_supported_by_candidate 8, partially_supported 7, supported 26; not_implemented → insufficient_evidence 3, not_supported_by_candidate 6, partially_supported 2, supported 1, unverified 4; partial → insufficient_evidence 13, not_supported_by_candidate 21, partially_supported 8, supported 5, unverified 1

**14b-behavioral**: implemented → insufficient_evidence 4, not_supported_by_candidate 8, partially_supported 6, supported 29; not_implemented → insufficient_evidence 1, not_supported_by_candidate 6, partially_supported 3, supported 2, unverified 4; partial → insufficient_evidence 7, not_supported_by_candidate 19, partially_supported 13, supported 8, unverified 1

**qwen3-14b-strict**: implemented → insufficient_evidence 21, not_supported_by_candidate 11, partially_supported 2, supported 13; not_implemented → insufficient_evidence 8, not_supported_by_candidate 4, unverified 4; partial → insufficient_evidence 20, not_supported_by_candidate 17, partially_supported 10, unverified 1

**qwen3-14b-behavioral**: implemented → insufficient_evidence 13, not_supported_by_candidate 9, partially_supported 5, supported 20; not_implemented → insufficient_evidence 6, not_supported_by_candidate 5, supported 1, unverified 4; partial → insufficient_evidence 15, not_supported_by_candidate 18, partially_supported 9, supported 5, unverified 1

## 4. Caveats

- One run per configuration at temperature 0 (deterministic up to GPU numerics); CIs cover requirement sampling only.
- The model also splits compound claims (`--claims clauses`), so a model change affects claims and verdicts.
- Requirements that the SRS Agent did not extract stay `unverified` (wrong) in every configuration.
- These 4 pairs are the test set: report the selected configuration once; do not iterate prompts on them.
