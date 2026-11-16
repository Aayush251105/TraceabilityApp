"""
Objective (no-LLM) metrics for the SRS Agent extractor — the counterpart of
DocAgent's AST completeness.

The pipeline, not the model, sets requirement_id and raw_text, so the model's
contribution is the structured fields. Measured per model over the same
retained candidates:

  success        extracted / candidates (schema-valid within 3 attempts)
  field fill     share of core fields that are non-empty
                 (title, normalized_text, actor, actions, entities, domain_terms, retrieval_text)
  grounding      share of content words in the descriptive fields that occur in
                 raw_text (an invention proxy; domain_terms/synonyms excluded,
                 they are meant to add words)
  values kept    share of numbers in raw_text that survive into the structured fields
  list items     share of "- " list items in raw_text covered by sub_requirements
  retrieval MRR  the real query builder (traceability texts.requirement_text) run
                 over the pair's code components; MRR of the gold PRIMARY components.
                 Two retrievers: BM25 and dense MiniLM (the pipeline's embedder);
                 a failed extraction scores 0. Mean of both = "Retr. MRR".
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from common.codeindex import BM25, code_tokens, load_components
from common.config import WORKSPACE, ws_path
from common.textmatch import content_tokens, coverage, numbers

CORE = ("title", "normalized_text", "actor", "actions", "entities", "domain_terms", "retrieval_text")
DESCRIPTIVE = ("normalized_text", "actor", "actions", "entities", "inputs", "outputs", "preconditions",
               "postconditions", "conditions", "constraints", "error_conditions", "sub_requirements")
VALUE_FIELDS = ("normalized_text", "sub_requirements", "constraints", "conditions", "error_conditions",
                "preconditions", "postconditions", "inputs", "outputs")
MATCH = 0.80


def _texts_module():
    spec = importlib.util.spec_from_file_location("tl_texts", WORKSPACE / "SRS_to_code_traceability" / "texts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _flat(req: Dict[str, Any], fields) -> str:
    out = []
    for f in fields:
        v = req.get(f)
        out.extend(v if isinstance(v, list) else [v or ""])
    return "\n".join(str(x) for x in out)


def _stem(t: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def _filled(v) -> bool:
    return bool([x for x in v if str(x).strip()]) if isinstance(v, list) else bool(str(v or "").strip())


def _section_free(text: str) -> str:
    return re.sub(r"(?m)^\s*\d+(?:\.\d+)+\s", " ", text or "")


def per_requirement(req: Dict[str, Any]) -> Dict[str, Optional[float]]:
    raw = req.get("raw_text") or ""
    fill = sum(_filled(req.get(f)) for f in CORE) / len(CORE)
    raw_stems = {_stem(t) for t in content_tokens(raw)}
    desc = [_stem(t) for t in content_tokens(_flat(req, DESCRIPTIVE))]
    grounding = (sum(t in raw_stems for t in desc) / len(desc)) if desc else None
    want = set(numbers(_section_free(raw)))
    want -= set(numbers(req.get("requirement_id") or ""))
    have = set(numbers(_flat(req, VALUE_FIELDS)))
    values = (len(want & have) / len(want)) if want else None
    items = [ln.strip()[2:] for ln in raw.splitlines() if ln.strip().startswith("- ")]
    subs = "\n".join(req.get("sub_requirements") or [])
    lists = (sum(coverage(i, subs) >= MATCH for i in items) / len(items)) if items else None
    return {"field_fill": fill, "grounding": grounding, "values_kept": values, "list_items": lists}


# ── retrieval proxy ──────────────────────────────────────────────────────────

class Retriever:
    """BM25 + MiniLM over one pair's components; ranks are 1-based."""

    def __init__(self, comps: List[Dict[str, Any]], embedder=None):
        self.ids = [c["component_id"] for c in comps]
        self.bm25 = BM25([code_tokens(c["text"]) for c in comps])
        self.embedder = embedder
        self.emb = embedder.encode([c["text"][:2000] for c in comps], normalize_embeddings=True) if embedder else None

    def rr(self, query: str, relevant: set) -> Dict[str, float]:
        out = {}
        s = self.bm25.scores(code_tokens(query))
        out["bm25"] = _rr(s, self.ids, relevant)
        if self.embedder is not None:
            q = self.embedder.encode([query], normalize_embeddings=True)[0]
            out["dense"] = _rr([float(v @ q) for v in self.emb], self.ids, relevant)
        return out


