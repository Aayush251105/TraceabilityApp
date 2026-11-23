#!/usr/bin/env bash
# FINAL TESTING V1: run all pairs (resumable) with GPU/CPU sampling.
#   nohup bash final_tests/v1/run_all_v1.sh > final_tests/v1/results/run_all_v1.log 2>&1 &
set -u
cd "$(dirname "$0")/../.."
export PYTHONUNBUFFERED=1
mkdir -p final_tests/v1/results
python3 TraceabilityApp/benchmark/common/resource_monitor.py final_tests/v1/results/resource_usage.csv --interval 10 &
MON=$!
trap 'kill $MON 2>/dev/null' EXIT
echo "######## $(date '+%F %T') start"
SRS_to_code_traceability/.venv/bin/python final_tests/v1/run_v1.py "$@"
echo "######## $(date '+%F %T') runs finished (rc=$?)"
