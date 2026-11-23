#!/usr/bin/env bash
# Rerun Virtual-clinic (DocAgent memory-reset fix) on a second Ollama server (port 11435) while
# ProClinic runs on the system one, so the GPU serves two DocAgent streams at once.
cd "$(dirname "$0")/../.."
until ! ollama ps | grep -q qwen3; do sleep 15; done       # wait until ProClinic's SRS models left VRAM
echo "=== $(date) Virtual-clinic rerun (memory-reset fix) on 127.0.0.1:11435, sequential lanes"
SRS_to_code_traceability/.venv/bin/python final_tests/v1/run_v1.py --pairs Virtual-clinic --force \
    --ollama-host http://127.0.0.1:11435 --sequential
