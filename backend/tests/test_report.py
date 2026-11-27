"""The traceability report renderer (pure function, no database)."""

from datetime import datetime

from tracelight.api.report import codebase_label, first_sentence, render_report


def detail(rid, status, *, title="T", claims=(), components=(), source="verifier", note=None, rationale="All good."):
    return {
        "requirement": {"requirement_id": rid, "title": title, "raw_text": f"The system shall do {rid}.",
                        "sub_requirements": [], "conditions": [], "error_conditions": []},
        "verdict": {"status": status, "source": source, "machine": "not_supported_by_candidate", "note": note},
        "verification": {"rationale": rationale, "model": "qwen2.5-coder:7b", "prompt_version": "verify-v2.3"},
        "claims": list(claims),
        "components": list(components),
    }


CLAIM_OK = {"text": "Renews a loan.", "verdict": "supported", "rationale": "Line 31 extends the due date.",
            "evidence": [{"component_id": "lib.loan.Loan.renew", "path": "lib/loan.py", "start_line": 30,
                          "end_line": 31, "quote": "self.due += timedelta(days=14)"}]}
CLAIM_BAD = {"text": "Refuses a third renewal.", "verdict": "not_supported",
             "rationale": "No check on the renewal count. The method always renews.", "evidence": []}
RENEW = {"component_id": "lib.loan.Loan.renew", "role": "direct", "path": "lib/loan.py", "start_line": 28, "end_line": 33}
LOAN = {"component_id": "lib.loan.Loan", "role": "supporting", "path": "lib/loan.py", "start_line": 1, "end_line": 40}


def data(reqs, **run):
    return {"run": {"run_id": 6, "name": "Library", "srs_filename": "SRS.docx", "source_kind": "folder",
                    "source_ref": "C:\\Users\\someone\\code\\library_system", "commit_sha": None,
                    "created_at": "2026-11-20T10:00:00", "finished_at": "2026-11-20T11:25:00",
                    "settings": {"models": {"verifier": "qwen2.5-coder:7b", "docagent": "yi-coder:9b"}}, **run},
            "summary": {"components": {"total": 41, "cited_as_evidence": 20}, "overridden": 1},
            "requirements": reqs,
            "code": {"files": [{"path": "lib/loan.py", "total": 4, "traced": 2}, {"path": "lib/empty.py", "total": 0, "traced": 0}],
                     "components": 4, "traced": 2},
            "generated_at": datetime(2026, 11, 27, 9, 30)}


def test_report_sections_summary_and_details():
    html = render_report(data([
        detail("FR-001", "supported", title="Renew a loan", claims=[CLAIM_OK], components=[RENEW, LOAN]),
        detail("FR-002", "partially_supported", claims=[CLAIM_OK, CLAIM_BAD], components=[RENEW]),
        detail("FR-003", "not_found", rationale="The mapping stage proposed no code for this requirement."),
        detail("FR-004", "supported", source="human", note="Checked by hand"),
    ]))
    assert "<title>Traceability report — Library</title>" in html
    assert "Of the 4 requirements, 2 (50%) are supported by the code, 1 (25%) are partially supported and 1 (25%)" in html
    assert "20 of 41 functions and classes (49%)" in html
    # at a glance: claims column and direct code only
    assert "<td class='num'>1/2</td>" in html and "<code>Loan.renew</code>" in html
    # needs attention: the partial one explains its failing claim; not_found has its own reason
    assert "“Refuses a third renewal.”: No check on the renewal count." in html
    assert "No code was found that matches this requirement." in html
    # details: quoted, escaped evidence; reviewer verdict and note
    assert "lib/loan.py:30–31" in html and "self.due += timedelta(days=14)" in html
    assert "Verdict set by a reviewer" in html and "Checked by hand" in html
    # coverage skips files without components; models listed
    assert "lib/empty.py" not in html and "<code>yi-coder:9b</code>" in html
    for n in range(1, 7):
        assert f"<h2>{n}. " in html


def test_report_escapes_everything_and_hides_local_paths():
    evil = detail("FR-9", "not_supported_by_candidate", title="<script>alert(1)</script>",
                  claims=[{**CLAIM_BAD, "text": "<b>x</b>"}])
    html = render_report(data([evil]))
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "<b>x</b>" not in html
    assert "C:\\Users" not in html and "library_system (local folder)" in html


def test_all_supported_needs_no_attention():
    html = render_report(data([detail("FR-001", "supported", claims=[CLAIM_OK], components=[RENEW])]))
    assert "Nothing needs attention." in html


def test_helpers():
    assert codebase_label({"source_kind": "git", "source_ref": "https://github.com/o/r", "git_ref": "main",
                           "commit_sha": "0123456789abcdef"}) == "https://github.com/o/r @ main (commit 0123456789)"
    assert codebase_label({"source_kind": "zip", "source_ref": "/data/uploads/code.zip"}) == "code.zip (ZIP upload)"
    assert first_sentence("One. Two.") == "One."
    assert first_sentence("x" * 300, 50).endswith("…")
