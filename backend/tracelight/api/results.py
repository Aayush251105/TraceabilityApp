"""
Read model for the results pages (read-only queries over the traceability
tables plus the run's own files).

Effective verdict of a requirement
----------------------------------
1. the latest human override, unless it was cleared;
2. otherwise the latest verification — 'needs_review' when the model failed
   (the stored status is then insufficient_evidence, which would be misleading);
3. 'pending' when it has not been verified (the run is not that far).

Flags explain what a reader should know about a row: text edited or merged
at review, kept without review, the verifier saw incomplete text, no code
candidates, a model failure, low extraction confidence.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

from traceability.candidates import PIPELINE_VERSION as CANDIDATES_VERSION
from traceability.config import TraceabilityConfig
from traceability.mapping import PIPELINE_VERSION as MAPPING_VERSION
from traceability.schema import VERIFICATION_STATUSES
from traceability.verification.verifier import PIPELINE_VERSION as VERIFICATION_VERSION

VERDICTS = ("supported", "partially_supported", "not_supported_by_candidate", "not_found",
            "insufficient_evidence", "needs_review")
OVERRIDE_STATUSES = tuple(VERIFICATION_STATUSES) + ("needs_review", "cleared")
LIKELY_NOT_IMPLEMENTED = ("not_supported_by_candidate", "not_found")
INCOMPLETE_MARK = "[requirement text looks incomplete"
MODEL_FAILURE_MARK = "Model failure"


def _short(component_id: str) -> str:
    parts = (component_id or "").split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else component_id


class ResultsReader:
    def __init__(self, cfg: TraceabilityConfig, run: Dict[str, Any], overrides: Dict[str, Dict[str, Any]],
                 source_root: Optional[Path] = None) -> None:
        """source_root: the pristine source copy (its line numbers match the parsed components)."""
        self.cfg = cfg
        self.run = run
        self.overrides = overrides
        self.workdir = Path(run["workdir"])
        self._source_root = source_root
        self._conn = psycopg2.connect(cfg.build_dsn())
        self._reviewed: Optional[Dict[str, Dict[str, Any]]] = None

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ResultsReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _q(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Basic lookups
    # ------------------------------------------------------------------

    @property
    def ready(self) -> bool:
        return bool(self.run.get("document_id"))

    def document_pk(self) -> Optional[int]:
        if not self.run.get("document_id"):          # requirements not ingested yet
            return None
        rows = self._q(f"SELECT document_pk FROM {self.cfg.table_srs_documents} WHERE document_id = %s",
                       (self.run["document_id"],))
        return rows[0]["document_pk"] if rows else None

    def repo_pk(self) -> Optional[int]:
        if not self.run.get("repo_id"):              # code not fetched yet
            return None
        rows = self._q(f"SELECT repo_pk FROM {self.cfg.table_repositories} WHERE repo_id = %s",
                       (self.run["repo_id"],))
        return rows[0]["repo_pk"] if rows else None

    def reviewed(self) -> Dict[str, Dict[str, Any]]:
        """Review decisions per requirement, from the run's reviewed requirement file."""
        if self._reviewed is None:
            path = self.workdir / "reviewed_requirements.json"
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            self._reviewed = {r["requirement_id"]: r.get("review") or {} for r in data}
        return self._reviewed

    def requirements(self) -> List[Dict[str, Any]]:
        doc = self.document_pk()
        if doc is None:
            return []
        return self._q(f"SELECT * FROM {self.cfg.table_requirements} WHERE document_pk = %s AND is_current "
                       f"ORDER BY req_pk", (doc,))

    def verifications(self, req_pk: Optional[int] = None) -> List[Dict[str, Any]]:
        """Requirement-level verification rows, newest first."""
        doc = self.document_pk()
        where, params = "r.document_pk = %s AND v.link_pk IS NULL AND v.pipeline_version = %s", [doc, VERIFICATION_VERSION]
        if req_pk is not None:
            where += " AND v.req_pk = %s"
            params.append(req_pk)
        return self._q(f"SELECT v.*, r.requirement_id FROM {self.cfg.table_verifications} v "
                       f"JOIN {self.cfg.table_requirements} r ON r.req_pk = v.req_pk WHERE {where} "
                       f"ORDER BY v.created_at DESC, v.verification_pk DESC", params)

    def latest_verifications(self) -> Dict[str, Dict[str, Any]]:
        latest: Dict[str, Dict[str, Any]] = {}
        for v in self.verifications():
            latest.setdefault(v["requirement_id"], v)
        return latest

    def links(self, version: str, req_pk: Optional[int] = None) -> List[Dict[str, Any]]:
        doc = self.document_pk()
        where, params = "r.document_pk = %s AND l.pipeline_version = %s AND l.link_type = 'requirement_to_component'", \
            [doc, version]
        if req_pk is not None:
            where += " AND l.req_pk = %s"
            params.append(req_pk)
        return self._q(f"SELECT l.*, r.requirement_id, c.component_id, c.component_type, c.relative_path, "
                       f"c.start_line, c.end_line FROM {self.cfg.table_trace_links} l "
                       f"JOIN {self.cfg.table_requirements} r ON r.req_pk = l.req_pk "
                       f"JOIN {self.cfg.table_components} c ON c.comp_pk = l.comp_pk WHERE {where} "
                       f"ORDER BY l.req_pk, (l.evidence->>'rank')::int NULLS LAST, l.link_pk", params)

    # ------------------------------------------------------------------
    # Verdicts and flags
    # ------------------------------------------------------------------

    def verdict(self, requirement_id: str, verification: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        override = self.overrides.get(requirement_id)
        machine = None
        if verification:
            machine = verification["status"]
            if (verification.get("rationale") or "").startswith(MODEL_FAILURE_MARK):
                machine = "needs_review"
        if override and override["status"] != "cleared":
            return {"status": override["status"], "source": "human", "machine": machine,
                    "note": override.get("note")}
        return {"status": machine or "pending", "source": "verifier" if machine else None, "machine": machine}

    def flags(self, req: Dict[str, Any], verification: Optional[Dict[str, Any]], direct: int) -> List[Dict[str, str]]:
        out = []
        review = self.reviewed().get(req["requirement_id"], {})
        if review.get("status") == "unreviewed":
            out.append({"code": "unreviewed", "label": "Kept without review", "level": "warn"})
        if review.get("status") == "edited":
            out.append({"code": "edited", "label": "Text edited in review", "level": "info"})
        if review.get("merged_from"):
            out.append({"code": "merged", "label": f"Merged {len(review['merged_from'])} item(s) in review",
                        "level": "info"})
        if review.get("extracted_after_review"):
            # an uncertain candidate, a failed extraction or skipped content the user kept
            out.append({"code": "added_at_review", "label": "Added at review", "level": "info"})
        rationale = (verification or {}).get("rationale") or ""
        if INCOMPLETE_MARK in rationale:
            out.append({"code": "incomplete_text", "label": "Requirement text looks incomplete", "level": "warn"})
        if rationale.startswith(MODEL_FAILURE_MARK):
            out.append({"code": "model_error", "label": "Verifier model failed", "level": "error"})
        if verification is not None and direct == 0:
            out.append({"code": "no_candidates", "label": "No code candidates", "level": "info"})
        if req.get("review_required"):
            out.append({"code": "low_confidence", "label": "Low extraction confidence", "level": "warn"})
        return out

    def human_label(self, requirement_id: str, machine: Optional[str] = None) -> Optional[str]:
        """'Accepted' when a reviewer confirmed the verifier's verdict, 'Overridden' when they changed it."""
        override = self.overrides.get(requirement_id)
        if override and override["status"] != "cleared":
            return "Accepted" if machine is not None and override["status"] == machine else "Overridden"
        status = self.reviewed().get(requirement_id, {}).get("status")
        return {"edited": "Edited", "kept": "Kept", "unreviewed": None}.get(status or "", None)

    # ------------------------------------------------------------------
    # Results table and summary
    # ------------------------------------------------------------------

    def table(self) -> List[Dict[str, Any]]:
        latest = self.latest_verifications()
        counts: Dict[int, Dict[str, int]] = {}
        for l in self.links(MAPPING_VERSION):
            role = (l["evidence"] or {}).get("role") or "supporting"
            c = counts.setdefault(l["req_pk"], {"direct": 0, "supporting": 0})
            c[role if role in c else "supporting"] += 1
        rows = []
        for req in self.requirements():
            v = latest.get(req["requirement_id"])
            claims = (v or {}).get("claims") or []
            c = counts.get(req["req_pk"], {"direct": 0, "supporting": 0})
            verdict = self.verdict(req["requirement_id"], v)
            rows.append({
                "requirement_id": req["requirement_id"], "title": req["title"], "type": req["type"],
                "subtype": req["subtype"], "verdict": verdict,
                "claims": {"supported": sum(x.get("verdict") == "supported" for x in claims), "total": len(claims)},
                "links": {**c, "total": c["direct"] + c["supporting"]},
                "flags": self.flags(req, v, c["direct"]),
                "human": self.human_label(req["requirement_id"], verdict["machine"]),
                "location": req.get("source_location") or {},
                "verified_at": (v or {}).get("created_at"),
            })
        return rows

    def summary(self, rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        rows = rows if rows is not None else self.table()
        counts = {k: 0 for k in VERDICTS}
        pending = 0
        for r in rows:
            status = r["verdict"]["status"]
            if status in counts:
                counts[status] += 1
            else:
                pending += 1
        repo = self.repo_pk()
        components = traced = 0
        if repo is not None:
            components = self._q(f"SELECT count(*) AS n FROM {self.cfg.table_components} "
                                 f"WHERE repo_pk = %s AND is_current", (repo,))[0]["n"]
            traced = self._q(
                f"SELECT count(DISTINCT l.comp_pk) AS n FROM {self.cfg.table_trace_links} l "
                f"JOIN {self.cfg.table_components} c ON c.comp_pk = l.comp_pk "
                f"WHERE c.repo_pk = %s AND l.pipeline_version = %s AND l.status = 'supported'",
                (repo, MAPPING_VERSION))[0]["n"]
        return {"requirements": len(rows), "counts": counts, "pending": pending,
                "supported": counts["supported"],
                "likely_not_implemented": sum(counts[k] for k in LIKELY_NOT_IMPLEMENTED),
                "needs_attention": counts["partially_supported"] + counts["insufficient_evidence"] + counts["needs_review"],
                "overridden": sum(1 for r in rows if r["verdict"]["source"] == "human"),
                "unreviewed": sum(1 for r in rows if any(f["code"] == "unreviewed" for f in r["flags"])),
                "components": {"total": components, "cited_as_evidence": traced}}

    # ------------------------------------------------------------------
    # Requirement detail
    # ------------------------------------------------------------------

    def source_lines(self, rel_path: str, start: int, end: int) -> List[Dict[str, Any]]:
        path = self.safe_source_path(rel_path)
        if path is None or not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return [{"n": n, "text": lines[n - 1]} for n in range(max(1, start), min(len(lines), end) + 1)]

    def safe_source_path(self, rel_path: str) -> Optional[Path]:
        """The pristine file for a repository-relative path (never outside the source copy)."""
        root = self._source_root
        if root is None:
            return None
        rel = PurePosixPath(rel_path.replace("\\", "/"))
        if rel.is_absolute() or ".." in rel.parts:
            return None
        path = (root / Path(*rel.parts)).resolve()
        return path if root.resolve() in path.parents else None

    def detail(self, requirement_id: str) -> Optional[Dict[str, Any]]:
        reqs = [r for r in self.requirements() if r["requirement_id"] == requirement_id]
        if not reqs:
            return None
        req = reqs[0]
        history = self.verifications(req["req_pk"])
        latest = history[0] if history else None
        mapped = self.links(MAPPING_VERSION, req["req_pk"])
        candidates = self.links(CANDIDATES_VERSION, req["req_pk"])
        cand_by_comp = {l["comp_pk"]: l for l in candidates}
        pks = [l["comp_pk"] for l in mapped]
        docs = {}
        if pks:
            for d in self._q(f"SELECT comp_pk, docstring_kind, content FROM {self.cfg.table_docstrings} "
                             f"WHERE comp_pk = ANY(%s) AND is_current", (pks,)):
                if d["docstring_kind"] == "generated" or d["comp_pk"] not in docs:
                    docs[d["comp_pk"]] = {"kind": d["docstring_kind"], "content": d["content"]}

        components = []
        for l in mapped:
            ev, sc = l["evidence"] or {}, l["scores"] or {}
            cand = cand_by_comp.get(l["comp_pk"])
            channels = sc.get("channels") or ((cand or {}).get("scores") or {}).get("channels") or {}
            components.append({
                "component_id": l["component_id"], "name": _short(l["component_id"]), "type": l["component_type"],
                "role": ev.get("role"), "status": l["status"], "rank": ev.get("rank"), "reason": ev.get("reason"),
                "path": l["relative_path"], "start_line": l["start_line"], "end_line": l["end_line"],
                "docstring": docs.get(l["comp_pk"]),
                "scores": {"fused": sc.get("fused"), "channels": channels},
                "code": self.source_lines(l["relative_path"], l["start_line"], l["end_line"]),
            })

        edges: List[Dict[str, Any]] = []
        if pks:
            for r in self._q(f"SELECT a.component_id AS src, b.component_id AS tgt, r.rel_type "
                             f"FROM {self.cfg.table_relationships} r "
                             f"JOIN {self.cfg.table_components} a ON a.comp_pk = r.source_comp_pk "
                             f"JOIN {self.cfg.table_components} b ON b.comp_pk = r.target_comp_pk "
                             f"WHERE r.source_comp_pk = ANY(%s) AND r.target_comp_pk = ANY(%s) ORDER BY 1, 2, 3",
                             (pks, pks)):
                edges.append({"from": r["src"], "to": r["tgt"], "type": r["rel_type"], "source": "docagent"})
            for l in mapped:
                for e in (l["evidence"] or {}).get("edges", []):
                    if e.get("source") == "source" and e not in edges:
                        edges.append(e)

        claims = []
        for c in (latest or {}).get("claims") or []:
            claims.append({"claim_id": c.get("claim_id"), "text": c.get("text"), "verdict": c.get("verdict"),
                           "model_verdict": c.get("model_verdict"), "rationale": c.get("rationale"),
                           "source": c.get("source"),
                           "evidence": [{k: e.get(k) for k in ("component_id", "path", "start_line", "end_line",
                                                               "quote", "tag", "realigned_from")}
                                        for e in c.get("evidence") or []],
                           "rejected": [{"reference": r.get("reference"), "reason": r.get("reason")}
                                        for r in c.get("rejected_evidence") or []]})

        search = [{"component_id": l["component_id"], "name": _short(l["component_id"]),
                   "rank": (l["evidence"] or {}).get("rank"), "fused": (l["scores"] or {}).get("fused"),
                   "channels": (l["scores"] or {}).get("channels") or {},
                   "mapped": l["comp_pk"] in pks} for l in candidates]

        review = self.reviewed().get(requirement_id, {})
        rationale = (latest or {}).get("rationale") or ""
        return {
            "requirement": {
                "requirement_id": req["requirement_id"], "title": req["title"], "type": req["type"],
                "subtype": req["subtype"], "raw_text": req["raw_text"], "normalized_text": req["normalized_text"],
                "location": req.get("source_location") or {}, "sub_requirements": req.get("sub_requirements") or [],
                "conditions": req.get("conditions") or [], "error_conditions": req.get("error_conditions") or [],
                "review": review},
            "verdict": self.verdict(requirement_id, latest),
            "flags": self.flags(req, latest, sum(1 for c in components if c["role"] == "direct")),
            "verification": None if latest is None else {
                "status": latest["status"], "rationale": rationale, "model": latest.get("model"),
                "prompt_version": latest.get("prompt_version"), "created_at": latest.get("created_at"),
                "incomplete_text": INCOMPLETE_MARK in rationale},
            "claims": claims,
            "components": components,
            "edges": edges,
            "search": search,
            "history": [{"kind": "verification", "status": v["status"], "model": v.get("model"),
                         "claims": {"supported": sum(c.get("verdict") == "supported" for c in v.get("claims") or []),
                                    "total": len(v.get("claims") or [])},
                         "at": v["created_at"]} for v in history],
        }

    # ------------------------------------------------------------------
    # Code view
    # ------------------------------------------------------------------

    def code_view(self) -> Dict[str, Any]:
        repo = self.repo_pk()
        if repo is None:
            return {"files": [], "components": 0, "traced": 0}
        comps = self._q(f"SELECT comp_pk, component_id, component_type, relative_path, start_line, end_line "
                        f"FROM {self.cfg.table_components} WHERE repo_pk = %s AND is_current "
                        f"ORDER BY relative_path, start_line", (repo,))
        latest = self.latest_verifications() if self.document_pk() else {}
        verdicts = {rid: self.verdict(rid, v)["status"] for rid, v in latest.items()}
        mapped: Dict[int, List[Dict[str, Any]]] = {}
        best: Dict[int, Dict[str, Any]] = {}
        if self.document_pk():
            for l in self.links(MAPPING_VERSION):
                mapped.setdefault(l["comp_pk"], []).append({
                    "requirement_id": l["requirement_id"], "role": (l["evidence"] or {}).get("role"),
                    "link_status": l["status"], "verdict": verdicts.get(l["requirement_id"], "pending")})
            for l in self.links(CANDIDATES_VERSION):
                score = (l["scores"] or {}).get("fused") or 0
                if l["comp_pk"] not in best or score > best[l["comp_pk"]]["score"]:
                    best[l["comp_pk"]] = {"requirement_id": l["requirement_id"], "score": round(score, 4),
                                          "rank": (l["evidence"] or {}).get("rank")}
        files: Dict[str, Dict[str, Any]] = {}
        for c in comps:
            f = files.setdefault(c["relative_path"], {"path": c["relative_path"], "components": []})
            reqs = mapped.get(c["comp_pk"], [])
            f["components"].append({
                "component_id": c["component_id"], "name": _short(c["component_id"]), "type": c["component_type"],
                "start_line": c["start_line"], "end_line": c["end_line"], "requirements": reqs,
                "traced": bool(reqs), "best_candidate": None if reqs else best.get(c["comp_pk"])})
        for f in files.values():
            f["traced"] = sum(c["traced"] for c in f["components"])
            f["total"] = len(f["components"])
        return {"files": list(files.values()), "components": len(comps),
                "traced": sum(f["traced"] for f in files.values())}

    def component(self, component_id: str) -> Optional[Dict[str, Any]]:
        repo = self.repo_pk()
        rows = self._q(f"SELECT * FROM {self.cfg.table_components} WHERE repo_pk = %s AND component_id = %s "
                       f"AND is_current", (repo, component_id))
        if not rows:
            return None
        c = rows[0]
        docs = self._q(f"SELECT docstring_kind, content FROM {self.cfg.table_docstrings} "
                       f"WHERE comp_pk = %s AND is_current", (c["comp_pk"],))
        view = next((f for f in self.code_view()["files"] if f["path"] == c["relative_path"]), {"components": []})
        entry = next((x for x in view["components"] if x["component_id"] == component_id), {})
        return {"component_id": component_id, "name": _short(component_id), "type": c["component_type"],
                "path": c["relative_path"], "start_line": c["start_line"], "end_line": c["end_line"],
                "signature": c.get("signature"),
                "docstrings": {d["docstring_kind"]: d["content"] for d in docs},
                "requirements": entry.get("requirements", []), "best_candidate": entry.get("best_candidate"),
                "code": self.source_lines(c["relative_path"], c["start_line"], c["end_line"])}

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["requirement_id", "title", "type", "verdict", "verdict_source", "verifier_verdict",
                    "claims_supported", "claims_total", "direct_links", "supporting_links", "flags",
                    "override_note"])
        for r in self.table():
            v = r["verdict"]
            w.writerow([r["requirement_id"], r["title"], r["type"], v["status"], v["source"] or "",
                        v["machine"] or "", r["claims"]["supported"], r["claims"]["total"],
                        r["links"]["direct"], r["links"]["supporting"],
                        "; ".join(f["label"] for f in r["flags"]), v.get("note") or ""])
        return buf.getvalue()

    def export_json(self) -> Dict[str, Any]:
        rows = self.table()
        return {"run": {k: self.run.get(k) for k in ("run_id", "name", "document_id", "repo_id", "commit_sha",
                                                     "srs_filename", "created_at", "finished_at", "settings")},
                "summary": self.summary(rows),
                "requirements": [self.detail(r["requirement_id"]) for r in rows]}
