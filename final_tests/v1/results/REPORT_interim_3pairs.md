# Tracelight — Final Testing V1 Report

> **V1 - human-annotated gold.** One run per pair, default models, auto-approved review (no human). 95% bootstrap CIs over requirements in brackets.

## Setup

| Pair | Run | Components | Gold reqs (scored set / excluded) | Commit |
|---|---|---|---|---|
| Travel-Agency-Automation-System | 2 | 44 | 14 / 5 | `2cc23a2f3b` |
| Books-Recommender-System | 3 | 53 | 33 / 7 | `69ed627f0f` |
| Virtual-clinic | 4 | 233 | 57 / 6 | `b8241e502d` |

Models: srs `qwen3:8b`, judge `qwen3:4b`, docagent `yi-coder:9b`, verifier `qwen2.5-coder:7b` (extractor thinking off). Requirement matching: ID, else difflib ratio ≥ 0.6 on normalised text.

## 1. SRS extraction

| Pair | Extracted | Precision | Recall | F1 | Recall incl. excluded |
|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 27 | 0.667 | 0.929 [0.786, 1.000] | 0.776 | 0.947 |
| Books-Recommender-System | 61 | 0.639 | 1.000 [1.000, 1.000] | 0.780 | 0.975 |
| Virtual-clinic | 91 | 0.582 | 0.895 [0.807, 0.965] | 0.706 | 0.841 |
| **micro (pooled)** | 179 | 0.615 | 0.933 [0.885, 0.971] | 0.741 | — |
| **macro (mean of pairs)** | 59.667 | 0.629 | 0.941 | 0.754 | 0.921 |

## 2. Search (stored candidates used by mapping)

| Pair | MAP | MRR | R@1 | R@5 | R@10 | nDCG@10 | SR@\|G\| | MRR all_hybrid (evaluate) |
|---|---|---|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 0.607 [0.424, 0.770] | 0.705 [0.500, 0.909] | 0.394 | 0.788 | 0.864 | 0.667 | 0.273 | 0.711 |
| Books-Recommender-System | 0.718 [0.599, 0.843] | 0.735 [0.623, 0.852] | 0.537 | 0.894 | 0.920 | 0.722 | 0.556 | 0.709 |
| Virtual-clinic | 0.296 [0.197, 0.408] | 0.415 [0.285, 0.549] | 0.198 | 0.361 | 0.553 | 0.349 | 0.108 | 0.383 |
| **micro (pooled)** | 0.493 [0.410, 0.581] | 0.572 [0.481, 0.664] | 0.349 | 0.616 | 0.730 | — | 0.293 | — |
| **macro (mean of pairs)** | 0.540 | 0.618 | 0.376 | 0.681 | 0.779 | 0.579 | 0.312 | 0.601 |

## 3. Mapping (micro over implemented + partial requirements)

| Pair | Direct P | Direct R | Direct F1 | Direct F2 | All P | All R | All F1 | All F2 |
|---|---|---|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 0.625 [0.400, 0.824] | 0.588 [0.400, 0.750] | 0.606 | 0.595 | 0.329 | 0.750 | 0.457 | 0.597 |
| Books-Recommender-System | 0.676 [0.556, 0.800] | 0.610 [0.394, 0.893] | 0.641 | 0.622 | 0.201 | 0.603 | 0.302 | 0.431 |
| Virtual-clinic | 0.298 [0.188, 0.408] | 0.215 [0.127, 0.321] | 0.250 | 0.228 | 0.129 | 0.259 | 0.173 | 0.216 |
| **micro (pooled)** | 0.490 [0.407, 0.577] | 0.398 [0.304, 0.512] | 0.439 | 0.414 | 0.194 | 0.463 | 0.274 | 0.363 |
| **macro (mean of pairs)** | 0.533 | 0.471 | 0.499 | 0.482 | 0.220 | 0.537 | 0.310 | 0.415 |

## 4. Verification

