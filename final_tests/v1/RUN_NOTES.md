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
