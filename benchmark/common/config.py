"""Load benchmark/config.yaml and resolve paths against the workspace root."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

BENCH_DIR = Path(__file__).resolve().parent.parent          # TraceabilityApp/benchmark
WORKSPACE = BENCH_DIR.parent.parent                          # folder holding all four projects


def load_config(path: str | Path | None = None) -> Dict[str, Any]:
    cfg_path = Path(path) if path else BENCH_DIR / "config.yaml"
    with open(cfg_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def ws_path(rel: str) -> Path:
    """A config path (relative to the workspace root) as an absolute Path."""
    p = Path(rel)
    return p if p.is_absolute() else WORKSPACE / p


def model_by_name(cfg: Dict[str, Any], name: str, key: str = "models") -> Dict[str, Any]:
    for m in cfg[key]:
        if m["name"] == name:
            return m
    raise KeyError(f"model {name!r} not in config[{key!r}]")
