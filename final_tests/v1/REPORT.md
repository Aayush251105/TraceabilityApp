# Tracelight — Final Testing V1 Report

> **V1 - human-annotated gold.** One run per pair, default models, auto-approved review (no human). 95% bootstrap CIs over requirements in brackets.

## Setup

| Pair | Run | Components | Gold reqs (scored set / excluded) | Commit |
|---|---|---|---|---|
| Travel-Agency-Automation-System | 2 | 44 | 14 / 5 | `2cc23a2f3b` |
| Books-Recommender-System | 3 | 53 | 33 / 7 | `69ed627f0f` |
| Virtual-clinic | 7 | 233 | 57 / 6 | `b8241e502d` |
| ProClinic | 6 | 558 | 21 / 1 | `ee23cb7e8b` |

Models: srs `qwen3:8b`, judge `qwen3:4b`, docagent `yi-coder:9b`, verifier `qwen2.5-coder:7b` (extractor thinking off). Requirement matching: ID, else difflib ratio ≥ 0.6 on normalised text.

## 1. SRS extraction

| Pair | Extracted | Precision | Recall | F1 | Recall incl. excluded |
|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 27 | 0.667 | 0.929 [0.786, 1.000] | 0.776 | 0.947 |
| Books-Recommender-System | 61 | 0.639 | 1.000 [1.000, 1.000] | 0.780 | 0.975 |
| Virtual-clinic | 91 | 0.582 | 0.895 [0.807, 0.965] | 0.706 | 0.841 |
| ProClinic | 31 | 0.710 | 1.000 [1.000, 1.000] | 0.830 | 1.000 |
| **micro (pooled)** | 210 | 0.629 | 0.944 [0.904, 0.976] | 0.755 | — |
| **macro (mean of pairs)** | 52.500 | 0.650 | 0.956 | 0.773 | 0.941 |

## 2. Search (stored candidates used by mapping)

| Pair | MAP | MRR | R@1 | R@5 | R@10 | nDCG@10 | SR@\|G\| | MRR all_hybrid (evaluate) |
|---|---|---|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 0.607 [0.424, 0.770] | 0.705 [0.500, 0.909] | 0.394 | 0.788 | 0.864 | 0.667 | 0.273 | 0.711 |
| Books-Recommender-System | 0.718 [0.599, 0.843] | 0.735 [0.623, 0.852] | 0.537 | 0.894 | 0.920 | 0.722 | 0.556 | 0.709 |
| Virtual-clinic | 0.289 [0.183, 0.405] | 0.369 [0.239, 0.504] | 0.198 | 0.365 | 0.577 | 0.353 | 0.135 | 0.346 |
| ProClinic | 0.261 [0.096, 0.443] | 0.348 [0.156, 0.546] | 0.147 | 0.291 | 0.469 | 0.326 | 0.133 | 0.367 |
| **micro (pooled)** | 0.452 [0.375, 0.535] | 0.516 [0.434, 0.605] | 0.315 | 0.563 | 0.697 | — | 0.278 | — |
| **macro (mean of pairs)** | 0.469 | 0.539 | 0.319 | 0.584 | 0.707 | 0.517 | 0.274 | 0.533 |

## 3. Mapping (micro over implemented + partial requirements)

| Pair | Direct P | Direct R | Direct F1 | Direct F2 | All P | All R | All F1 | All F2 |
|---|---|---|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 0.625 [0.400, 0.824] | 0.588 [0.400, 0.750] | 0.606 | 0.595 | 0.329 | 0.750 | 0.457 | 0.597 |
| Books-Recommender-System | 0.676 [0.556, 0.800] | 0.610 [0.394, 0.893] | 0.641 | 0.622 | 0.201 | 0.603 | 0.302 | 0.431 |
| Virtual-clinic | 0.238 [0.114, 0.372] | 0.154 [0.071, 0.250] | 0.187 | 0.166 | 0.089 | 0.153 | 0.113 | 0.134 |
| ProClinic | 0.250 [0.059, 0.467] | 0.095 [0.022, 0.190] | 0.138 | 0.109 | 0.105 | 0.065 | 0.080 | 0.070 |
| **micro (pooled)** | 0.441 [0.357, 0.533] | 0.297 [0.225, 0.386] | 0.355 | 0.318 | 0.176 | 0.321 | 0.228 | 0.276 |
| **macro (mean of pairs)** | 0.447 | 0.362 | 0.393 | 0.373 | 0.181 | 0.393 | 0.238 | 0.308 |

