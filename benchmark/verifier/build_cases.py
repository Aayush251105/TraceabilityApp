"""
Verifier benchmark — Step 0: build fixed verification cases from the (DRAFT) gold.

Each case = one requirement + the code shown to the verifier + the expected verdict.
Search and mapping are taken out of the loop, so only the verifier model varies.

  gold      implemented / partial requirement + its gold PRIMARY components (role
            direct) and SUPPORTING components (role supporting)
            -> expected `supported` (implemented) or `partially_supported` (partial)
  distractor  the same requirement + the 2 components that look most similar by BM25
            but are not linked to it (and not in the same class as a linked one)
            -> expected `not_supported_by_candidate` (a "support" here is a false support)
  absent    not_implemented requirement + its 2 most similar components
            -> expected `not_supported_by_candidate`
cross_cutting and excluded requirements are skipped (no single-component verdict).

    SRS_to_code_traceability/.venv/bin/python TraceabilityApp/benchmark/verifier/build_cases.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from common.codeindex import BM25, code_tokens, load_components  # noqa: E402
from common.config import load_config, ws_path  # noqa: E402

N_DISTRACTORS = 2
EXPECTED = {"implemented": "supported", "partial": "partially_supported"}


def _family(cid: str) -> str:
    """Module + class part of a component ID (methods of one class share it)."""
    parts = cid.split(".")
    for i, p in enumerate(parts):
        if p[:1].isupper():
            return ".".join(parts[: i + 1])
    return cid


def build(cfg) -> list:
    cases = []
    for pair in cfg["pairs"]:
        gold = json.loads((ws_path(cfg["paths"]["gold_json"]) / f"{pair['id']}.json").read_text(encoding="utf-8"))
        comps = load_components(cfg, pair["id"], gold)
        by_id = {c["component_id"]: c for c in comps}
        bm25 = BM25([code_tokens(c["text"]) for c in comps])
        links = {}
        for l in gold["links"]:
            links.setdefault(l["requirement_id"], []).append(l)
        for req in gold["requirements"]:
            status, rid, text = req["status"], req["requirement_id"], req["text"] or ""
            if status not in ("implemented", "partial", "not_implemented") or not text:
                continue
            rl = [l for l in links.get(rid, []) if l["component"] in by_id]
            base = {"pair": pair["id"], "requirement_id": rid, "requirement_text": text, "gold_status": status,
                    "gold_sure": req.get("sure")}
            linked = {l["component"] for l in rl}
            if status in EXPECTED:
                prim = [l["component"] for l in rl if l["role"] == "primary"]
                if not prim:
                    continue
                supp = [l["component"] for l in rl if l["role"] == "supporting"]
                cases.append({**base, "case_id": f"{pair['id']}::{rid}::gold", "kind": "gold",
                              "expected": EXPECTED[status],
                              "components": [{"component_id": c, "role": "direct"} for c in prim] +
                                            [{"component_id": c, "role": "supporting"} for c in supp]})
            families = {_family(c) for c in linked}
            scores = bm25.scores(code_tokens(text))
            order = sorted(range(len(comps)), key=lambda i: -scores[i])
            picks = []
            for i in order:
                cid = comps[i]["component_id"]
                if cid in linked or _family(cid) in families or not comps[i]["source_code"].strip():
                    continue
                picks.append(cid)
                if len(picks) == N_DISTRACTORS:
                    break
            kind = "distractor" if status in EXPECTED else "absent"
            cases.append({**base, "case_id": f"{pair['id']}::{rid}::{kind}", "kind": kind,
                          "expected": "not_supported_by_candidate",
                          "components": [{"component_id": c, "role": "direct"} for c in picks]})
    return cases


def main() -> None:
    cfg = load_config()
    out = ws_path(cfg["paths"]["verifier_results"])
    out.mkdir(parents=True, exist_ok=True)
    cases = build(cfg)
    (out / "cases.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    print(len(cases), "cases", dict(Counter(c["kind"] for c in cases)), dict(Counter(c["expected"] for c in cases)))
    print("per pair", dict(Counter(c["pair"] for c in cases)))


if __name__ == "__main__":
    main()