def _rr(scores, ids, relevant) -> float:
    order = sorted(range(len(ids)), key=lambda i: -scores[i])
    for rank, i in enumerate(order, 1):
        if ids[i] in relevant:
            return 1.0 / rank
    return 0.0


def best_gold(raw: str, gold_reqs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best, score = None, 0.0
    for g in gold_reqs:
        s = max(coverage(g["text"] or "", raw), coverage(raw, g["text"] or ""))
        if s > score:
            best, score = g, s
    return best if score >= MATCH else None


def load_embedder():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    except Exception as exc:                       # dense part is optional
        print(f"  (dense retrieval skipped: {exc})")
        return None


# ── driver ───────────────────────────────────────────────────────────────────

def evaluate(cfg, gens: Dict[str, Dict[str, Any]], out_path: Path) -> Dict[str, Any]:
    texts = _texts_module()
    embedder = load_embedder()
    results: Dict[str, Any] = {}
    agg = {m: {"candidates": 0, "extracted": 0, "seconds": g["seconds"], "per_req": [], "rr_bm25": [],
               "rr_dense": []} for m, g in gens.items()}
    for pair in cfg["pairs"]:
        gold = json.loads((ws_path(cfg["paths"]["gold_json"]) / f"{pair['id']}.json").read_text(encoding="utf-8"))
        primary: Dict[str, set] = {}
        for l in gold["links"]:
            if l["role"] == "primary":
                primary.setdefault(l["requirement_id"], set()).add(l["component"])
        retr = Retriever(load_components(cfg, pair["id"], gold), embedder)
        # Retrieval targets: retained candidates (same for every model) that match a gold
        # requirement with primary links. Keyed by candidate_id.
        targets = {}
        for m, g in gens.items():
            for r in g["pairs"][pair["id"]]["requirements"]:
                gm = best_gold(r["raw_text"], gold["requirements"])
                if gm and gm["requirement_id"] in primary:
                    targets[r["candidate_id"]] = primary[gm["requirement_id"]]
        for m, g in gens.items():
            pg = g["pairs"][pair["id"]]
            agg[m]["candidates"] += pg["candidates"]
            agg[m]["extracted"] += len(pg["requirements"])
            by_cid = {r["candidate_id"]: r for r in pg["requirements"]}
            for r in pg["requirements"]:
                agg[m]["per_req"].append(per_requirement(r))
            for cid, rel in targets.items():
                r = by_cid.get(cid)
                if r is None:
                    agg[m]["rr_bm25"].append(0.0)
                    agg[m]["rr_dense"].append(0.0)
                    continue
                rr = retr.rr(texts.requirement_text(r), rel)
                agg[m]["rr_bm25"].append(rr["bm25"])
                if "dense" in rr:
                    agg[m]["rr_dense"].append(rr["dense"])
    for m, a in agg.items():
        def mean(key):
            vals = [x[key] for x in a["per_req"] if x[key] is not None]
            return sum(vals) / len(vals) if vals else None
        bm = sum(a["rr_bm25"]) / len(a["rr_bm25"]) if a["rr_bm25"] else None
        de = sum(a["rr_dense"]) / len(a["rr_dense"]) if a["rr_dense"] else None
        results[m] = {
            "candidates": a["candidates"], "extracted": a["extracted"],
            "success": a["extracted"] / a["candidates"] if a["candidates"] else 0.0,
            "seconds": a["seconds"], "field_fill": mean("field_fill"), "grounding": mean("grounding"),
            "values_kept": mean("values_kept"), "list_items": mean("list_items"),
            "mrr_bm25": bm, "mrr_dense": de,
            "mrr": (bm + de) / 2 if bm is not None and de is not None else bm,
            "n_retrieval_targets": len(a["rr_bm25"]),
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results
