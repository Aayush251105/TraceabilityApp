"""
FINAL TESTING V1 — step 1: gold workbooks -> GOLD_FORMAT v2 JSON, with validation.

    SRS_to_code_traceability/.venv/bin/python final_tests/v1/gold_v2.py

For each pair: reads datasets/Data/<pair>/<pair>_gold.xlsx (via the benchmark's
common/gold.py) and writes datasets/Data/<pair>/gold_standard_v2.json:

  schema_version "2.0", dataset, code_root, srs_file, commit_sha, line_numbering, label,
  requirements: [{requirement_id, title, text, type, status, sure, notes,
                  links: [{component_id, component_type, path, start_line, end_line,
                           anchor_text, relevance, sure, notes,
                           evidence: [{kind: "block", path, start_line, end_line, anchor_text}]}]}]
  excluded_requirements: [...same, not scored...]

relevance = the sheet's "role" column; component_type/path/lines = DocAgent's parser on
code/; link anchor_text = the def/class line; evidence = the "lines" column
("file.py:26-27", several separated by , or ;) with anchor_text = the first non-blank
line of the block. The golds are never edited; problems go to
final_tests/v1/results/gold_validation.json (+ a summary on stdout).

Checks (error unless noted):
  - every linked component exists in the DocAgent parse of code/; the components
    sheet matches the parse (warning);
  - evidence: file exists, path = the component's file, lines inside the file and
    inside the component's range; a decorator line directly above the component or a
    module-level constant/assignment the component uses -> warning;
  - status/links agree: implemented/partial need >= 1 primary link; not_implemented and
    excluded have no links (excluded with links -> warning); links to unknown
    requirement IDs; duplicate requirement IDs; unknown status / role values.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent.parent
DATA = WS / "datasets" / "Data"
sys.path.insert(0, str(WS / "TraceabilityApp" / "benchmark"))
from common.gold import convert  # noqa: E402

PAIRS = ["Books-Recommender-System", "ProClinic", "Travel-Agency-Automation-System", "Virtual-clinic"]
LABEL = "V1 - human-annotated gold"
STATUSES = {"implemented", "partial", "not_implemented", "cross_cutting", "excluded"}
ROLES = {"primary", "supporting"}
DOCAGENT_PY = WS / "DocAgent" / ".venv" / "bin" / "python"
PARSE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from dependency_analyzer.ast_parser import DependencyParser
c = DependencyParser(sys.argv[2]).parse_repository()
print(json.dumps({k: [v.component_type, v.relative_path, v.start_line, v.end_line] for k, v in c.items()}))
"""


def docagent_components(code: Path) -> dict:
    out = subprocess.run([str(DOCAGENT_PY), "-c", PARSE, str(WS / "DocAgent" / "src"), str(code)],
                         capture_output=True, text=True, check=True).stdout
    return {k: dict(zip(("type", "path", "start_line", "end_line"), v)) for k, v in json.loads(out).items()}


class Files:
    def __init__(self, root: Path):
        self.root, self.cache = root, {}

    def lines(self, rel: str):
        if rel not in self.cache:
            p = self.root / rel
            self.cache[rel] = p.read_text(encoding="utf-8", errors="replace").splitlines() if p.is_file() else None
        return self.cache[rel]


def parse_lines(spec: str):
    """'a.py:26-27, b.py:30' -> [(path, start, end)]; returns (blocks, bad_parts)."""
    blocks, bad = [], []
    for part in re.split(r"[;,\n]+", spec or ""):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(.+?\.py)\s*:\s*(\d+)(?:\s*[-–]\s*(\d+))?", part)
        if not m:
            bad.append(part)
            continue
        a = int(m.group(2)); b = int(m.group(3) or a)
        blocks.append((m.group(1).strip().replace("\\", "/"), min(a, b), max(a, b)))
    return blocks, bad