| Pair | Judged | Exact acc. | Macro-F1 | Weighted κ | False support ↓ | Impl. recall | Citation valid. |
|---|---|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 13 | 0.308 [0.077, 0.538] | 0.248 | 0.077 | 0.0% [0.0%, 0.0%] | 0.0% [0.0%, 0.0%] | 0.778 |
| Books-Recommender-System | 28 | 0.429 [0.250, 0.607] | 0.476 | 0.149 | 0.0% [0.0%, 0.0%] | 50.0% [30.0%, 71.4%] | 0.923 |
| Virtual-clinic | 52 | 0.269 [0.154, 0.404] | 0.314 | 0.171 | 0.0% [0.0%, 0.0%] | 30.0% [0.0%, 62.5%] | 0.873 |
| **micro (pooled)** | 93 | 0.323 [0.226, 0.419] | 0.355 | 0.234 | 0.0% [0.0%, 0.0%] | 40.0% [23.5%, 56.2%] | 0.868 |
| **macro (mean of pairs)** | 31.000 | 0.335 | 0.346 | 0.132 | 0.0% | 26.7% | 0.858 |

*False support* = partial or not-implemented requirements declared `supported`. *Impl. recall* = implemented requirements declared `supported`. κ: linear weights on not (incl. insufficient / unverified) < partial < supported.

## 5. Against the Run 6 library baseline (CLAUDE.md)

Run 6 is the library **dev** set (39 requirements, its own SRS); V1 is 4 unseen test pairs, so this is a sanity comparison, not a like-for-like one.

| Metric | Run 6 (library, dev) | V1 micro (4 test pairs) |
|---|---|---|
| Search MRR (all_hybrid) | 0.936 | 0.601 (mean of pairs) |
| Mapping direct P / R | 0.67 / 0.87 | 0.490 / 0.398 |
| Verifier exact accuracy | 0.833 | 0.323 |
| False support | 0.0 | 0.0% |
| Supported | 27/39 | 15/104 |
| Minutes per pair | 85 | Travel 26.690, Books 33.080, Virtual 228.320 |

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
| Virtual-clinic | partial | 0 | 3 | 27 | 0 | 0 | 1 |
| Virtual-clinic | implemented | 3 | 2 | 5 | 0 | 0 | 0 |
| Virtual-clinic | not_implemented | 0 | 0 | 8 | 0 | 0 | 3 |
| Virtual-clinic | cross_cutting (not scored) | 1 | 0 | 2 | 0 | 0 | 2 |

## 7. Error analysis (every wrong verdict)

Label order: *extraction miss* (gold requirement not extracted) → *gold has no links* → *retrieval miss* (no gold primary among the stored candidates) → *mapping miss* (primary retrieved but not mapped) → *verifier error* (gold code was shown, or the requirement has no code).

| Pair | extraction miss | gold has no links | retrieval miss | mapping miss | verifier error | total wrong |
|---|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 1 | 0 | 1 | 1 | 6 | 9 |
| Books-Recommender-System | 0 | 1 | 0 | 2 | 13 | 16 |
| Virtual-clinic | 4 | 2 | 10 | 10 | 12 | 38 |
| **all** | 5 | 3 | 11 | 13 | 31 | 63 |

## 8. Worst failures

Ordered: false support on not-implemented requirements, then implemented requirements rejected with the right code shown, then other implemented misses, then partial.

