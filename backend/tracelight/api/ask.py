"""
Ask a run a question in plain language:

    "which functions use can_borrow()?"      -> callers
    "what does checkout call?"               -> callees
    "what does Loan.renew do?"               -> describe
    "which requirements does checkout cover" -> component_requirements
    "which code implements FR-016?"          -> requirement_code
    "where is renewing a loan implemented?"  -> requirement_code (found by search)
    "which requirements are not implemented" -> requirements_by_status
    anything else                            -> find (the normal hybrid search)

The question is turned into one of these intents with a target:

- first by rules (instant, no model needed);
- then, only if no rule matches, by a small LLM asked for JSON with a fixed
  schema.

The answer itself is never written by the LLM.  It comes from data the run
already stores:

- the code graph: DocAgent relationships plus call sites parsed from the
  source, i.e. the mapping agent's RepoGraph;
- the trace links and the verdicts;
- the docstrings.

So every name in an answer exists in the repository.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

INTENTS = ("callers", "callees", "describe", "component_requirements", "requirement_code",
           "requirements_by_status", "find")

# Words a user may use for a verdict -> the verdicts they mean.
STATUS_WORDS = (
    (r"not\s+(?:yet\s+)?implemented|unimplemented|missing|not\s+supported|not\s+done|not\s+met|failing|failed",
     ("not_supported_by_candidate", "not_found")),
    (r"partial(?:ly)?(?:\s+(?:implemented|supported|done))?|incomplete", ("partially_supported",)),
    (r"insufficient|unverified|unclear|uncertain", ("insufficient_evidence",)),
    (r"implemented|supported|verified|done|met|covered|passing|passed", ("supported",)),
)
STATUS_KEYS = {"not_implemented": ("not_supported_by_candidate", "not_found"),
               "partial": ("partially_supported",), "insufficient": ("insufficient_evidence",),
               "implemented": ("supported",)}

_NAME = r"[`'\"]?(?P<t>[A-Za-z_][\w.]*)[`'\"]?\s*(?:\(\s*\))?"
_CALL_VERBS = r"(?:calls?|calling|uses?|using|invokes?|invoking|references?|depends?\s+on|relies\s+on)"
_RULES = (
    ("callers", rf"\b(?:which|what|who|list|show|find|all)\b.*?\b{_CALL_VERBS}\s+(?:the\s+)?(?:function\s+|method\s+|class\s+)?{_NAME}"),
    ("callers", rf"\b(?:callers?|usages?|uses|references)\s+(?:of|to)\s+(?:the\s+)?{_NAME}"),
    ("callers", rf"\bwhere\s+(?:is|are)\s+{_NAME}\s+(?:called|used|invoked|referenced)"),
    ("callees", rf"\bwhat\s+(?:does|do|did)\s+{_NAME}\s+{_CALL_VERBS}"),
    ("callees", rf"\b(?:functions?|methods?|code)\s+(?:called|used|invoked)\s+(?:by|from|in)\s+{_NAME}"),
    ("component_requirements", rf"\b(?:which|what)\s+requirements?\b.*?\b(?:does|do|is|are)\s+{_NAME}\s+"
                               rf"(?:implement|cover|satisf|support|link|relat|trace|map)"),
    ("component_requirements", rf"\brequirements?\s+(?:for|of|linked\s+to|implemented\s+by|covered\s+by|mapped\s+to)\s+{_NAME}"),
)
_DESCRIBE = (rf"^\s*what\s+(?:does|do)\s+{_NAME}\s+do\b", rf"^\s*(?:explain|describe|what\s+is)\s+(?:the\s+)?(?:function\s+|method\s+|class\s+)?{_NAME}\s*\??\s*$")
_WHERE_IMPLEMENTED = (r"\bwhere\s+(?:is|are|do\s+we|does\s+it)\s+(?P<t>.+?)\s+(?:implemented|handled|done|coded)\b",
                      r"\b(?:which|what)\s+(?:code|functions?|methods?|classes|components?)\s+(?:implements?|handles?|does|do)\s+(?P<t>.+?)\s*\??$",
                      r"\bhow\s+(?:is|are)\s+(?P<t>.+?)\s+implemented\b")


# Words that can sit where a name goes ("which requirements are NOT implemented") but never are one.
_NOT_NAMES = {"not", "yet", "still", "partially", "fully", "being", "already", "the", "a", "an", "this", "that", "it",
              "they", "these", "those", "all", "any", "some", "currently", "really", "actually"}


@dataclass
class Intent:
    intent: str
    target: str = ""
    statuses: Sequence[str] = ()
    parsed_by: str = "rules"


def _clean_name(name: str) -> str:
    return re.sub(r"\(\s*\)$", "", name.strip().strip("`'\" .,?!:;")).strip()


def _statuses(text: str) -> Sequence[str]:
    low = text.lower()
    for pattern, statuses in STATUS_WORDS:
        if re.search(rf"\b(?:{pattern})\b", low):
            return statuses
    return ()


def parse_question(question: str, known_ids: Iterable[str] = ()) -> Optional[Intent]:
    """The intent of a question by rules, or None when no rule matches."""
    q = question.strip()
    if not q:
        return None
    low = q.lower()
    ids = {i.lower(): i for i in known_ids}

    # A requirement ID in the question: its code ("which code implements FR-016?", "FR-016").
    for token in re.findall(r"[A-Za-z][\w./-]*\d[\w./-]*", q):
        rid = ids.get(token.strip(".,?!:;").lower())
        if rid:
            return Intent("requirement_code", rid)

    if re.search(r"\brequirements?\b|\bfeatures?\b|\bwhat\s+is\s+(?:not\s+)?(?:implemented|missing)\b", low) \
            and not re.search(_CALL_VERBS, low):
        statuses = _statuses(low)
        about_component = any(
            m.group(1) not in _NOT_NAMES
            for m in re.finditer(r"\b(?:does|do|is|are)\s+[`'\"]?([a-z_][\w.]*)[`'\"]?\s*(?:\(\s*\))?\s+(?:implement|cover)", low))
        if statuses and not about_component:
            return Intent("requirements_by_status", statuses=statuses)

    for intent, pattern in _RULES:
        m = re.search(pattern, q, flags=re.IGNORECASE)
        if m and _clean_name(m.group("t")) and _clean_name(m.group("t")).lower() not in _NOT_NAMES:
            return Intent(intent, _clean_name(m.group("t")))

    for pattern in _DESCRIBE:
        m = re.search(pattern, q, flags=re.IGNORECASE)
        if m and _clean_name(m.group("t")):
            return Intent("describe", _clean_name(m.group("t")))

    for pattern in _WHERE_IMPLEMENTED:
        m = re.search(pattern, q, flags=re.IGNORECASE)
        if m and m.group("t").strip():
            return Intent("requirement_code", m.group("t").strip(" ?.!"))
    return None


# ---------------------------------------------------------------------------
# LLM parsing (only when no rule matches)
# ---------------------------------------------------------------------------

LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "target": {"type": "string"},
        "status": {"type": "string", "enum": ["none", *STATUS_KEYS]},
    },
    "required": ["intent", "target", "status"],
}

LLM_SYSTEM = """You turn a developer's question about a codebase and its software requirements into JSON.
Pick ONE intent:
- callers: which functions/methods/classes call or use a named function, method or class.
- callees: what a named function or method calls or uses.
- describe: what a named function, method or class does.
- component_requirements: which requirements a named function/method/class implements or is linked to.
- requirement_code: which code implements a requirement (target = requirement ID or a short feature phrase).
- requirements_by_status: list requirements by how well they are implemented (set status).
- find: anything else, a general search (target = the search words).
Rules: "target" is the name or phrase exactly as written in the question, without "()" (empty if none).
"status" is one of none, not_implemented, partial, insufficient, implemented (none unless intent is requirements_by_status).
Answer with the JSON object only."""


def llm_parse(llm: Any, question: str) -> Optional[Intent]:
    try:
        out = llm.chat_json(LLM_SYSTEM, f"Question: {question}", LLM_SCHEMA)
    except Exception:                                       # model down, timeout, bad JSON: fall back to search
        return None
    intent = out.get("intent")
    if intent not in INTENTS:
        return None
    status = STATUS_KEYS.get(str(out.get("status") or "none"), ())
    if intent == "requirements_by_status" and not status:
        status = _statuses(question) or ()
        if not status:
            return None
    return Intent(intent, _clean_name(str(out.get("target") or "")), status, parsed_by="llm")


# ---------------------------------------------------------------------------
# Graph questions (pure: take the loaded RepoGraph)
# ---------------------------------------------------------------------------


def resolve_names(graph: Any, name: str, limit: int = 10) -> List[int]:
    """Component pks matching a name the user typed: full ID, dotted suffix, or short name."""
    n = _clean_name(name)
    if not n:
        return []
    if n in graph.by_id:
        return [graph.by_id[n]]
    low = n.lower()
    suffix = [pk for pk, c in graph.components.items()
              if c["component_id"].lower().endswith("." + low)]
    if suffix:
        return sorted(suffix, key=lambda pk: graph.components[pk]["component_id"])[:limit]
    short = [pk for pk, c in graph.components.items() if c["component_id"].rsplit(".", 1)[-1].lower() == low]
    return sorted(short, key=lambda pk: graph.components[pk]["component_id"])[:limit]


_EDGE_WORDS = {"calls": "calls", "instantiates": "creates", "imports": "uses", "inherits": "inherits from",
               "contains": "contains"}


def callers_of(graph: Any, targets: Set[int]) -> Dict[int, Dict[str, Any]]:
    """{caller pk: {"relations": [...], "lines": [...]}} for components that call/create/use any target."""
    out: Dict[int, Dict[str, Any]] = {}
    names = {pk: graph.components[pk]["component_id"] for pk in targets}

    def add(pk: int, relation: str, line: Optional[int] = None) -> None:
        if pk in targets:
            return
        entry = out.setdefault(pk, {"relations": [], "lines": []})
        if relation not in entry["relations"]:
            entry["relations"].append(relation)
        if line is not None and line not in entry["lines"]:
            entry["lines"].append(line)

    for t in targets:
        for src, rtype in graph.in_edges.get(t, []):
            if rtype in ("calls", "instantiates", "imports", "inherits"):
                add(src, f"{_EDGE_WORDS[rtype]} {_short(names[t])}")
    for pk in graph.components:
        if pk in targets:
            continue
        for ref in graph.references(pk, set()):
            if ref.target in targets:
                add(pk, f"calls {_short(names[ref.target])}", ref.line)
    for entry in out.values():
        entry["lines"].sort()
    return out


def callees_of(graph: Any, pk: int) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for tgt, rtype in graph.out_edges.get(pk, []):
        if rtype in ("calls", "instantiates", "imports", "inherits"):
            out.setdefault(tgt, {"relations": [], "lines": []})["relations"].append(_EDGE_WORDS[rtype])
    for ref in graph.references(pk, set()):
        if ref.target == pk:
            continue
        entry = out.setdefault(ref.target, {"relations": [], "lines": []})
        if "calls" not in entry["relations"]:
            entry["relations"].append("calls")
        if ref.line not in entry["lines"]:
            entry["lines"].append(ref.line)
    for entry in out.values():
        entry["lines"].sort()
    return out


def _short(component_id: str) -> str:
    parts = component_id.split(".")
    return ".".join(parts[-2:]) if len(parts) > 1 else component_id


def doc_summary(content: Optional[str], limit: int = 400) -> str:
    """First paragraph of a docstring, without Args/Returns sections."""
    if not content:
        return ""
    kept: List[str] = []
    for line in content.strip().splitlines():
        if re.match(r"^\s*(args|arguments|parameters|params|returns?|yields?|raises|examples?|attributes|notes?)\s*:?\s*$",
                    line, re.IGNORECASE) or re.match(r"^\s*[-=]{3,}\s*$", line):
            break
        if not line.strip():
            if kept:
                break
            continue
        kept.append(line.strip())
    text = " ".join(kept)
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


# ---------------------------------------------------------------------------
# Answering a question for one run
# ---------------------------------------------------------------------------

NOT_FOUND_NOTE = ("Calls made through variables, callbacks or dynamic dispatch (e.g. getattr) can be missed; "
                  "the graph covers DocAgent's relationships and call sites read from the source.")


@dataclass
class _Context:
    graph: Any
    rows: Dict[str, Dict[str, Any]]
    by_component: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    by_requirement: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


def _component_entry(ctx: _Context, pk: int, relation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    c = ctx.graph.components[pk]
    cid = c["component_id"]
    reqs = [{**l, "title": (ctx.rows.get(l["requirement_id"]) or {}).get("title"),
             "verdict": ((ctx.rows.get(l["requirement_id"]) or {}).get("verdict") or {}).get("status", "pending")}
            for l in ctx.by_component.get(cid, [])]
    entry = {"component_id": cid, "name": _short(cid), "type": c["component_type"], "path": c["relative_path"],
             "start_line": c["start_line"], "end_line": c["end_line"], "requirements": reqs}
    if relation:
        entry["relation"] = ", ".join(relation["relations"])
        entry["lines"] = relation["lines"]
    return entry


def _requirement_entry(ctx: _Context, rid: str) -> Dict[str, Any]:
    row = ctx.rows.get(rid, {})
    comps = sorted(ctx.by_requirement.get(rid, []), key=lambda c: c["role"] != "direct")
    return {"requirement_id": rid, "title": row.get("title"), "verdict": (row.get("verdict") or {}).get("status", "pending"),
            "components": comps}


def answer_intent(ctx: _Context, intent: Intent, *, docstrings: Optional[Dict[str, Dict[str, str]]] = None,
                  search: Optional[Any] = None) -> Dict[str, Any]:
    """Answer an intent from the stored data. `search(text)` runs the hybrid search (for find / phrases)."""
    out: Dict[str, Any] = {"intent": intent.intent, "target": intent.target, "parsed_by": intent.parsed_by,
                           "components": [], "requirements": [], "matches": []}
    g = ctx.graph

    if intent.intent in ("callers", "callees", "describe", "component_requirements"):
        if g is None:
            out["answer"] = "The code of this run is not indexed yet."
            return out
        pks = resolve_names(g, intent.target)
        out["matches"] = [_component_entry(ctx, pk) for pk in pks]
        if not pks:
            out["answer"] = f"No function, method or class named “{intent.target}” was found in this repository."
            return out
        label = intent.target if len(pks) == 1 else f"{intent.target} ({len(pks)} components with this name)"

        if intent.intent == "callers":
            found = callers_of(g, set(pks))
            out["components"] = sorted((_component_entry(ctx, pk, rel) for pk, rel in found.items()),
                                       key=lambda e: (e["path"], e["start_line"]))
            n = len(out["components"])
            out["answer"] = (f"{n} component{'s' if n != 1 else ''} use{'s' if n == 1 else ''} {label}."
                             if n else f"Nothing in the indexed code calls or uses {label}.")
            out["note"] = NOT_FOUND_NOTE
        elif intent.intent == "callees":
            found: Dict[int, Dict[str, Any]] = {}
            for pk in pks:
                for tgt, rel in callees_of(g, pk).items():
                    e = found.setdefault(tgt, {"relations": [], "lines": []})
                    e["relations"] += [r for r in rel["relations"] if r not in e["relations"]]
                    e["lines"] = sorted(set(e["lines"]) | set(rel["lines"]))
            out["components"] = sorted((_component_entry(ctx, pk, rel) for pk, rel in found.items()),
                                       key=lambda e: (e["path"], e["start_line"]))
            n = len(out["components"])
            out["answer"] = (f"{label} uses {n} other component{'s' if n != 1 else ''} of this repository."
                             if n else f"{label} does not call any other component of this repository "
                                       f"(calls to libraries are not listed).")
            out["note"] = NOT_FOUND_NOTE
        elif intent.intent == "describe":
            for m in out["matches"]:
                docs = (docstrings or {}).get(m["component_id"], {})
                text = docs.get("generated") or docs.get("original") or next(iter(docs.values()), "")
                m["summary"] = doc_summary(text)
                m["summary_kind"] = "generated" if docs.get("generated") else ("existing" if text else None)
            first = out["matches"][0]
            out["answer"] = first.get("summary") or f"{first['name']} has no description; open it to read the code."
        else:  # component_requirements
            seen: Dict[str, Dict[str, Any]] = {}
            for m in out["matches"]:
                for r in m["requirements"]:
                    seen.setdefault(r["requirement_id"], _requirement_entry(ctx, r["requirement_id"]))
            out["requirements"] = list(seen.values())
            n = len(out["requirements"])
            out["answer"] = (f"{label} is linked to {n} requirement{'s' if n != 1 else ''}."
                             if n else f"{label} is not linked to any requirement in this run.")
        return out

    if intent.intent == "requirement_code":
        rid = intent.target if intent.target in ctx.rows else None
        if rid is None and search is not None:
            hits = search(intent.target)
            for h in hits.get("requirements", [])[:3]:
                out["requirements"].append(_requirement_entry(ctx, h["requirement_id"]))
            if not out["requirements"]:
                out["answer"] = f"No requirement about “{intent.target}” was found."
                return out
            top = out["requirements"][0]
            out["answer"] = (f"Closest requirement: {top['requirement_id']} {top.get('title') or ''}. "
                             f"{len(top['components'])} linked component{'s' if len(top['components']) != 1 else ''}.").strip()
            return out
        if rid is None:
            out["answer"] = f"Unknown requirement “{intent.target}”."
            return out
        entry = _requirement_entry(ctx, rid)
        out["requirements"] = [entry]
        direct = [c for c in entry["components"] if c["role"] == "direct"]
        out["answer"] = (f"{rid} is implemented mainly by {', '.join(_short(c['component_id']) for c in direct)}."
                         if direct else f"No code is linked to {rid}.")
        return out

    if intent.intent == "requirements_by_status":
        wanted = set(intent.statuses)
        rids = [rid for rid, r in ctx.rows.items() if (r.get("verdict") or {}).get("status") in wanted]
        out["requirements"] = [_requirement_entry(ctx, rid) for rid in rids]
        out["statuses"] = list(intent.statuses)
        n = len(rids)
        out["answer"] = f"{n} requirement{'s' if n != 1 else ''} match{'es' if n == 1 else ''}."
        return out

    # find
    out["intent"] = "find"
    out["search"] = search(intent.target) if search is not None else None
    out["answer"] = "No specific question type was recognised, so these are the search results."
    return out


def ask_run(reader: Any, embedder: Any, question: str, *, llm: Any = None, limit: int = 10) -> Dict[str, Any]:
    """Answer a question about one run (see module docstring)."""
    from traceability.mapping import PIPELINE_VERSION as MAPPING_VERSION, RepoGraph
    from traceability.store import Store

    from .search import search_run

    q = (question or "").strip()
    if not q:
        return {"question": "", "intent": "empty", "answer": "", "components": [], "requirements": [], "matches": []}

    rows = {r["requirement_id"]: r for r in reader.table()} if reader.document_pk() is not None else {}
    intent = parse_question(q, rows.keys())
    if intent is None and llm is not None:
        intent = llm_parse(llm, q)
    if intent is None:
        intent = Intent("find", q, parsed_by="fallback")

    graph = None
    repo_pk = reader.repo_pk()
    if repo_pk is not None and intent.intent in ("callers", "callees", "describe", "component_requirements"):
        with Store(reader.cfg) as store:
            graph = RepoGraph.load(store, repo_pk)

    ctx = _Context(graph=graph, rows=rows)
    if rows:
        for link in reader.links(MAPPING_VERSION):
            role = (link["evidence"] or {}).get("role")
            ctx.by_component.setdefault(link["component_id"], []).append(
                {"requirement_id": link["requirement_id"], "role": role})
            ctx.by_requirement.setdefault(link["requirement_id"], []).append(
                {"component_id": link["component_id"], "role": role, "path": link["relative_path"],
                 "start_line": link["start_line"], "end_line": link["end_line"]})

    docstrings = None
    if intent.intent == "describe" and graph is not None:
        docstrings = {}
        for pk in resolve_names(graph, intent.target):
            comp = reader.component(graph.components[pk]["component_id"])
            if comp:
                docstrings[comp["component_id"]] = comp.get("docstrings") or {}

    result = answer_intent(ctx, intent, docstrings=docstrings,
                           search=lambda text: search_run(reader, embedder, text, limit=limit))
    result["question"] = q
    return result
