"""
Objective (no-LLM) verifier metrics against the expected verdicts of the cases.

Classes: supported / partially_supported / not_supported_by_candidate.
`insufficient_evidence` (the verifier abstaining or failing) is always wrong,
and its rate is reported separately.

  exact accuracy     verdict == expected
  macro-F1           mean F1 over the 3 expected classes
  support accuracy   binary: (supported|partial) vs not — "is this the right code?"
  false-support rate negative cases (distractor/absent) judged supported or partial
  implemented recall gold `implemented` cases judged supported or partial (RCRR in the over-correction paper)
  partial recall     gold `partial` cases judged supported or partial
  citation validity  valid / (valid + rejected) evidence references over all claims
  model failures     cases where the LLM call failed after retries
"""

from __future__ import annotations

from typing import Any, Dict, List

CLASSES = ("supported", "partially_supported", "not_supported_by_candidate")
POSITIVE = {"supported", "partially_supported"}


def evaluate(cases: List[Dict[str, Any]], gen: Dict[str, Any]) -> Dict[str, Any]:
    res = gen["cases"]
    rows = [(c, res[c["case_id"]]) for c in cases if c["case_id"] in res]
    n = len(rows)
    exact = sum(r["status"] == c["expected"] for c, r in rows)
    binary = sum((r["status"] in POSITIVE) == (c["expected"] in POSITIVE) for c, r in rows)
    f1s = []
    for k in CLASSES:
        tp = sum(r["status"] == k and c["expected"] == k for c, r in rows)
        fp = sum(r["status"] == k and c["expected"] != k for c, r in rows)
        fn = sum(r["status"] != k and c["expected"] == k for c, r in rows)
        p = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * p * rc / (p + rc) if p + rc else 0.0)
    neg = [(c, r) for c, r in rows if c["expected"] == "not_supported_by_candidate"]
    impl = [(c, r) for c, r in rows if c["gold_status"] == "implemented" and c["kind"] == "gold"]
    part = [(c, r) for c, r in rows if c["gold_status"] == "partial" and c["kind"] == "gold"]
    valid = sum(len(cl.get("evidence") or []) for _, r in rows for cl in r["claims"])
    rejected = sum(len(cl.get("rejected_evidence") or []) for _, r in rows for cl in r["claims"])
    confusion: Dict[str, Dict[str, int]] = {}
    for c, r in rows:
        confusion.setdefault(c["expected"], {}).setdefault(r["status"], 0)
        confusion[c["expected"]][r["status"]] += 1
    rate = lambda xs, pred: (sum(pred(r) for _, r in xs) / len(xs)) if xs else None  # noqa: E731
    return {
        "cases": n, "seconds": gen["seconds"],
        "exact_accuracy": exact / n if n else 0.0,
        "macro_f1": sum(f1s) / len(f1s),
        "f1_per_class": dict(zip(CLASSES, f1s)),
        "support_accuracy": binary / n if n else 0.0,
        "false_support_rate": rate(neg, lambda r: r["status"] in POSITIVE),
        "implemented_recall": rate(impl, lambda r: r["status"] in POSITIVE),
        "implemented_exact": rate(impl, lambda r: r["status"] == "supported"),
        "partial_recall": rate(part, lambda r: r["status"] in POSITIVE),
        "abstain_rate": sum(r["status"] == "insufficient_evidence" for _, r in rows) / n if n else 0.0,
        "citation_validity": valid / (valid + rejected) if valid + rejected else None,
        "valid_citations": valid, "rejected_citations": rejected,
        "model_failures": sum(1 for _, r in rows if r.get("error")),
        "sec_per_case": gen["seconds"] / n if n else None,
        "confusion": confusion,
    }