def def_line(lines, start, end):
    for i in range(start - 1, min(end, len(lines))):
        s = lines[i].strip()
        if s.startswith(("def ", "async def ", "class ")):
            return s
    return lines[start - 1].strip() if 0 < start <= len(lines) else ""


def outside_kind(lines, comp, a, b):
    """Why an evidence block outside the component range is acceptable (or None)."""
    blk = [lines[i - 1] for i in range(a, b + 1) if 0 < i <= len(lines)]
    # the part above the component is only its decorator lines (the rest may lie inside it)
    above = [lines[i - 1] for i in range(a, min(b, comp["start_line"] - 1) + 1) if 0 < i <= len(lines)]
    if a < comp["start_line"] and b <= comp["end_line"] and above and \
            all(l.strip().startswith("@") or not l.strip() for l in above):
        return "decorator"
    if all(re.match(r"^[A-Za-z_][\w.]*\s*(:[^=]+)?=", l) or not l.strip() or l.startswith((" ", "\t", ")", "]", "}"))
           for l in blk) and re.match(r"^[A-Za-z_]", blk[0] if blk else ""):
        return "module_constant"
    return None


def build(pair: str):
    wb = convert(DATA / pair / f"{pair}_gold.xlsx")
    code = DATA / pair / "code"
    parsed = docagent_components(code)
    files = Files(code)
    errors, warnings = [], []
    sheet = {c["component_id"]: c for c in wb["components"]}
    if set(sheet) != set(parsed):
        warnings.append({"check": "components_sheet_vs_parser", "only_in_sheet": sorted(set(sheet) - set(parsed)),
                         "only_in_parser": sorted(set(parsed) - set(sheet))})
    for cid in set(sheet) & set(parsed):
        s, p = sheet[cid], parsed[cid]
        if (s.get("start_line"), s.get("end_line")) != (p["start_line"], p["end_line"]):
            warnings.append({"check": "component_lines_differ", "component": cid,
                             "sheet": [s.get("start_line"), s.get("end_line")],
                             "parser": [p["start_line"], p["end_line"]]})

    reqs, ids = {}, Counter(r["requirement_id"] for r in wb["requirements"])
    for rid, n in ids.items():
        if n > 1:
            errors.append({"check": "duplicate_requirement_id", "requirement": rid, "count": n})
    for r in wb["requirements"]:
        status = (r.get("status") or "").strip()
        if status not in STATUSES:
            errors.append({"check": "unknown_status", "requirement": r["requirement_id"], "status": status})
        reqs.setdefault(r["requirement_id"], {
            "requirement_id": r["requirement_id"], "title": None, "text": r.get("text"), "type": None,
            "status": status, "sure": r.get("sure"), "notes": r.get("notes"), "links": []})

    for l in wb["links"]:
        rid, cid, role = l["requirement_id"], l.get("component"), (l.get("role") or "").strip()
        where = {"requirement": rid, "component": cid}
        if rid not in reqs:
            errors.append({"check": "link_to_unknown_requirement", **where}); continue
        if role not in ROLES:
            errors.append({"check": "unknown_role", "role": role, **where})
        comp = parsed.get(cid)
        if comp is None:
            errors.append({"check": "component_not_in_code", **where}); continue
        lines = files.lines(comp["path"]) or []
        link = {"component_id": cid, "component_type": comp["type"], "path": comp["path"],
                "start_line": comp["start_line"], "end_line": comp["end_line"],
                "anchor_text": def_line(lines, comp["start_line"], comp["end_line"]),
                "relevance": role, "sure": l.get("sure"), "notes": l.get("notes"), "evidence": []}
        blocks, bad = parse_lines(l.get("lines") or "")
        for part in bad:
            errors.append({"check": "unparseable_lines", "value": part, **where})
        for path, a, b in blocks:
            flines = files.lines(path)
            if flines is None:
                # bare file names: resolve against the component's file
                if Path(path).name == Path(comp["path"]).name:
                    path, flines = comp["path"], files.lines(comp["path"])
                else:
                    errors.append({"check": "evidence_file_missing", "path": path, **where}); continue
            if path != comp["path"]:
                errors.append({"check": "evidence_in_other_file", "path": path, "component_path": comp["path"],
                               **where})
            if b > len(flines):
                errors.append({"check": "evidence_beyond_eof", "lines": [a, b], "file_lines": len(flines), **where})
                continue
            block = [flines[i - 1] for i in range(a, b + 1)]
            anchor = next((x.strip() for x in block if x.strip()), "")
            if not anchor:
                errors.append({"check": "evidence_blank", "lines": [a, b], **where})
            if path == comp["path"] and not (comp["start_line"] <= a and b <= comp["end_line"]):
                kind = outside_kind(flines, comp, a, b)
                (warnings if kind else errors).append(
                    {"check": f"evidence_outside_component{'_' + kind if kind else ''}", "lines": [a, b],
                     "component_lines": [comp["start_line"], comp["end_line"]], "anchor_text": anchor, **where})
            link["evidence"].append({"kind": "block", "path": path, "start_line": a, "end_line": b,
                                     "anchor_text": anchor})
        if role == "primary" and not blocks:
            warnings.append({"check": "primary_link_without_lines", **where})
        reqs[rid]["links"].append(link)

    for r in reqs.values():
        prim = [x for x in r["links"] if x["relevance"] == "primary"]
        if r["status"] in ("implemented", "partial") and not prim:
            errors.append({"check": "implemented_without_primary_link", "requirement": r["requirement_id"],
                           "status": r["status"]})
        if r["status"] == "not_implemented" and r["links"]:
            errors.append({"check": "not_implemented_with_links", "requirement": r["requirement_id"],
                           "links": len(r["links"])})
        if r["status"] == "excluded" and r["links"]:
            warnings.append({"check": "excluded_with_links", "requirement": r["requirement_id"]})

    info = wb["repo_info"]
    gold = {
        "schema_version": "2.0", "label": LABEL, "dataset": pair, "code_root": "code",
        "srs_file": info.get("srs_file"), "repository_url": info.get("repository_url"),
        "commit_sha": info.get("commit_sha"),
        "line_numbering": "1-based, inclusive, original code before any docstring insertion",
        "annotation": "human-annotated (workbook repo_info still says DRAFT; reviewed by the annotators)",
        "source_workbook": f"{pair}_gold.xlsx", "guide_version": info.get("guide_version"),
        "requirements": [r for r in reqs.values() if r["status"] != "excluded"],
        "excluded_requirements": [r for r in reqs.values() if r["status"] == "excluded"],
    }
    return gold, errors, warnings, len(parsed)


