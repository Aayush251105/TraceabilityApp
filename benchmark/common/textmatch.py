"""
Token-overlap helpers for matching SRS Agent text to gold requirement text.

Matching is by text, not by ID: gold IDs are sometimes renamed by the
annotators (Travel-Agency "REQ1" labels repeat per feature -> FEAT-4.x), so an
ID match would under-count. Same tokeniser as SRSAgent/tools/evaluate_extraction.py.
"""

from __future__ import annotations

import re
from typing import Iterable, List

_TOKEN = re.compile(r"[a-z]+|\d+(?:\.\d+)?")
_STOP = frozenset(
    "a an the and or of to in on for with by be is are was were as at from that this it its "
    "shall should must will can may system".split())


def tokens(text: str) -> List[str]:
    text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", text or "")
    text = text.lower().replace("’", "'")
    return _TOKEN.findall(re.sub(r"\b(?:n?fr|req|feat)-\d+(?:\.\d+)*\b", " ", text))


def content_tokens(text: str) -> List[str]:
    return [t for t in tokens(text) if t not in _STOP and len(t) > 1]


def coverage(target: str, source: str) -> float:
    """Fraction of *target*'s content tokens that occur in *source*."""
    want = content_tokens(target)
    if not want:
        return 1.0
    have = set(content_tokens(source))
    return sum(t in have for t in want) / len(want)


def coverage_of_union(target: str, sources: Iterable[str]) -> float:
    return coverage(target, "\n".join(sources))


def numbers(text: str) -> List[str]:
    return re.findall(r"\d+(?:\.\d+)?", text or "")