| # | Pair | Requirement | Gold | Predicted | Label | First primary rank | Mapped direct |
|---|---|---|---|---|---|---|---|
| 1 | Travel-Agency-Automation-System | FEAT-4.3 | implemented | not_supported_by_candidate | verifier error | 2 | Booking.Booking |
| 2 | Travel-Agency-Automation-System | REQ-005 | implemented | insufficient_evidence | verifier error | 1 | main.main |
| 3 | Books-Recommender-System | FR-1.2 | implemented | not_supported_by_candidate | verifier error | 2 | src.config.configuration.AppConfiguration.get_model_recommendation_config |
| 4 | Books-Recommender-System | FR-1.4 | implemented | not_supported_by_candidate | verifier error | 2 | src.exception.__init__.CustomException.__init__, src.exception.__init__.error_message_deta |
| 5 | Books-Recommender-System | FR-2.1 | implemented | not_supported_by_candidate | verifier error | 3 | src.components.data_ingestion.DataIngestion._create_sample_dataset |
| 6 | Books-Recommender-System | FR-3.4 | implemented | not_supported_by_candidate | verifier error | 3 | src.components.data_transformation.DataTransformation.initiate_data_transformation, src.co |
| 7 | Books-Recommender-System | FR-5.3 | implemented | not_supported_by_candidate | verifier error | 1 | src.components.model_trainer.ModelTrainer.initiate_model_training |
| 8 | Books-Recommender-System | FR-6.4 | implemented | not_supported_by_candidate | verifier error | 1 | src.pipeline.prediction_pipeline.RecommendationEngine.recommend |
| 9 | Books-Recommender-System | FR-7.1 | implemented | not_supported_by_candidate | verifier error | 1 | app.get_book_names |
| 10 | Books-Recommender-System | FR-7.2 | implemented | not_supported_by_candidate | verifier error | 1 | src.pipeline.prediction_pipeline.RecommendationEngine.recommend |
| 11 | Books-Recommender-System | FR-7.3 | implemented | not_supported_by_candidate | verifier error | 1 | src.pipeline.training_pipeline.TrainingPipeline.run_pipeline |
| 12 | Virtual-clinic | Req-4 | implemented | not_supported_by_candidate | verifier error | 1 | server.views_admin.view_symptom |
| 13 | Virtual-clinic | Req-4/1 | implemented | not_supported_by_candidate | verifier error | 3 | server.forms.SymptomForm, server.views_admin.add_symptom, testing.test_admin.TestAdminView |
| 14 | Virtual-clinic | Req-5/2 | implemented | partially_supported | verifier error | 1 | server.views_profile.update_view |
| 15 | Virtual-clinic | BR-2 | implemented | partially_supported | verifier error | 1 | server.forms.LoginForm.clean |
| 16 | Virtual-clinic | BR-6 | implemented | not_supported_by_candidate | verifier error | 1 | server.views.register_user |
| 17 | Travel-Agency-Automation-System | REQ-001 | implemented | not_supported_by_candidate | retrieval miss | — | Booking.Booking.token |
| 18 | Books-Recommender-System | FR-3.1 | implemented | not_supported_by_candidate | mapping miss | 2 | src.entity.config_entity.DataValidationConfig |
| 19 | Books-Recommender-System | FR-3.5 | implemented | not_supported_by_candidate | mapping miss | 2 | src.entity.config_entity.DataValidationConfig |
| 20 | Virtual-clinic | Req-6 | implemented | not_supported_by_candidate | retrieval miss | — | server.views_appointment.list_view |
| 21 | Virtual-clinic | BR-5 | implemented | not_supported_by_candidate | mapping miss | 8 | server.models.MedicalTest.get_populated_fields |
| 22 | Travel-Agency-Automation-System | FEAT-4.11 | not_implemented | unverified | extraction miss | — | — |
| 23 | Virtual-clinic | REQ-007 | not_implemented | unverified | extraction miss | — | — |
| 24 | Virtual-clinic | REQ-008 | not_implemented | unverified | extraction miss | — | — |
| 25 | Virtual-clinic | REQ-009 | not_implemented | unverified | extraction miss | — | — |

All 63 wrong verdicts are in `results/<pair>/per_requirement.csv` (`error_label`).

## 9. Minutes per stage

| Pair | fetch | docstrings | index_code | extract | prepare_review | index_srs | search | map | verify | results | wall total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Travel-Agency-Automation-System | 0.000 | 23.340 | 0.040 | 13.680 | 0.090 | 0.340 | 0.010 | 0.000 | 2.940 | 0.000 | 26.690 |
| Books-Recommender-System | 0.000 | 28.550 | 0.030 | 16.950 | 0.120 | 0.210 | 0.010 | 0.000 | 4.240 | 0.000 | 33.080 |
| Virtual-clinic | 0.000 | 219.440 | 0.050 | 31.610 | 0.110 | 0.200 | 0.020 | 0.010 | 8.520 | 0.000 | 228.320 |

Lanes A (code) and B (SRS) run in parallel, so stage minutes overlap.

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
