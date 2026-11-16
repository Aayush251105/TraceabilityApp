#!/usr/bin/env bash
# Run the whole SRS Agent + verifier benchmark end to end (resumable).
# From the workspace root:
#   nohup bash TraceabilityApp/benchmark/run_all.sh > TraceabilityApp/benchmark/results/run_all.log 2>&1 &
set -u
cd "$(dirname "$0")/../.."
SRS=SRSAgent/.venv/bin/python
TR=SRS_to_code_traceability/.venv/bin/python
B=TraceabilityApp/benchmark
export PYTHONUNBUFFERED=1
step() { echo; echo "######## $(date '+%F %T') $*"; }

step "0. golds, candidates, cases"
$TR  $B/common/gold.py
$SRS $B/srs_agent/prepare_candidates.py
$TR  $B/verifier/build_cases.py
step "1. SRS candidate judge"
[ -f $B/results/srs_agent/judge/judge_metrics.json ] || $SRS $B/srs_agent/judge_benchmark.py
step "2a. SRS extractor generations"
$SRS $B/srs_agent/generate_extractions.py --all
step "3a. verifier generations"
$TR  $B/verifier/generate_verdicts.py --all
step "2b. SRS extractor evaluation + report"
$TR  $B/srs_agent/run_benchmark.py
step "3b. verifier evaluation + report"
$TR  $B/verifier/run_benchmark.py
step "done"
