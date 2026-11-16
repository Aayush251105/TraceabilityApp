"""
SRS Agent extractor benchmark — Step 1: generate structured requirements per model.

Input: the candidates the DEFAULT judge (config srs_default_judge, qwen2.5:3b)
retained, taken from judge_benchmark's raw decisions — identical for every
extractor. Each model runs the unmodified SRSAgent.extract (same prompt,
3 attempts, temperature 0, seed 42, num_ctx 8192); only the model changes.

    SRSAgent/.venv/bin/python TraceabilityApp/benchmark/srs_agent/generate_extractions.py --all
    SRSAgent/.venv/bin/python TraceabilityApp/benchmark/srs_agent/generate_extractions.py --model mistral-7b [--overwrite]

Writes results/srs_agent/extractor/raw_generations/<model>.json:
    {"model", "ollama_model", "seconds", "pairs": {pair: {"seconds", "requirements": [...], "failures": [...]}}}
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from common.config import WORKSPACE, load_config, ws_path  # noqa: E402

sys.path.insert(0, str(WORKSPACE / "SRSAgent"))


def retained_candidates(cfg) -> dict:
    judge = next(m for m in cfg["srs_judge_models"] if m["ollama_model"] == cfg["srs_default_judge"])
    f = ws_path(cfg["paths"]["srs_results"]) / "judge" / "raw_decisions" / f"{judge['name']}.json"
    if not f.exists():
        sys.exit(f"missing {f}: run judge_benchmark.py --model {judge['name']} first")
    data = json.loads(f.read_text(encoding="utf-8"))
    return {p: v["retained"] for p, v in data["pairs"].items()}


def generate(cfg, entry, out: Path) -> None:
    from agents.srs_agent import SRSAgent
    from llm.ollama_provider import OllamaProvider

    retained = retained_candidates(cfg)
    res = {"model": entry["name"], "ollama_model": entry["ollama_model"], "pairs": {}}
    total = 0.0
    for pair in cfg["pairs"]:
        agent = SRSAgent(llm_provider=OllamaProvider(model=entry["ollama_model"], host=cfg["ollama"]["host"]))
        cands = retained[pair["id"]]
        t0 = time.time()
        reqs = agent.extract(cands)
        secs = time.time() - t0
        total += secs
        res["pairs"][pair["id"]] = {"seconds": round(secs, 1), "candidates": len(cands),
                                    "requirements": [r.model_dump(mode="json") for r in reqs],
                                    "failures": agent.failures}
        print(f"  {pair['id']}: {len(reqs)}/{len(cands)} extracted, {len(agent.failures)} failed, {secs:.0f}s",
              flush=True)
    res["seconds"] = round(total, 1)
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--model", action="append")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    out_dir = ws_path(cfg["paths"]["srs_results"]) / "extractor" / "raw_generations"
    out_dir.mkdir(parents=True, exist_ok=True)
    for m in cfg["models"]:
        if not args.all and m["name"] not in args.model:
            continue
        out = out_dir / f"{m['name']}.json"
        if out.exists() and not args.overwrite:
            print(f"skip {m['name']} (exists; --overwrite to redo)")
            continue
        print(f"\n=== extractor {m['name']} ({m['ollama_model']})", flush=True)
        try:
            generate(cfg, m, out)
        except Exception as exc:          # keep going; a partial file is never written
            print(f"FAILED {m['name']}: {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