def main() -> None:
    out_dir = HERE / "results"; out_dir.mkdir(parents=True, exist_ok=True)
    report = {"label": LABEL, "pairs": {}}
    for pair in PAIRS:
        gold, errors, warnings, n_comp = build(pair)
        (DATA / pair / "gold_standard_v2.json").write_text(json.dumps(gold, indent=2, ensure_ascii=False) + "\n",
                                                           encoding="utf-8")
        st = Counter(r["status"] for r in gold["requirements"])
        nl = sum(len(r["links"]) for r in gold["requirements"])
        report["pairs"][pair] = {"components_parsed": n_comp, "requirements": len(gold["requirements"]),
                                 "excluded": len(gold["excluded_requirements"]), "status": dict(st),
                                 "links": nl, "errors": errors, "warnings": warnings}
        print(f"{pair}: {len(gold['requirements'])} scored-set requirements {dict(st)}, "
              f"{len(gold['excluded_requirements'])} excluded, {nl} links, {n_comp} components; "
              f"{len(errors)} errors, {len(warnings)} warnings "
              f"{dict(Counter(e['check'] for e in errors))} {dict(Counter(w['check'] for w in warnings))}")
    (out_dir / "gold_validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                                  encoding="utf-8")


if __name__ == "__main__":
    main()
