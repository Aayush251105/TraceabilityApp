#!/usr/bin/env bash
# Re-run ONE model through the SRS extractor and verifier benchmarks, then
# re-judge only what involves that model (the other models' judgments are
# cached) and rebuild both reports. GPU/CPU usage is sampled throughout.
# From the workspace root:
#   nohup bash TraceabilityApp/benchmark/rerun_model.sh qwen3-8b > TraceabilityApp/benchmark/results/rerun_qwen3-8b.log 2>&1 &
# Move the model's old raw_generations/<model>.json (and its judged entries) out first,
# or the generators skip it.
set -u
MODEL=${1:?usage: rerun_model.sh <model name from config.yaml>}
cd "$(dirname "$0")/../.."
SRS=SRSAgent/.venv/bin/python
TR=SRS_to_code_traceability/.venv/bin/python
B=TraceabilityApp/benchmark
export PYTHONUNBUFFERED=1
step() { echo; echo "######## $(date '+%F %T') $*"; }

MON=$B/results/resource_usage/rerun_${MODEL}.csv
mkdir -p "$(dirname "$MON")"
python3 $B/common/resource_monitor.py "$MON" --interval 5 &
MON_PID=$!
trap 'kill $MON_PID 2>/dev/null' EXIT

step "1. SRS extractor generation: $MODEL"
$SRS $B/srs_agent/generate_extractions.py --model "$MODEL"
step "2. verifier generation: $MODEL"
$TR  $B/verifier/generate_verdicts.py --model "$MODEL"
step "3. SRS extractor evaluation + report (only missing judgments run)"
$TR  $B/srs_agent/run_benchmark.py
step "4. verifier evaluation + report (only missing judgments run)"
$TR  $B/verifier/run_benchmark.py

kill $MON_PID 2>/dev/null; wait $MON_PID 2>/dev/null
python3 $B/common/resource_monitor.py --summary "$MON" | tee "${MON%.csv}_summary.md"
step "done"
