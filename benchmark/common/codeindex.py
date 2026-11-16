"""Code components of a test pair (from the gold components tab + the cloned code) and a small BM25."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List

from common.config import ws_path

_SPLIT = re.compile(r"[A-Za-z][a-z]+|[A-Z]+(?![a-z])|\d+")


def code_tokens(text: str) -> List[str]:
    """Split identifiers (snake_case, camelCase) into lower-case words."""
    return [t.lower() for t in _SPLIT.findall(text or "") if len(t) > 1]


class BM25:
    def __init__(self, docs: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.avg = sum(map(len, docs)) / max(1, len(docs))
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, q: List[str]) -> List[float]:
        out = []
        for tf, d in zip(self.tf, self.docs):
            s = 0.0
            for t in set(q):
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
            out.append(s)
        return out


def load_components(cfg, pair_id: str, gold: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Gold components with their source code read from datasets/Data/<pair>/code."""
    root = ws_path(cfg["paths"]["datasets"]) / pair_id / "code"
    comps, cache = [], {}
    for c in gold["components"]:
        path = root / (c["path"] or "")
        if path not in cache:
            try:
                cache[path] = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                cache[path] = []
        lines = cache[path]
        start = c["start_line"] or 1
        end = c["end_line"] or len(lines)
        src = "\n".join(lines[start - 1:end])
        comps.append({"component_id": c["component_id"], "component_type": c["type"] or "function",
                      "relative_path": c["path"], "start_line": start, "end_line": end, "source_code": src,
                      "text": f"{c['component_id']}\n{c['path']}\n{src}"})
    return comps
