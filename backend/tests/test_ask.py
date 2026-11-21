"""Ask: plain-language questions answered from the code graph, links and verdicts."""

import pytest
from fastapi.testclient import TestClient

from traceability.mapping import RepoGraph

from tracelight.api import create_app
from tracelight.api.ask import (
    Intent, _Context, answer_intent, callees_of, callers_of, doc_summary, llm_parse, parse_question, resolve_names,
)

from test_runner import env, make_orch, pytestmark as db_mark  # noqa: F401  (env fixture)


# ---------------------------------------------------------------------------
# Question parsing (rules)
# ---------------------------------------------------------------------------

IDS = ["FR-016", "FR-020", "Req-1/2"]


@pytest.mark.parametrize("question, intent, target", [
    ("which functions use can_borrow()?", "callers", "can_borrow"),
    ("Which all functions call `Member.can_borrow`", "callers", "Member.can_borrow"),
    ("who calls renew", "callers", "renew"),
    ("callers of checkout", "callers", "checkout"),
    ("where is calculate_fine used?", "callers", "calculate_fine"),
    ("what does checkout call?", "callees", "checkout"),
    ("functions called by LendingService.checkout", "callees", "LendingService.checkout"),
    ("what does Loan.renew do?", "describe", "Loan.renew"),
    ("explain checkout", "describe", "checkout"),
    ("which requirements does checkout implement?", "component_requirements", "checkout"),
    ("requirements linked to Loan.renew", "component_requirements", "Loan.renew"),
    ("which code implements FR-016?", "requirement_code", "FR-016"),
    ("fr-020", "requirement_code", "FR-020"),
    ("where is Req-1/2 implemented", "requirement_code", "Req-1/2"),
    ("where is renewing a loan implemented?", "requirement_code", "renewing a loan"),
    ("which code handles overdue fines", "requirement_code", "overdue fines"),
])
def test_rules(question, intent, target):
    got = parse_question(question, IDS)
    assert (got.intent, got.target) == (intent, target)
    assert got.parsed_by == "rules"


@pytest.mark.parametrize("question, statuses", [
    ("which requirements are not implemented?", ("not_supported_by_candidate", "not_found")),
    ("list partially implemented requirements", ("partially_supported",)),
    ("show me the requirements that are supported", ("supported",)),
    ("which features are missing", ("not_supported_by_candidate", "not_found")),
])
def test_status_questions(question, statuses):
    got = parse_question(question, IDS)
    assert got.intent == "requirements_by_status" and tuple(got.statuses) == statuses


def test_unrecognised_questions_are_left_to_the_llm():
    assert parse_question("tell me something interesting about the lending module", IDS) is None
    assert parse_question("", IDS) is None


class FakeLLM:
    def __init__(self, reply=None, fail=False):
        self.reply, self.fail, self.calls = reply, fail, 0

    def chat_json(self, system, user, schema):
        self.calls += 1
        if self.fail:
            raise RuntimeError("model down")
        assert schema["properties"]["intent"]["enum"][0] == "callers"
        return self.reply


def test_llm_parse_maps_status_and_cleans_target():
    got = llm_parse(FakeLLM({"intent": "callers", "target": "`renew()`", "status": "none"}), "q")
    assert (got.intent, got.target, got.parsed_by) == ("callers", "renew", "llm")
    got = llm_parse(FakeLLM({"intent": "requirements_by_status", "target": "", "status": "partial"}), "q")
    assert tuple(got.statuses) == ("partially_supported",)
    assert llm_parse(FakeLLM(fail=True), "q") is None
    assert llm_parse(FakeLLM({"intent": "nonsense", "target": "", "status": "none"}), "q") is None


# ---------------------------------------------------------------------------
# Graph questions on a real RepoGraph (no database)
# ---------------------------------------------------------------------------

LENDING = '''def checkout(self, member_id, isbn):
    member = self.members[member_id]
    if not member.can_borrow():
        raise PermissionError("no")
    loan = Loan(member, isbn)
    return loan'''
CAN_BORROW = '''def can_borrow(self):
    return self.fines == 0'''
RENEW = '''def renew(self):
    if not self.member.can_borrow():
        return False
    return True'''


def comp(pk, cid, ctype, path, a, b, src=""):
    return pk, {"component_id": cid, "component_type": ctype, "relative_path": path, "start_line": a,
                "end_line": b, "source_code": src, "containing_class": None, "has_vec": True}


def graph():
    comps = dict([
        comp(1, "lib.services.lending.LendingService", "class", "lib/services/lending.py", 1, 30),
        comp(2, "lib.services.lending.LendingService.checkout", "method", "lib/services/lending.py", 10, 15, LENDING),
        comp(3, "lib.models.member.Member.can_borrow", "method", "lib/models/member.py", 20, 21, CAN_BORROW),
        comp(4, "lib.models.loan.Loan", "class", "lib/models/loan.py", 1, 40),
        comp(5, "lib.models.loan.Loan.__init__", "method", "lib/models/loan.py", 2, 6),
        comp(6, "lib.models.loan.Loan.renew", "method", "lib/models/loan.py", 30, 33, RENEW),
    ])
    rels = [(1, 2, "contains"), (4, 5, "contains"), (4, 6, "contains"), (2, 4, "instantiates")]
    return RepoGraph(comps, rels, {})


def test_names_resolve_by_id_suffix_or_short_name():
    g = graph()
    assert resolve_names(g, "lib.models.loan.Loan.renew") == [6]
    assert resolve_names(g, "Loan.renew()") == [6]
    assert resolve_names(g, "`can_borrow`") == [3]
    assert resolve_names(g, "nothing_like_this") == []


