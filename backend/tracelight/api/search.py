"""
Search a finished (or partly finished) run by keyword or sentence:
"which requirement is about renewing a loan, and which code does it?".

Uses the same hybrid retrieval as the search agent (keyword + semantic,
fused), scoped to the run's SRS document and repository, and joins the
run's results:

- requirements that match, with their verdict and the code mapped to them;
- code components that match, with the requirements they are linked to.

A requirement ID ("FR-016") is looked up directly.
"""

from __future__ import annotations

from typing import Any, Dict, List

from traceability.mapping import PIPELINE_VERSION as MAPPING_VERSION
from traceability.query import QueryResolver, detect_mode
from traceability.retrieval import Retriever
from traceability.store import Store

from .results import ResultsReader


def _channels(hit) -> Dict[str, Any]:
    """Which kinds of evidence matched: keyword and/or meaning, on code, docstring or requirement text."""
    out = {"keyword": False, "semantic": False}
    for name in hit.channels:
        if name.endswith("_lexical"):
            out["keyword"] = True
        elif name.endswith("_vector"):
            out["semantic"] = True
    out["via_docstring"] = any(name.startswith("docstring_") for name in hit.channels)
    return out


def search_run(reader: ResultsReader, embedder: Any, q: str, *, limit: int = 10) -> Dict[str, Any]:
    run = reader.run
    text = (q or "").strip()
    if not text:
        return {"query": "", "mode": "empty", "requirements": [], "components": []}

    with Store(reader.cfg) as store:
        resolver = QueryResolver(store)
        document_id = run.get("document_id") if reader.document_pk() is not None else None
        repo_id = run.get("repo_id") if reader.repo_pk() is not None else None
        mode = "id" if detect_mode(text) == "id" else "adhoc"
        query = resolver.resolve(text, mode=mode, document_id=document_id, repo_id=repo_id)
        exact = query.requirement["requirement_id"] if mode == "id" and query.status == "ok" and query.requirement else None
        if mode == "id" and query.status != "ok":              # an ID-like word that is not an ID here
            mode = "adhoc"
            query = resolver.resolve(text, mode="adhoc", document_id=document_id, repo_id=repo_id)
        entities = tuple(e for e, ok in (("requirement", document_id), ("docstring", repo_id), ("component", repo_id)) if ok)
        response = Retriever(store, embedder).search(query, method="hybrid", entities=entities, top_k=limit) \
            if entities and query.status == "ok" else None

    rows = {r["requirement_id"]: r for r in reader.table()} if document_id else {}
    mapped: Dict[str, List[Dict[str, Any]]] = {}
    by_component: Dict[str, List[Dict[str, Any]]] = {}
    if document_id:
        for link in reader.links(MAPPING_VERSION):
            ev = link["evidence"] or {}
            entry = {"component_id": link["component_id"], "role": ev.get("role"), "path": link["relative_path"],
                     "start_line": link["start_line"], "end_line": link["end_line"]}
            mapped.setdefault(link["requirement_id"], []).append(entry)
            by_component.setdefault(link["component_id"], []).append(
                {"requirement_id": link["requirement_id"], "role": ev.get("role")})

    def requirement_entry(rid: str, score: float | None, match: Dict[str, Any]) -> Dict[str, Any]:
        row = rows.get(rid, {})
        comps = sorted(mapped.get(rid, []), key=lambda c: c["role"] != "direct")
        return {"requirement_id": rid, "title": row.get("title"), "type": row.get("type"),
                "verdict": (row.get("verdict") or {}).get("status", "pending"), "score": score, "match": match,
                "components": comps}

    requirements: List[Dict[str, Any]] = []
    if exact:
        requirements.append(requirement_entry(exact, None, {"exact_id": True}))
    if response is not None:
        for hit in response.results.get("requirement", []):
            if hit.external_id != exact:
                requirements.append(requirement_entry(hit.external_id, round(hit.score, 6), _channels(hit)))

    components: List[Dict[str, Any]] = []
    if response is not None:
        verdicts = {rid: (r.get("verdict") or {}).get("status", "pending") for rid, r in rows.items()}
        for hit in response.components:
            d = hit.data
            linked = [{**l, "title": (rows.get(l["requirement_id"]) or {}).get("title"),
                       "verdict": verdicts.get(l["requirement_id"], "pending")}
                      for l in by_component.get(hit.external_id, [])]
            components.append({"component_id": hit.external_id, "type": d.get("component_type"), "path": d.get("path"),
                               "start_line": d.get("start_line"), "end_line": d.get("end_line"),
                               "score": round(hit.score, 6), "match": _channels(hit), "requirements": linked})

    return {"query": text, "mode": "id" if exact else "text", "requirements": requirements, "components": components,
            "scope": {"requirements": bool(document_id), "code": bool(repo_id)}}
