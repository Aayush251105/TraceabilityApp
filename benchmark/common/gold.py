"""
Convert the gold annotation workbooks (datasets/Data/<pair>/<pair>_gold.xlsx)
to JSON, so the benchmarks need no spreadsheet library at run time.

    SRS_to_code_traceability/.venv/bin/python TraceabilityApp/benchmark/common/gold.py

Writes TraceabilityApp/benchmark/data/gold/<pair>.json:
    {"pair_id", "repo_info": {...}, "draft": true,
     "requirements": [{"requirement_id", "text", "status", "sure", "notes"}],
     "links": [{"requirement_id", "component", "role", "lines", "sure", "notes"}],
     "components": [{"component_id", "type", "path", "start_line", "end_line"}]}

Row 2 of every data tab is the instruction row and is skipped.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.config import load_config, ws_path  # noqa: E402

TABS = {
    "requirements": ("requirement_id", "text", "status", "sure", "notes"),
    "links": ("requirement_id", "component", "role", "lines", "sure", "notes"),
    "components": ("component_id", "type", "path", "start_line", "end_line"),
}


def _clean(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def convert(xlsx: Path) -> dict:
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    out = {"pair_id": None, "source_workbook": xlsx.name, "draft": True,
           "repo_info": {str(r[0]): _clean(r[1]) for r in wb["repo_info"].iter_rows(values_only=True) if r[0]}}
    out["pair_id"] = out["repo_info"].get("pair_id")
    for tab, cols in TABS.items():
        rows = []
        for r in wb[tab].iter_rows(min_row=3, values_only=True):
            if not r or not _clean(r[0]):
                continue
            row = {c: _clean(r[i]) if i < len(r) else None for i, c in enumerate(cols)}
            for k in ("start_line", "end_line"):
                if k in row and row[k] is not None:
                    row[k] = int(row[k])
            rows.append(row)
        out[tab] = rows
    return out


def main() -> None:
    cfg = load_config()
    out_dir = ws_path(cfg["paths"]["gold_json"])
    out_dir.mkdir(parents=True, exist_ok=True)
    for pair in cfg["pairs"]:
        xlsx = ws_path(cfg["paths"]["datasets"]) / pair["id"] / f"{pair['id']}_gold.xlsx"
        gold = convert(xlsx)
        (out_dir / f"{pair['id']}.json").write_text(json.dumps(gold, indent=2, ensure_ascii=False) + "\n",
                                                    encoding="utf-8")
        print(f"{pair['id']}: {len(gold['requirements'])} requirements, {len(gold['links'])} links, "
              f"{len(gold['components'])} components")


if __name__ == "__main__":
    main()
