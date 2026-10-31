"""
Application settings.

Two kinds of settings:

- **Paths** (where the agents and their virtual environments live, where run
  data is written).  Derived from the workspace layout, overridable with
  environment variables:

    TRACELIGHT_WORKSPACE      folder holding DocAgent/, SRSAgent/, TraceabilityApp/
    TRACELIGHT_DATA_DIR       run data (uploads, working copies, agent outputs)
    TRACELIGHT_DOCAGENT_DIR / TRACELIGHT_DOCAGENT_PYTHON
    TRACELIGHT_SRSAGENT_DIR / TRACELIGHT_SRSAGENT_PYTHON

- **User settings** (models per agent, thresholds, limits), edited on the
  Settings page and stored as JSON in the data folder.  Each run records the
  settings it started with, so a run can be reproduced and compared.

Database credentials are never stored here; they come from the traceability
package's environment variables (TRACELIGHT reuses TraceabilityConfig).
"""

from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_APP_DIR = _BACKEND_DIR.parent


def _venv_python(project: Path) -> Path:
    scripts = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return project / ".venv" / scripts


DEFAULTS: Dict[str, Any] = {
    "models": {
        "docagent": "yi-coder:9b",          # docstring generation
        "srs": "llama3.1",                  # requirement extraction
        "judge": "qwen2.5:3b",              # candidate judge
        "verifier": "qwen2.5-coder:7b",     # claim verification
    },
    "ollama_host": "http://localhost:11434",
    "ingest": {
        # Run the code lane and the SRS lane at the same time.  On a GPU that
        # cannot hold both models, Ollama swaps them and sequential is faster.
        "parallel": True,
        "overwrite_docstrings": True,
    },
    "search": {"top_n": 10, "candidate_k": 50},
    "mapping": {"max_direct_rank": 3, "max_supporting": 6, "use_source_references": True},
    "verification": {"claims": "clauses"},
    "review": {"duplicate_threshold": 0.9},
    "limits": {
        "max_upload_mb": 200,
        "large_repo_files": 400,        # warn above this many Python files
        "large_repo_components": 1500,  # warn above this many components
    },
    "source": {
        "exclude_dirs": [".git", ".hg", ".svn", "venv", ".venv", "env", "node_modules",
                         "build", "dist", "site-packages", "__pycache__", ".tox", ".mypy_cache",
                         ".pytest_cache", ".idea", ".vscode"],
    },
}


def _merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class AppPaths:
    workspace: Path
    data_dir: Path
    docagent_dir: Path
    docagent_python: Path
    srsagent_dir: Path
    srsagent_python: Path
    runners_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "runners")

    @classmethod
    def from_env(cls) -> "AppPaths":
        env = os.environ.get
        workspace = Path(env("TRACELIGHT_WORKSPACE") or _APP_DIR.parent)
        docagent = Path(env("TRACELIGHT_DOCAGENT_DIR") or workspace / "DocAgent")
        srsagent = Path(env("TRACELIGHT_SRSAGENT_DIR") or workspace / "SRSAgent")
        return cls(
            workspace=workspace,
            data_dir=Path(env("TRACELIGHT_DATA_DIR") or _APP_DIR / "data"),
            docagent_dir=docagent,
            docagent_python=Path(env("TRACELIGHT_DOCAGENT_PYTHON") or _venv_python(docagent)),
            srsagent_dir=srsagent,
            srsagent_python=Path(env("TRACELIGHT_SRSAGENT_PYTHON") or _venv_python(srsagent)),
        )

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"


class SettingsStore:
    """User settings as JSON (defaults merged with what the user saved)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Dict[str, Any]:
        saved: Dict[str, Any] = {}
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                saved = {}
        return _merge(DEFAULTS, saved)

    def save(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        merged = _merge(self.load(), changes)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        return merged


def effective_settings(store: SettingsStore, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Saved settings with per-run overrides applied (e.g. a model chosen on the New run page)."""
    return _merge(store.load(), overrides or {})
