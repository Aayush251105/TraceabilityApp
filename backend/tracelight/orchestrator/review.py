"""
The human review checkpoint between requirement extraction and tracing.

build_review_items() turns the SRS Agent's output into review items in four
categories (the tabs of the Review page):

  uncertain    candidates the judge could not decide on (not extracted yet);
               also skipped sections/tables, shown pre-discarded so they can
               be restored
  flagged      extracted with review_required / low judge confidence, or a
               candidate whose extraction failed after retries
  incomplete   text that introduces a list or table that is not there
               (segmenter warning, or the text ends with ':'), or empty text
  split        possible duplicates: the same requirement ID twice, or two
               requirements whose texts are near-identical (embeddings)

Every other extracted requirement needs no decision and is traced as is.

apply_review() applies the user's resolutions and returns the requirement
list to ingest plus the candidates that still need extraction (kept
uncertain candidates, failed extractions, restored skipped items):

  kept         keep as extracted (or extract, for a candidate)
  edited       keep with the user's text (replaces raw and normalized text)
  discarded    drop
  merged       append to another requirement (resolution_data.into)
  unreviewed   "skip remaining": keep, marked unreviewed in the results
  resolution_data.requirement_id renames the requirement.

Nothing is decided silently: an item without a resolution blocks the run
until the user resolves it or skips the remaining items.
"""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

CATEGORIES = ("uncertain", "flagged", "incomplete", "split")
RESOLUTIONS = ("kept", "edited", "discarded", "merged", "unreviewed")
KEEPING = ("kept", "edited", "unreviewed")

# {key: text} -> {key: vector}; keys with empty text may be omitted.
EmbedFn = Callable[[Dict[str, str]], Dict[str, List[float]]]


class ReviewError(ValueError):
    """The resolutions cannot be applied (shown to the user, with the item keys)."""

    def __init__(self, message: str, keys: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.keys = list(keys)


# ---------------------------------------------------------------------------
# SRS Agent outputs
# ---------------------------------------------------------------------------


@dataclass
class SRSOutputs:
    requirements: List[Dict[str, Any]]
    report: Dict[str, Any] = field(default_factory=dict)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    blocks: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, out_dir: Path) -> "SRSOutputs":
        def read(name, default):
            path = out_dir / name
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
        blocks = read("document_blocks.json", {})
        return cls(requirements=read("requirements.json", []), report=read("extraction_report.json", {}),
                   candidates=read("candidates.json", []), blocks=blocks.get("blocks", []))