def test_callers_come_from_source_call_sites_and_docagent_edges():
    g = graph()
    callers = callers_of(g, {3})
    assert set(callers) == {2, 6}                      # member.can_borrow() / self.member.can_borrow()
    assert callers[2]["lines"] == [12] and callers[2]["relations"] == ["calls Member.can_borrow"]
    assert set(callers_of(g, {4})) == {2}              # Loan(...) creates Loan


def test_callees():
    found = callees_of(graph(), 2)
    assert {3, 4} <= set(found)
    assert found[3]["relations"] == ["calls"]


def test_answers_are_built_from_stored_data():
    g = graph()
    rows = {"FR-016": {"title": "Check out a book", "verdict": {"status": "supported"}},
            "FR-020": {"title": "Renew a loan", "verdict": {"status": "partially_supported"}}}
    ctx = _Context(graph=g, rows=rows,
                   by_component={"lib.services.lending.LendingService.checkout": [{"requirement_id": "FR-016", "role": "direct"}]},
                   by_requirement={"FR-016": [{"component_id": "lib.services.lending.LendingService.checkout", "role": "direct",
                                               "path": "lib/services/lending.py", "start_line": 10, "end_line": 15}]})

    out = answer_intent(ctx, Intent("callers", "can_borrow"))
    assert out["answer"] == "2 components use can_borrow."
    assert [c["name"] for c in out["components"]] == ["Loan.renew", "LendingService.checkout"]
    checkout = out["components"][1]
    assert checkout["lines"] == [12] and checkout["requirements"][0]["requirement_id"] == "FR-016"
    assert "dynamic dispatch" in out["note"]

    assert answer_intent(ctx, Intent("callers", "missing_fn"))["answer"].startswith("No function, method or class named")
    assert answer_intent(ctx, Intent("component_requirements", "checkout"))["requirements"][0]["requirement_id"] == "FR-016"
    out = answer_intent(ctx, Intent("requirement_code", "FR-016"))
    assert out["answer"] == "FR-016 is implemented mainly by LendingService.checkout."
    out = answer_intent(ctx, Intent("requirements_by_status", statuses=("partially_supported",)))
    assert [r["requirement_id"] for r in out["requirements"]] == ["FR-020"]
    out = answer_intent(ctx, Intent("describe", "can_borrow"),
                        docstrings={"lib.models.member.Member.can_borrow": {"generated": "True when the member has no fines.\n\nReturns:\n  bool"}})
    assert out["answer"] == "True when the member has no fines." and out["matches"][0]["summary_kind"] == "generated"
    out = answer_intent(ctx, Intent("requirement_code", "renewing a loan"),
                        search=lambda text: {"requirements": [{"requirement_id": "FR-020"}]})
    assert out["requirements"][0]["requirement_id"] == "FR-020" and out["answer"].startswith("Closest requirement: FR-020")
    out = answer_intent(ctx, Intent("find", "loans", parsed_by="fallback"), search=lambda text: {"query": text})
    assert out["search"] == {"query": "loans"} and out["intent"] == "find"


def test_doc_summary():
    assert doc_summary("Renews a loan.\nArgs:\n  x: y") == "Renews a loan."
    assert doc_summary(None) == ""


# ---------------------------------------------------------------------------
# HTTP, on a real (placeholder-mode) run in the test database
# ---------------------------------------------------------------------------


def test_ask_endpoint(env):
    llm = FakeLLM({"intent": "requirements_by_status", "target": "", "status": "not_implemented"})
    orch = make_orch(env, ask_llm_factory=lambda settings: llm)
    with TestClient(create_app(orch, poll_seconds=0.05)) as api:
        run_id = orch.create_run(source_kind="folder", source_ref=str(env["repo"]), srs_path=str(env["srs"]))
        assert orch.execute(run_id, auto_approve=True) == "completed"

        r = api.get(f"/api/runs/{run_id}/ask", params={"q": "which code implements FR-002?"}).json()
        assert r["intent"] == "requirement_code" and r["parsed_by"] == "rules"
        assert r["requirements"][0]["requirement_id"] == "FR-002" and r["requirements"][0]["components"]

        r = api.get(f"/api/runs/{run_id}/ask", params={"q": "what does total do?"}).json()
        assert r["intent"] == "describe" and r["matches"][0]["name"] == "Cart.total"

        r = api.get(f"/api/runs/{run_id}/ask", params={"q": "which functions use add_item?"}).json()
        assert r["intent"] == "callers" and r["components"] == []
        assert r["answer"] == "Nothing in the indexed code calls or uses add_item."

        assert llm.calls == 0                            # rules handled everything so far
        r = api.get(f"/api/runs/{run_id}/ask", params={"q": "gimme the stuff nobody built"}).json()
        assert llm.calls == 1 and r["parsed_by"] == "llm" and r["intent"] == "requirements_by_status"
        assert [x["requirement_id"] for x in r["requirements"]] == ["FR-004"]

        llm.fail = True
        r = api.get(f"/api/runs/{run_id}/ask", params={"q": "cart things please"}).json()
        assert r["intent"] == "find" and r["parsed_by"] == "fallback" and "requirements" in r["search"]


test_ask_endpoint.pytestmark = db_mark     # needs the test database (skipped when unreachable)


def test_filler_words_are_never_names():
    assert parse_question("which requirements are not yet implemented?", IDS).intent == "requirements_by_status"
    assert parse_question("which requirements does checkout implement?", IDS).target == "checkout"
