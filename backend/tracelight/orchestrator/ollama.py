"""Ollama availability: is the server reachable, which models are pulled (standard library only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Dict, Iterable, List


class OllamaUnavailable(RuntimeError):
    pass


def list_models(host: str, timeout: float = 3.0) -> List[str]:
    """Names of the locally pulled models (e.g. 'llama3.1:latest')."""
    url = host.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise OllamaUnavailable(f"Ollama is not reachable at {host} ({exc})") from exc
    return [m.get("name") or m.get("model") for m in data.get("models", []) if m.get("name") or m.get("model")]


def has_model(name: str, available: Iterable[str]) -> bool:
    """'llama3.1' matches 'llama3.1:latest'; a tagged name must match exactly."""
    available = set(available)
    return name in available or (":" not in name and f"{name}:latest" in available)


def check_models(host: str, models: Dict[str, str], timeout: float = 3.0) -> Dict[str, bool]:
    """{role: pulled?} for the given {role: model name}; raises OllamaUnavailable."""
    available = list_models(host, timeout)
    return {role: has_model(name, available) for role, name in models.items()}