## 4. Verification

| Pair | Judged | Exact acc. | Macro-F1 | Weighted κ | False support ↓ | Impl. recall | Citation valid. |
|---|---|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 13 | 0.308 [0.077, 0.538] | 0.248 | 0.077 | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.778 |
| Books-Recommender-System | 28 | 0.429 [0.250, 0.607] | 0.476 | 0.149 | 0.0% [0.0%, 0.0%] | 50.0% [30.0%, 71.4%] | 0.923 |
| Virtual-clinic | 52 | 0.154 [0.058, 0.269] | 0.139 | 0.028 | 4.8% [0.0%, 11.9%] | 10.0% [0.0%, 33.3%] | 0.712 |
| ProClinic | 18 | 0.278 [0.111, 0.500] | 0.206 | 0.096 | 0.0% [0.0%, 0.0%] | 16.7% [0.0%, 40.0%] | 0.720 |
| **micro (pooled)** | 111 | 0.261 [0.171, 0.351] | 0.271 | 0.152 | 3.1% [0.0%, 8.0%] | 29.8% [17.0%, 43.4%] | 0.783 |
| **macro (mean of pairs)** | 27.750 | 0.292 | 0.268 | 0.087 | 1.2% | 19.2% | 0.783 |

*False support* = partial or not-implemented requirements declared `supported`. *Impl. recall* = implemented requirements declared `supported`. κ: linear weights on not (incl. insufficient / unverified) < partial < supported.

## 5. Against the Run 6 library baseline (CLAUDE.md)

Run 6 is the library **dev** set (39 requirements, its own SRS); V1 is 4 unseen test pairs, so this is a sanity comparison, not a like-for-like one.

| Metric | Run 6 (library, dev) | V1 micro (4 test pairs) |
|---|---|---|
| Search MRR (all_hybrid) | 0.936 | 0.533 (mean of pairs) |
| Mapping direct P / R | 0.67 / 0.87 | 0.441 / 0.297 |
| Verifier exact accuracy | 0.833 | 0.261 |
| False support | 0.0 | 3.1% |
| Supported | 27/39 | 17/125 |
| Minutes per pair | 85 | Travel 26.690, Books 33.080, Virtual 274.290, ProClinic 433.870 |

## 6. Verdict confusion (gold status → predicted)

| Pair | Gold status | supported | partially_supported | not_supported_by_candidate | not_found | insufficient_evidence | unverified |
|---|---|---|---|---|---|---|---|
| Travel-Agency-Automation-System | partial | 0 | 3 | 5 | 0 | 0 | 0 |
| Travel-Agency-Automation-System | not_implemented | 0 | 0 | 1 | 0 | 0 | 1 |
| Travel-Agency-Automation-System | implemented | 0 | 0 | 2 | 0 | 1 | 0 |
| Travel-Agency-Automation-System | cross_cutting (not scored) | 0 | 0 | 1 | 0 | 0 | 0 |
| Books-Recommender-System | implemented | 11 | 0 | 11 | 0 | 0 | 0 |
| Books-Recommender-System | partial | 0 | 1 | 5 | 0 | 0 | 0 |
| Books-Recommender-System | cross_cutting (not scored) | 0 | 0 | 5 | 0 | 0 | 0 |
| Virtual-clinic | partial | 2 | 0 | 28 | 0 | 0 | 1 |
| Virtual-clinic | implemented | 1 | 2 | 7 | 0 | 0 | 0 |
| Virtual-clinic | not_implemented | 0 | 1 | 7 | 0 | 0 | 3 |
| Virtual-clinic | cross_cutting (not scored) | 1 | 0 | 2 | 0 | 0 | 2 |
| ProClinic | implemented | 2 | 1 | 9 | 0 | 0 | 0 |
| ProClinic | partial | 0 | 0 | 3 | 0 | 0 | 0 |
| ProClinic | not_implemented | 0 | 0 | 3 | 0 | 0 | 0 |
| ProClinic | cross_cutting (not scored) | 0 | 0 | 3 | 0 | 0 | 0 |

## 7. Error analysis (every wrong verdict)

Label order: *extraction miss* (gold requirement not extracted) → *gold has no links* → *retrieval miss* (no gold primary among the stored candidates) → *mapping miss* (primary retrieved but not mapped) → *verifier error* (gold code was shown, or the requirement has no code).

