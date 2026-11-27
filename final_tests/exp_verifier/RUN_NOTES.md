# Verifier experiment: run notes

Companion to `REPORT.md`, which `run_verifier_exp.py` generates. Each configuration ran once, and nothing
was re-run or tuned on these results.

## What happened during the run

- **Power cut.** The machine went down at about 20:29 on 2026-11-26, during `qwen3-14b-strict` /
  Virtual-clinic. That pair had no eval file, so the script started it again from the beginning
  (same command, no `--force`) at 10:46 on 2026-11-27. Every other config/pair had finished before the
  cut and was skipped. All runs were done by 11:21.
- **Shared GPU.** From 26 Nov afternoon until the power cut, another user's process (`snu`) held about
  5.7 GB of the 16 GB GPU. A 14B model then no longer fitted, and Ollama ran it 30% on the CPU and 70% on the GPU:

  | Config | Ollama placement | Other GPU process |
  |---|---|---|
  | 7b-strict | (before the monitor started) | — |
  | 7b-behavioral | 100% GPU | yes (the 7B still fitted) |
  | 14b-strict | 30%/70% CPU/GPU | yes |
  | 14b-behavioral | 30%/70% CPU/GPU | yes |
  | qwen3-14b-strict: Travel, Books | 31%/69% CPU/GPU | yes |
  | qwen3-14b-strict: Virtual-clinic, ProClinic | 100% GPU | no |
  | qwen3-14b-behavioral | 100% GPU | no |

  **The 14B minutes in `REPORT.md` are therefore inflated and not comparable.** On the same pair,
  `qwen3-14b-behavioral` took 4.1 min on Travel with the full GPU, while `qwen3-14b-strict` took 17.45 min
  with the split. Only `qwen3-14b-behavioral`, and the second half of `qwen3-14b-strict`, give clean 14B timings.

  The weights and temperature (0) were the same, so verdicts should not depend on the placement. CPU and
  GPU arithmetic can still differ in the last bits, the same caveat as for GPU numerics in general.

## Peak VRAM (whole card, 16 376 MiB)

| Setting | Peak used | Of which other user |
|---|---|---|
| qwen2.5-coder:7b (7b-behavioral) | 12 716 MiB | ~5 736 MiB → ~7.0 GB for the 7B |
| 14B, shared GPU (30% on CPU) | 15 027 MiB | ~5 736 MiB |
| qwen3:14b, full GPU | 10 826 MiB | 0 |

## Sanity check of the selected configuration (`14b-strict`)

Each entry gives the claim, the cited code and a judgment. They come from
`traceability.cli show-verification <ID> --document-id <D> --pipeline-version verification-exp-14b-strict`.

### New `supported` verdicts that are correct per gold (5 of 13 shown)

| Pair / ID | Cited code | Judgment |
|---|---|---|
| Travel REQ-005 (text front-end) | `main.main` main.py:11-17, the console menu | Genuine. |
| Books FR-1.4 (exception handler, traceback, structured report) | call sites `utils.common.save_bin` 37-38 and `TrainingPipeline.run_pipeline` 31-33 that raise or log `CustomException` | Right verdict, weak evidence. The traceback capture in `CustomException` itself is asserted, not cited. |
| Virtual-clinic Req-4 (master list of symptoms) | `views_admin.view_symptom` 170-172 (`Symptom.objects.all()`) | Genuine. |
| Virtual-clinic BR-6 (patient registers; unique id) | `views.register_user` 102-125 (User, Profile, Account) | Genuine. The unique id is the implicit Django primary key. |
| ProClinic US001 (admin manages system roles) | `permissions.IsAdminRole.has_permission` 36-41 | Right verdict for a weak reason. The cited code only checks the ADMIN role and does not manage roles. The gold primary was not shown. |

### Every false support (gold partial or not_implemented → `supported`): 6 of 64

| Pair / ID | Gold | What the verifier said | Judgment |
|---|---|---|---|
| Travel FEAT-4.4 (REQ-013) | partial: no return-time validation, no initial reading | all 4 claims supported; it cites `print("Pay Advance Amount")` for "notes down the car's initial readings" and a print line for "updates the database" | **Clear error.** The citations do not show the claims, and the rationale invents behaviour. |
| Travel FEAT-4.6 (REQ-015) | partial: different wrong-password/wrong-model messages; models not listed | supported, citing main.py:78-79 "Please enter the correct password" for "Wrong password." | **Borderline.** The core lookup works. The verifier ignored the exact messages and the missing model list. |
| Books FR-3.2 (user filter < 200) | partial: silently lowers the threshold to 5 if < 50 rows survive | supported, citing `data_validation.py:54-58` | **Borderline.** The cited rule is there, but the fallback a few lines later was missed. |
| Virtual-clinic Req-3 (maintain chemist & lab details) | partial: roles only, no details | supported, citing the `ACCOUNT_LAB` / `ACCOUNT_CHEMIST` constants in `models.Account` | **Clear error.** Role constants are not "maintaining details". The gold primary (`createemployee_view`) was not shown. |
| Virtual-clinic Req-6/1 (consultation request; upload reports) | partial: patients cannot upload reports | supported, citing `AppointmentForm`; it says uploading is "implied by the form fields" | **Clear error.** The upload part is invented. |
| ProClinic US006 (any user gets answers to system queries) | not_implemented: the AI desk is for patients only and answers general health questions | supported, citing `patients.views.patient_ai_ask` 395-406 (Gemini call) | **Scope error.** The code exists, but for a different user and purpose. |

Summary: 3 of 6 are clear errors, with citations that do not show the claim; 3 are scope or detail
misses on requirements that are mostly implemented. None looks like a gold mistake.