def _location(source: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {k: v for k, v in (source or {}).items() if v is not None and k in
            ("section", "subsection", "page", "paragraph", "table", "row", "page_end", "paragraph_end")}


def _title(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _req_payload(req: Dict[str, Any], reasons: List[str], **extra: Any) -> Dict[str, Any]:
    return {"kind": "requirement", "title": req.get("title") or _title(req.get("raw_text", "")),
            "type": req.get("type"), "subtype": req.get("subtype"),
            "confidence": req.get("candidate_confidence"),
            "source_text": req.get("raw_text", ""), "normalized_text": req.get("normalized_text", ""),
            "location": _location(req.get("source")), "reasons": reasons, **extra}


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def similar_pairs(reqs: List[Dict[str, Any]], embed: EmbedFn, threshold: float) -> List[Tuple[int, int, float]]:
    """(earlier index, later index, similarity) for near-identical requirement texts.
    A parent and its own child requirement are not duplicates."""
    texts = {str(i): (r.get("normalized_text") or r.get("raw_text") or "").strip() for i, r in enumerate(reqs)}
    vectors = embed({k: t for k, t in texts.items() if t})
    pairs = []
    for i in range(len(reqs)):
        for j in range(i + 1, len(reqs)):
            vi, vj = vectors.get(str(i)), vectors.get(str(j))
            if vi is None or vj is None:
                continue
            a, b = reqs[i], reqs[j]
            if a.get("requirement_id") and a.get("requirement_id") in (b.get("parent_requirement_id"),):
                continue
            if b.get("requirement_id") and b.get("requirement_id") in (a.get("parent_requirement_id"),):
                continue
            sim = _cosine(vi, vj)
            if sim >= threshold:
                pairs.append((i, j, sim))
    return pairs


def embedder_fn(embedder: Any) -> EmbedFn:
    """Adapt traceability.embedder.Embedder to EmbedFn."""
    def embed(texts: Dict[str, str]) -> Dict[str, List[float]]:
        return {k: r.vector for k, r in embedder.embed_batch(texts).items()} if texts else {}
    return embed


# ---------------------------------------------------------------------------
# Building items
# ---------------------------------------------------------------------------


def _is_incomplete(req: Dict[str, Any]) -> Optional[str]:
    raw = (req.get("raw_text") or "").rstrip()
    if not raw.strip():
        return "The requirement text is empty."
    if raw.endswith(":"):
        return "The text ends with a colon and introduces a list that was not attached to it."
    return None


def build_review_items(out: SRSOutputs, *, embed: Optional[EmbedFn] = None,
                       duplicate_threshold: float = 0.9) -> List[Dict[str, Any]]:
    reqs = out.requirements
    report = out.report or {}
    seg = report.get("segmentation") or {}
    by_category: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORIES}
    auto: List[Dict[str, Any]] = []

    # --- requirement-level findings (one item per requirement, strongest category wins)
    findings: Dict[int, Dict[str, Any]] = {}

    def note(index: int, category: str, reason: str, **extra: Any) -> None:
        f = findings.setdefault(index, {"categories": [], "reasons": [], "extra": {}})
        if category not in f["categories"]:
            f["categories"].append(category)
        f["reasons"].append(reason)
        f["extra"].update(extra)

    index_of_id: Dict[str, int] = {}
    for i, r in enumerate(reqs):
        rid = r.get("requirement_id") or ""
        if rid and rid.casefold() in index_of_id:
            first = index_of_id[rid.casefold()]
            note(i, "split", f"Same requirement ID as an earlier requirement ({rid}). "
                             f"Merge it, rename it or discard it.", suggestion={"action": "merge", "target": rid})
        elif rid:
            index_of_id[rid.casefold()] = i
        reason = _is_incomplete(r)
        if reason:
            note(i, "incomplete", reason, suggestion={"action": "edit"})
        if r.get("review_required"):
            note(i, "flagged", r.get("candidate_reason") or "The SRS Agent marked this requirement for review.")
        elif (r.get("candidate_confidence") or "").lower() == "low":
            note(i, "flagged", f"Low judge confidence: {r.get('candidate_reason') or 'no reason given'}")

    for w in seg.get("warnings") or []:
        rid = (w.get("requirement_id") or "").casefold()
        if rid in index_of_id:
            note(index_of_id[rid], "incomplete", w.get("message") or "Possibly incomplete.",
                 suggestion={"action": "edit"})

    if embed is not None and len(reqs) > 1:
        for i, j, sim in similar_pairs(reqs, embed, duplicate_threshold):
            target = reqs[i].get("requirement_id") or f"#{i + 1}"
            note(j, "split", f"{round(sim * 100)}% similar to {target} "
                             f"“{_title(reqs[i].get('title') or reqs[i].get('raw_text', ''), 40)}”. Possibly a duplicate.",
                 suggestion={"action": "merge", "target": target}, similarity=round(sim, 3))

    priority = ("incomplete", "split", "flagged")
    for i, f in sorted(findings.items()):
        r = reqs[i]
        category = next(c for c in priority if c in f["categories"])
        rid = r.get("requirement_id") or ""
        by_category[category].append({
            "key": f"req:{i}", "category": category, "requirement_id": rid,
            "payload": _req_payload(r, f["reasons"], index=i, also=[c for c in f["categories"] if c != category],
                                    **f["extra"])})

    # --- candidates that were not extracted
    for d in report.get("candidate_review") or []:
        text = d.get("text") or ""
        by_category["uncertain"].append({
            "key": f"cand:{d.get('candidate_id')}", "category": "uncertain",
            "requirement_id": d.get("source_requirement_id"),
            "payload": {"kind": "candidate", "candidate_id": d.get("candidate_id"), "title": _title(text),
                        "source_text": text, "normalized_text": text, "confidence": d.get("confidence"),
                        "location": _location(d.get("source")),
                        "reasons": [f"The judge was unsure: {d.get('reason') or 'no reason given'}"]}})
    for n, fail in enumerate(report.get("extraction_failures") or [], start=1):
        text = fail.get("text") or ""
        by_category["flagged"].append({
            "key": f"fail:{n}", "category": "flagged", "requirement_id": fail.get("requirement_id"),
            "payload": {"kind": "failure", "title": _title(text), "source_text": text, "normalized_text": text,
                        "location": _location(fail.get("source")),
                        "reasons": [f"Extraction failed after retries: {fail.get('error')}. "
                                    f"Keep it to retry extraction."]}})

    # --- skipped content, pre-discarded (the user can restore it)
    for n, s in enumerate(seg.get("skipped_sections") or [], start=1):
        items = [t for t in (s.get("items") or []) if t and t.strip()]
        if not items:
            continue
        auto.append({
            "key": f"skip:section:{n}", "category": "uncertain", "requirement_id": None,
            "resolution": "discarded", "resolution_data": {"auto": True},
            "payload": {"kind": "skipped_section", "title": s.get("heading") or "Skipped section",
                        "source_text": "\n".join(items), "normalized_text": "", "items": items,
                        "location": _location(s.get("location")),
                        "reasons": [f"Section “{s.get('heading')}” looks descriptive (not requirements) "
                                    f"and was skipped ({len(items)} item(s))."]}})
    for n, t in enumerate(seg.get("skipped_tables") or [], start=1):
        first = t.get("first_row") or []
        auto.append({
            "key": f"skip:table:{n}", "category": "uncertain", "requirement_id": None,
            "resolution": "discarded", "resolution_data": {"auto": True},
            "payload": {"kind": "skipped_table", "title": "Table: " + _title(" | ".join(map(str, first)), 50),
                        "source_text": " | ".join(map(str, first)), "normalized_text": "", "items": [],
                        "location": _location(t.get("location")),
                        "reasons": [f"Table skipped: {t.get('reason')}."]}})

    items = [it for c in CATEGORIES for it in by_category[c]] + auto
    return items


# ---------------------------------------------------------------------------
# Applying resolutions
# ---------------------------------------------------------------------------


@dataclass
class ReviewResult:
    requirements: List[Dict[str, Any]]          # to ingest (after extraction of `to_extract`)
    to_extract: List[Dict[str, Any]]            # SRS Agent candidates (candidate_id = item key)
    summary: Dict[str, int]


def _merge_into(target: Dict[str, Any], text: str, normalized: str, source_key: str,
                extra: Optional[Dict[str, Any]] = None) -> None:
    target["raw_text"] = (target.get("raw_text") or "").rstrip() + "\n" + text.strip()
    norm = (target.get("normalized_text") or "").rstrip()
    target["normalized_text"] = (norm + " " + (normalized or text).strip()).strip()
    target.setdefault("sub_requirements", []).append((normalized or text).strip())
    for key in ("conditions", "constraints", "error_conditions", "preconditions", "postconditions"):
        for value in (extra or {}).get(key) or []:
            if value not in target.setdefault(key, []):
                target[key].append(value)
    target.setdefault("review", {}).setdefault("merged_from", []).append(source_key)


def apply_review(out: SRSOutputs, items: List[Dict[str, Any]]) -> ReviewResult:
    """
    items: review items as stored (key/item_key, category, payload, resolution,
    resolution_data).  Raises ReviewError when items are unresolved, a merge
    target does not exist or is itself dropped, or two kept requirements share an ID.
    """
    norm_items = [{**it, "key": it.get("key") or it.get("item_key")} for it in items]
    pending = [it["key"] for it in norm_items if not it.get("resolution")]
    if pending:
        raise ReviewError(f"{len(pending)} review item(s) are unresolved.", pending)
    bad = [it["key"] for it in norm_items if it["resolution"] not in RESOLUTIONS]
    if bad:
        raise ReviewError("Unknown resolution.", bad)

    reqs = copy.deepcopy(out.requirements)
    decision: Dict[int, Dict[str, Any]] = {}
    for it in norm_items:
        if it["payload"].get("kind") == "requirement":
            decision[it["payload"]["index"]] = it

    # Final IDs of requirements that stay (renames applied) — merge targets refer to these.
    final_id: Dict[int, str] = {}
    for i, r in enumerate(reqs):
        it = decision.get(i)
        if it and it["resolution"] in ("discarded", "merged"):
            continue
        new_id = ((it or {}).get("resolution_data") or {}).get("requirement_id")
        final_id[i] = (new_id or r.get("requirement_id") or "").strip()
    kept_by_id: Dict[str, int] = {}
    duplicates: List[str] = []
    for i, rid in final_id.items():
        if not rid:
            continue
        if rid.casefold() in kept_by_id:
            duplicates.append(rid)
        kept_by_id.setdefault(rid.casefold(), i)

    def target_index(it: Dict[str, Any]) -> int:
        into = ((it.get("resolution_data") or {}).get("into") or "").strip()
        own = (it.get("requirement_id") or "").strip()
        if into and it["payload"].get("kind") == "requirement" and into.casefold() == own.casefold() \
                and into.casefold() not in kept_by_id:
            raise ReviewError("A requirement cannot be merged into itself.", [it["key"]])
        if not into or into.casefold() not in kept_by_id:
            raise ReviewError(f"Merge target {into or '(none)'} is not a kept requirement.", [it["key"]])
        return kept_by_id[into.casefold()]

    if duplicates:
        keys = [it["key"] for it in norm_items if (it.get("requirement_id") or "") in duplicates]
        raise ReviewError(f"These IDs are used by more than one kept requirement: "
                          f"{', '.join(sorted(set(duplicates)))}. Rename, merge or discard one.", keys)

    summary = {r: 0 for r in RESOLUTIONS}
    to_extract: List[Dict[str, Any]] = []
    merges: List[Tuple[int, Dict[str, Any]]] = []
    for it in norm_items:
        summary[it["resolution"]] += 1
        p, res, data = it["payload"], it["resolution"], it.get("resolution_data") or {}
        if p.get("kind") == "requirement":
            i = p["index"]
            r = reqs[i]
            if res == "merged":
                merges.append((target_index(it), it))
            elif res in KEEPING:
                if data.get("requirement_id"):
                    r.setdefault("review", {})["original_requirement_id"] = r.get("requirement_id")
                    r["requirement_id"] = data["requirement_id"].strip()
                if res == "edited":
                    text = (data.get("text") or "").strip()
                    if not text:
                        raise ReviewError("Edited text is empty.", [it["key"]])
                    r.setdefault("review", {})["original_raw_text"] = r.get("raw_text")
                    r["raw_text"] = text
                    r["normalized_text"] = text
                    r["sub_requirements"] = []        # derived from the old text
                r.setdefault("review", {})["status"] = "unreviewed" if res == "unreviewed" else res
                r["review"]["item"] = it["key"]
            continue
        # candidates, failures, skipped content
        if res == "merged":
            merges.append((target_index(it), it))
        elif res in KEEPING:
            if res == "edited":
                texts = [(data.get("text") or "").strip()]
                if not texts[0]:
                    raise ReviewError("Edited text is empty.", [it["key"]])
            elif p.get("kind") == "skipped_section":
                texts = list(p.get("items") or [])      # each item of the section is a candidate
            else:
                texts = [p.get("source_text", "")]
            single = len(texts) == 1
            for n, text in enumerate(texts, start=1):
                cand = _candidate_for(out, it, text)
                cand["candidate_id"] = it["key"] if single else f"{it['key']}#{n}"
                if data.get("requirement_id") and single:
                    cand["source_requirement_id"] = data["requirement_id"].strip()
                cand["review_status"] = "unreviewed" if res == "unreviewed" else res
                to_extract.append(cand)

    for idx, it in merges:
        p = it["payload"]
        if p.get("kind") == "requirement":
            src = reqs[p["index"]]
            _merge_into(reqs[idx], src.get("raw_text", ""), src.get("normalized_text", ""), it["key"], src)
        else:
            text = (it.get("resolution_data") or {}).get("text") or p.get("source_text", "")
            _merge_into(reqs[idx], text, text, it["key"])

    kept = [r for i, r in enumerate(reqs) if i in final_id]
    return ReviewResult(requirements=kept, to_extract=to_extract, summary=summary)


def _candidate_for(out: SRSOutputs, item: Dict[str, Any], text: str) -> Dict[str, Any]:
    """An SRS Agent candidate for text the user kept (from candidates.json when available)."""
    p = item["payload"]
    cand: Dict[str, Any] = {}
    cid = p.get("candidate_id") or ""
    m = re.match(r"^C-(\d+)$", cid)
    if m and 0 < int(m.group(1)) <= len(out.candidates):
        cand = copy.deepcopy(out.candidates[int(m.group(1)) - 1])
    if not cand or (cand.get("text") or "").strip() != text.strip():
        cand = {"text": text, "source": dict(p.get("location") or {}), "detection_confidence": "low",
                "detection_reason": "kept by the user at review"}
    cand["text"] = text
    cand["candidate_decision"] = "keep"
    cand["candidate_confidence"] = "user"
    cand["candidate_reason"] = "Kept by the user at review"
    return cand


def add_extracted(requirements: List[Dict[str, Any]], extracted: List[Dict[str, Any]],
                  to_extract: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Append requirements extracted after review.  Generated IDs (REQ-nnn) are
    renumbered to not collide with existing IDs; a source ID that collides
    gets a suffix.  Review status is carried over from the candidate.
    """
    out = list(requirements)
    used = {(r.get("requirement_id") or "").casefold() for r in out}
    by_cand = {c["candidate_id"]: c for c in to_extract}
    numbers = [int(m.group(1)) for r in out
               for m in [re.match(r"^REQ-(\d+)$", r.get("requirement_id") or "")] if m]
    next_no = max(numbers, default=0) + 1
    for req in extracted:
        req = copy.deepcopy(req)
        rid = (req.get("requirement_id") or "").strip()
        if req.get("id_source") == "generated" or not rid:
            while f"REQ-{next_no:03d}".casefold() in used:
                next_no += 1
            rid = f"REQ-{next_no:03d}"
            next_no += 1
        elif rid.casefold() in used:
            base, n = rid, 2
            while f"{base}-{n}".casefold() in used:
                n += 1
            rid = f"{base}-{n}"
        req["requirement_id"] = rid
        used.add(rid.casefold())
        cand = by_cand.get(req.get("candidate_id") or "", {})
        req["review"] = {"status": cand.get("review_status", "kept"), "item": req.get("candidate_id"),
                         "extracted_after_review": True}
        out.append(req)
    return out


def review_counts(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Open items per category, and how many are resolved (for the progress bar and badges)."""
    open_by = {c: 0 for c in CATEGORIES}
    resolved = 0
    for it in items:
        if it.get("resolution"):
            resolved += 1
        else:
            open_by[it["category"]] += 1
    return {"total": len(items), "resolved": resolved, "open": sum(open_by.values()), "open_by_category": open_by}