| Pair | extraction miss | gold has no links | retrieval miss | mapping miss | verifier error | total wrong |
|---|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 1 | 0 | 1 | 1 | 6 | 9 |
| Books-Recommender-System | 0 | 1 | 0 | 2 | 13 | 16 |
| Virtual-clinic | 4 | 3 | 10 | 15 | 12 | 44 |
| ProClinic | 0 | 0 | 5 | 5 | 3 | 13 |
| **all** | 5 | 4 | 16 | 23 | 34 | 82 |

## 8. Worst failures

Ordered: false support on not-implemented requirements, then implemented requirements rejected with the right code shown, then other implemented misses, then partial.

| # | Pair | Requirement | Gold | Predicted | Label | First primary rank | Mapped direct |
|---|---|---|---|---|---|---|---|
| 1 | Virtual-clinic | BR-8 | not_implemented | partially_supported | verifier error | — | — |
| 2 | Travel-Agency-Automation-System | FEAT-4.3 | implemented | not_supported_by_candidate | verifier error | 2 | Booking.Booking |
| 3 | Travel-Agency-Automation-System | REQ-005 | implemented | insufficient_evidence | verifier error | 1 | main.main |
| 4 | Books-Recommender-System | FR-1.2 | implemented | not_supported_by_candidate | verifier error | 2 | src.config.configuration.AppConfiguration.get_model_recommendation_config |
| 5 | Books-Recommender-System | FR-1.4 | implemented | not_supported_by_candidate | verifier error | 2 | src.exception.__init__.CustomException.__init__, src.exception.__init__.error_message_deta |
| 6 | Books-Recommender-System | FR-2.1 | implemented | not_supported_by_candidate | verifier error | 3 | src.components.data_ingestion.DataIngestion._create_sample_dataset |
| 7 | Books-Recommender-System | FR-3.4 | implemented | not_supported_by_candidate | verifier error | 3 | src.components.data_transformation.DataTransformation.initiate_data_transformation, src.co |
| 8 | Books-Recommender-System | FR-5.3 | implemented | not_supported_by_candidate | verifier error | 1 | src.components.model_trainer.ModelTrainer.initiate_model_training |
| 9 | Books-Recommender-System | FR-6.4 | implemented | not_supported_by_candidate | verifier error | 1 | src.pipeline.prediction_pipeline.RecommendationEngine.recommend |
| 10 | Books-Recommender-System | FR-7.1 | implemented | not_supported_by_candidate | verifier error | 1 | app.get_book_names |
| 11 | Books-Recommender-System | FR-7.2 | implemented | not_supported_by_candidate | verifier error | 1 | src.pipeline.prediction_pipeline.RecommendationEngine.recommend |
| 12 | Books-Recommender-System | FR-7.3 | implemented | not_supported_by_candidate | verifier error | 1 | src.pipeline.training_pipeline.TrainingPipeline.run_pipeline |
| 13 | Virtual-clinic | Req-4 | implemented | not_supported_by_candidate | verifier error | 1 | server.views_admin.view_symptom |
| 14 | Virtual-clinic | BR-2 | implemented | partially_supported | verifier error | 1 | server.forms.LoginForm.clean |
| 15 | Virtual-clinic | BR-6 | implemented | not_supported_by_candidate | verifier error | 1 | server.views.register_user |
| 16 | ProClinic | FR-3 | implemented | partially_supported | verifier error | 1 | backend.patients.views.patient_my_visits |
| 17 | ProClinic | US005 | implemented | not_supported_by_candidate | verifier error | 1 | backend.prescriptions.views.pharmacist_prescription_detail |
| 18 | Travel-Agency-Automation-System | REQ-001 | implemented | not_supported_by_candidate | retrieval miss | — | Booking.Booking.token |
| 19 | Books-Recommender-System | FR-3.1 | implemented | not_supported_by_candidate | mapping miss | 2 | src.entity.config_entity.DataValidationConfig |
| 20 | Books-Recommender-System | FR-3.5 | implemented | not_supported_by_candidate | mapping miss | 2 | src.entity.config_entity.DataValidationConfig |
| 21 | Virtual-clinic | Req-4/1 | implemented | not_supported_by_candidate | mapping miss | 8 | testing.test_admin.TestAdminViews.test_add_symptom |
| 22 | Virtual-clinic | Req-5 | implemented | not_supported_by_candidate | retrieval miss | — | server.models.Appointment.get_populated_fields |
| 23 | Virtual-clinic | Req-5/2 | implemented | not_supported_by_candidate | mapping miss | 10 | server.views_appointment.update_view |
| 24 | Virtual-clinic | Req-6 | implemented | not_supported_by_candidate | retrieval miss | — | server.appointment.parse_appointments, server.views_appointment.list_view |
| 25 | Virtual-clinic | Req-15 | implemented | partially_supported | mapping miss | 8 | server.models.Account |

