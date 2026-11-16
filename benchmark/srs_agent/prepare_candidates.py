"""
Step 0 — parse + detect each test-pair SRS once (no LLM).

Runs the SRS Agent's own input adapter, parser and RequirementDetector exactly
as SRSAgent/app.py:main does, and caches the candidates, so every judge and
extractor model sees identical input.

    SRSAgent/.venv/bin/python TraceabilityApp/benchmark/srs_agent/prepare_candidates.py

Writes results/srs_agent/candidates/<pair>.json:
    {"pair_id", "srs_file", "input_type", "candidates": [...], "segmentation": {...}}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from common.config import WORKSPACE, load_config, ws_path  # noqa: E402

sys.path.insert(0, str(WORKSPACE / "SRSAgent"))
import app as srs_app  # noqa: E402
from parsers.input_adapter import InputAdapter  # noqa: E402
from processors.requirement_detector import RequirementDetector  # noqa: E402


def detect(srs_path: Path) -> dict:
    adapted = InputAdapter().adapt(str(srs_path))
    input_type = adapted["type"]
    document = srs_app.parse_input(adapted["data"], input_type)
    detector = RequirementDetector()
    if input_type in {"pdf", "docx"}:
        candidates = detector.detect(document, input_type)
    else:
        candidates = detector.detect_text(document["text"], file_name=document.get("file_name"))
    for c in candidates:
        c["input_kind"] = "text" if input_type == "text" else "document"
    seg = detector.last_report
    return {
        "srs_file": srs_path.name, "input_type": input_type, "candidates": candidates,
        "segmentation": None if seg is None else {
            "skipped_sections": seg.skipped_sections, "warnings": seg.warnings,
            "duplicates": seg.duplicates, "repeated_ids": seg.repeated_ids,
        },
    }


def main() -> None:
    cfg = load_config()
    out_dir = ws_path(cfg["paths"]["srs_results"]) / "candidates"
    out_dir.mkdir(parents=True, exist_ok=True)
    for pair in cfg["pairs"]:
        srs = ws_path(cfg["paths"]["datasets"]) / pair["id"] / pair["srs"]
        res = {"pair_id": pair["id"], **detect(srs)}
        (out_dir / f"{pair['id']}.json").write_text(
            json.dumps(res, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        conf = {}
        for c in res["candidates"]:
            conf[c.get("detection_confidence")] = conf.get(c.get("detection_confidence"), 0) + 1
        print(f"{pair['id']}: {len(res['candidates'])} candidates {conf}")


if __name__ == "__main__":
    main()