All 82 wrong verdicts are in `results/<pair>/per_requirement.csv` (`error_label`).

## 9. Minutes per stage

| Pair | fetch | docstrings | index_code | extract | prepare_review | index_srs | search | map | verify | results | wall total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 0.000 | 23.340 | 0.040 | 13.680 | 0.090 | 0.340 | 0.010 | 0.000 | 2.940 | 0.000 | 26.690 |
| Books-Recommender-System | 0.000 | 28.550 | 0.030 | 16.950 | 0.120 | 0.210 | 0.010 | 0.000 | 4.240 | 0.000 | 33.080 |
| Virtual-clinic | 0.000 | 221.720 | 0.040 | 34.460 | 0.110 | 0.390 | 0.030 | 0.010 | 17.460 | 0.000 | 274.290 |
| ProClinic | 0.000 | 431.460 | 0.080 | 8.310 | 0.120 | 0.020 | 0.010 | 0.000 | 2.230 | 0.000 | 433.870 |

Lanes A (code) and B (SRS) run in parallel, so stage minutes overlap.

## 10. GPU / CPU usage (sampled every 10 s)

8833 samples, 2026-11-20 11:04:36 → 2026-11-21 11:46:48

| Loaded model | Samples | Processor (ollama ps) | GPU util avg / max | GPU mem max (MiB) | Runner CPU avg / max (%, 100 = 1 core) | Host CPU avg | Other users on GPU |
|---|---|---|---|---|---|---|---|
| qwen3:4b;yi-coder:9b | 47 | 100% GPU;100% GPU, 100% GPU;18%/82% CPU/GPU | 100% / 100% | 11238 | 862 / 1242 | 38% | none |
| qwen3:4b | 21 | 100% GPU | 96% / 98% | 5532 | 386 / 479 | 20% | none |
| yi-coder:9b;qwen3:4b | 48 | 100% GPU;100% GPU, 18%/82% CPU/GPU;100% GPU | 99% / 100% | 10620 | 974 / 1370 | 42% | none |
| yi-coder:9b | 8194 | 100% GPU, 18%/82% CPU/GPU | 19% / 100% | 12918 | 160 / 799 | 8% | none |
| qwen3:8b;yi-coder:9b | 173 | 100% GPU;100% GPU | 100% / 100% | 13715 | 852 / 902 | 38% | none |
| yi-coder:9b;qwen3:8b | 223 | 100% GPU;100% GPU | 95% / 100% | 13717 | 649 / 902 | 30% | none |
| qwen2.5-coder:7b | 65 | 100% GPU | 93% / 100% | 7450 | 423 / 462 | 20% | none |
| (none loaded) | 3 | — | 2% / 7% | 7098 | 0 / 0 | 9% | none |
| qwen3:4b;yi-coder:9b;qwen2.5-coder:7b | 16 | 100% GPU;18%/82% CPU/GPU;100% GPU | 99% / 100% | 14945 | 1128 / 1273 | 49% | none |
| yi-coder:9b;qwen3:4b;qwen2.5-coder:7b | 13 | 18%/82% CPU/GPU;100% GPU;100% GPU | 99% / 100% | 14945 | 1192 / 1310 | 51% | none |
| qwen3:8b | 1 | 100% GPU | 0% / 0% | 8691 | 260 / 260 | 15% | none |
| qwen2.5-coder:7b;qwen3:8b | 29 | 100% GPU;100% GPU | 93% / 100% | 13663 | 427 / 443 | 28% | none |


### Final ProClinic and Virtual-clinic runs (two Ollama servers in parallel)

2584 samples, 2026-11-21 11:48:11 → 2026-11-21 19:01:46

| Loaded model | Samples | Processor (ollama ps) | GPU util avg / max | GPU mem max (MiB) | Runner CPU avg / max (%, 100 = 1 core) | Host CPU avg | Other users on GPU |
|---|---|---|---|---|---|---|---|
| qwen3:4b;yi-coder:9b | 6 | 100% GPU;100% GPU | 100% / 100% | 10852 | 730 / 890 | 38% | none |
| yi-coder:9b | 2493 | 100% GPU | 96% / 100% | 14199 | 702 / 912 | 30% | none |
| qwen3:8b;yi-coder:9b | 20 | 100% GPU;100% GPU | 100% / 100% | 13174 | 815 / 900 | 36% | none |
| yi-coder:9b;qwen3:8b | 45 | 100% GPU;100% GPU | 92% / 100% | 14922 | 593 / 898 | 26% | none |
| qwen2.5-coder:7b | 20 | 100% GPU | 62% / 100% | 7497 | 275 / 453 | 13% | none |


## 11. Gold validation (step 1; golds not edited)

| Pair | Errors | Warnings |
|---|---|---|
| Books-Recommender-System | 1: {'implemented_without_primary_link': 1} | 6: {'evidence_outside_component_module_constant': 1, 'evidence_outside_component_decorator': 5} |
| ProClinic | 1: {'not_implemented_with_links': 1} | 1: {'components_sheet_vs_parser': 1} |
| Travel-Agency-Automation-System | 0: {} | 0: {} |
| Virtual-clinic | 4: {'implemented_without_primary_link': 4} | 1: {'components_sheet_vs_parser': 1} |

## 12. Caveats

- One run per pair (no repeats); CIs cover requirement sampling only, not run-to-run variance.
- Auto-approved review: no human resolved the review items.
- Requirements the gold marks partial without links cannot be scored for search/mapping (see section 11).

## 13. Run notes (what happened during V1)

### DocAgent memory bug, found and fixed during V1

DocAgent's `generate_docstrings.py` builds one `Orchestrator` for the whole repository.
Its Reader, Writer and Verifier only cleared their message history when a docstring was
rejected, so every accepted component added its messages to every later request. Two effects:

- **Speed.** Requests grew steadily. Ollama tokenized the whole history, then truncated it to the
  4096-token context. In the first ProClinic run (run 5), a 3-second generation took
  45 s to 4 min of wall time. The rate fell from 100 components/hour to 1 every 6 min, and the run
  was stopped at 479/558.
- **Quality.** Truncation keeps the tail of the history, so the system prompt was eventually
  dropped. The model also saw earlier components' messages.

**Fix** (`DocAgent/src/agent/orchestrator.py`, commit `b8426b9` on `linux`): each agent's memory
is reset to its system prompt at the start of every component.

**Which runs had the fix**

| Pair | Run scored | DocAgent memory fix | Note |
|---|---|---|---|
| Travel-Agency-Automation-System | 2 | no | 44 components; history grew less (pace stayed at ~32 s/component) |
| Books-Recommender-System | 3 | no | 53 components; same |
| Virtual-clinic | **7** (rerun) | yes | run 4 (no fix) is kept in `results/Virtual-clinic_run4_memory-bug/` |
| ProClinic | **6** (rerun) | yes | run 5 (no fix) was stopped at 479/558 and not scored |

Run 1 failed at start (missing DocAgent config) and is left in the database as stale.

### Virtual-clinic: run 4 (memory bug) vs run 7 (fixed)

| Metric | Run 4 | Run 7 |
|---|---|---|
| Search MRR (stored candidates) | 0.415 | 0.369 |
| Search MRR all_hybrid | 0.383 | 0.346 |
| all_hybrid R@10 | 0.499 | 0.521 |
| Mapping direct P / R | 0.298 / 0.215 | 0.238 / 0.154 |
| Verifier exact accuracy | 0.269 | 0.154 |
| False support | 0% | 4.8% (1 requirement: BR-8) |
| Implemented recall | 30% | 10% |

The fix did not improve the scores. Every LLM stage reran (DocAgent, SRS extraction, verifier),
and the bootstrap CIs overlap. The gap is therefore best read as **run-to-run variance**,
not as an effect of the fix. A shift of this size between two identical-configuration runs is
the strongest argument for the 3 repeats per configuration planned in TEST_PLAN.md.

### Parallel GPU use for the final two runs

The system Ollama server handles one request at a time, and DocAgent leaves the GPU idle
between its calls. Virtual-clinic run 7 therefore ran on a second, user-level Ollama server
(`127.0.0.1:11435`, same model files, `--sequential` lanes) at the same time as ProClinic run 6.
GPU utilisation averaged **96%** over that period, with every model 100% on the GPU. While the
two runs shared the GPU, ProClinic ran at ~60 s/component; alone it ran at ~36 s.
`run_v1.py --ollama-host … --sequential` reproduces this.

