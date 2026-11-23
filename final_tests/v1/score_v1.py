"""
FINAL TESTING V1 — step 3: score every completed run against the gold.

    SRS_to_code_traceability/.venv/bin/python final_tests/v1/score_v1.py [--pairs ...]

Uses `traceability.cli evaluate / evaluate-candidates / evaluate-mapping /
evaluate-verification` (raw outputs kept in results/<pair>/eval_*.json) and adds:
  - SRS extraction P/R/F1 vs the gold requirement list (ID match, else difflib
    ratio >= 0.6 on normalised text — the evaluators' own rule, so all stages match
    requirements the same way);
  - search (stored candidates = what mapping used): MAP, MRR, R@1/5/10, nDCG@10, SR@|G|;
    plus the per-channel `evaluate` report (all_hybrid MRR = the Run 6 baseline metric);
  - mapping: direct and all-links P/R/F1/F2 (micro over requirements);
  - verification: exact accuracy, macro-F1, linear-weighted kappa, false-support rate,
    implemented recall, confusion (cross_cutting separately), citation validity;
  - minutes per stage (runs.json);
  - 95% bootstrap CIs over requirements (2000 resamples, seed 42); macro and micro
    averages over the pairs;
  - error analysis of every wrong verdict: extraction / retrieval / mapping miss,
    verifier error.
Writes results/<pair>/scores.json, results/<pair>/per_requirement.csv,
results/summary.json and REPORT.md.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import random
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent.parent
PY = WS / "SRS_to_code_traceability" / ".venv" / "bin" / "python"
DATA = WS / "datasets" / "Data"
RES = HERE / "results"
LABEL = "V1 - human-annotated gold"
TEXT_THRESHOLD = 0.6
B, SEED = 2000, 42
PAIRS = ["Travel-Agency-Automation-System", "Books-Recommender-System", "Virtual-clinic", "ProClinic"]

EXPECTED = {"implemented": "sup", "partial": "part", "not_implemented": "not"}
PRED = {"supported": "sup", "partially_supported": "part", "not_supported_by_candidate": "not",
        "not_found": "not", "insufficient_evidence": "insuf", "unverified": "unverified"}
ORD = {"sup": 2, "part": 1, "not": 0, "insuf": 0, "unverified": 0}
RUN6 = {"search_mrr_all_hybrid": 0.936, "mapping_direct_p": 0.67, "mapping_direct_r": 0.87,
        "verifier_exact": 0.833, "false_support": 0.0, "supported": "27/39", "minutes_total": 85}


# --------------------------------------------------------------------------- helpers

def norm(text: str) -> str:
    sys.path.insert(0, str(WS / "SRS_to_code_traceability" / ".."))
    from traceability.query import normalise_text
    return normalise_text(text or "")


def ratio(a, b):
    return a / b if b else None


def prf(tp, fp, fn):
    p = ratio(tp, tp + fp); r = ratio(tp, tp + fn)
    f1 = 2 * p * r / (p + r) if p and r else 0.0 if p is not None and r is not None else None
    f2 = 5 * p * r / (4 * p + r) if p and r else 0.0 if p is not None and r is not None else None
    return {"precision": p, "recall": r, "f1": f1, "f2": f2, "tp": tp, "fp": fp, "fn": fn}


def boot(rows, fn):
    """95% percentile bootstrap CI of fn(rows) over rows."""
    if not rows:
        return None
    rng = random.Random(SEED)
    vals = []
    for _ in range(B):
        v = fn([rows[rng.randrange(len(rows))] for _ in rows])
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    return [vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def cli(args, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([str(PY), "-m", "traceability.cli", *args, "--out", str(out)], cwd=WS,
                       capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"traceability.cli {args[0]} failed: {r.stderr[-800:]}")
    return json.loads(out.read_text())


def extracted_requirements(document_id: str):
    from traceability.config import TraceabilityConfig
    import psycopg2
    cfg = TraceabilityConfig()
    with psycopg2.connect(cfg.build_dsn()) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT r.requirement_id, r.raw_text FROM {cfg.table_requirements} r "
                    f"JOIN {cfg.table_srs_documents} d USING (document_pk) WHERE d.document_id = %s",
                    (document_id,))
        return cur.fetchall()


def match_requirements(gold_reqs, extracted):
    """One-to-one: by ID, then greedy by text similarity >= TEXT_THRESHOLD."""
    ext = {rid: norm(t) for rid, t in extracted}
    used, out = set(), {}
    for g in gold_reqs:
        if g["requirement_id"] in ext:
            out[g["requirement_id"]] = (g["requirement_id"], "by_id", 1.0); used.add(g["requirement_id"])
    cands = []
    for g in gold_reqs:
        if g["requirement_id"] in out:
            continue
        t = norm(g["text"])
        for rid, et in ext.items():
            if rid not in used:
                cands.append((difflib.SequenceMatcher(None, t, et).ratio(), g["requirement_id"], rid))
    for s, gid, rid in sorted(cands, reverse=True):
        if s < TEXT_THRESHOLD:
            break
        if gid in out or rid in used:
            continue
        out[gid] = (rid, "by_text", round(s, 3)); used.add(rid)
    return out, used


def ap(ranks):
    """Average precision over the gold primaries (unretrieved count as 0)."""
    got = sorted(r for r in ranks if r is not None)
    if not ranks:
        return None
    return sum((i + 1) / r for i, r in enumerate(got)) / len(ranks)


# --------------------------------------------------------------------------- per pair

def score_pair(pair: str, run: dict):
    gold_path = DATA / pair / "gold_standard_v2.json"
    gold = json.loads(gold_path.read_text())
    out = RES / pair
    doc, repo = run["document_id"], run["repo_id"]
    G = str(gold_path)
    ev_search = cli(["evaluate", "--gold", G, "--repo-id", repo, "--document-id", doc,
                     "--query-source", "ingested"], out / "eval_search.json")
    ev_cand = cli(["evaluate-candidates", "--gold", G, "--document-id", doc], out / "eval_candidates.json")
    ev_map = cli(["evaluate-mapping", "--gold", G, "--document-id", doc], out / "eval_mapping.json")
    ev_ver = cli(["evaluate-verification", "--gold", G, "--document-id", doc], out / "eval_verification.json")

    reqs = gold["requirements"]
    extracted = extracted_requirements(doc)
    match, used = match_requirements(reqs + gold["excluded_requirements"], extracted)
    cand = {d["requirement_id"]: d for d in ev_cand["per_requirement"]}
    mapd = {d["requirement_id"]: d for d in ev_map["per_requirement"]}
    ver = {d["requirement_id"]: d for d in ev_ver["per_requirement"]}

    rows = []
    for g in reqs:
        rid, st = g["requirement_id"], g["status"]
        prim = {l["component_id"] for l in g["links"] if l["relevance"] == "primary"}
        allg = {l["component_id"] for l in g["links"]}
        m = match.get(rid)
        row = {"pair": pair, "requirement_id": rid, "gold_status": st, "sure": g.get("sure"),
               "matched_to": m[0] if m else None, "match_how": m[1] if m else "unmatched",
               "match_score": m[2] if m else None, "n_gold_primary": len(prim), "n_gold_links": len(allg)}
        c = cand.get(rid)
        if c and prim:
            ranks = [c["primary_ranks"].get(p) for p in sorted(prim)]
            found = [r for r in ranks if r is not None]
            row.update({"candidates": c["candidates"], "first_primary_rank": min(found) if found else None,
                        "ap": ap(ranks), "rr": 1 / min(found) if found else 0.0,
                        **{f"r@{k}": sum(1 for r in found if r <= k) / len(prim) for k in (1, 5, 10)},
                        "sr@|G|": float(all(r is not None and r <= len(prim) for r in ranks))})
        md = mapd.get(rid)
        if md is not None:
            d, s = set(md["direct"]), set(md["supporting"])
            row.update({"map_direct": ";".join(sorted(d)), "map_supporting": ";".join(sorted(s)),
                        "dir_tp": len(d & prim), "dir_fp": len(d - prim), "dir_fn": len(prim - d),
                        "all_tp": len((d | s) & allg), "all_fp": len((d | s) - allg), "all_fn": len(allg - d - s),
                        "primary_in_mapping": bool(prim & (d | s))})
        v = ver.get(rid, {})
        pred = v.get("predicted", "unverified")
        row.update({"predicted": pred, "pred_class": PRED.get(pred, pred),
                    "expected": EXPECTED.get(st), "correct": (PRED.get(pred) == EXPECTED[st]) if st in EXPECTED else None})
        # error analysis
        if row["correct"] is False:
            if not m:
                lab = "extraction miss"
            elif st in ("implemented", "partial") and not prim:
                lab = "gold has no links"
            elif st in ("implemented", "partial") and not row.get("first_primary_rank"):
                lab = "retrieval miss"
            elif st in ("implemented", "partial") and not row.get("primary_in_mapping"):
                lab = "mapping miss"
            else:
                lab = "verifier error"
            row["error_label"] = lab
        rows.append(row)

    s = summarize(rows)
    # extraction
    ng, ne = len(reqs), len(extracted)
    matched_scored = sum(1 for g in reqs if g["requirement_id"] in match)
    matched_all = len(match)
    n_all = ng + len(gold["excluded_requirements"])
    ext_p = ratio(len(used), ne)
    s["extraction"] = {"gold_requirements": ng, "gold_incl_excluded": n_all, "extracted": ne,
                       "matched_extracted": len(used), "precision": ext_p,
                       "recall": ratio(matched_scored, ng), "recall_incl_excluded": ratio(matched_all, n_all),
                       "by": dict(Counter(v[1] for v in match.values())), "text_threshold": TEXT_THRESHOLD}
    p, r = s["extraction"]["precision"], s["extraction"]["recall"]
    s["extraction"]["f1"] = 2 * p * r / (p + r) if p and r else 0.0
    s["extraction"]["recall_ci"] = boot([x for x in rows], lambda rs: mean([float(x["match_how"] != "unmatched")
                                                                             for x in rs]))
    s["search"]["ndcg@10_stored_candidates"] = ev_cand["scores"].get("ndcg@10")
    s["search"]["evaluate_channels"] = ev_search["channels"]
    s["search"]["mrr_all_hybrid"] = ev_search["channels"].get("all_hybrid", {}).get("mrr")
    s["search"]["gold_components_missing_from_repo"] = ev_search.get("gold_components_missing_from_repo")
    s["verification"]["citation_validity"] = ev_ver["scores"].get("citation_validity")
    s["verification"]["citation_on_gold"] = ev_ver["scores"].get("citation_on_gold")
    s["verification"]["evaluator_scores"] = ev_ver["scores"]
    s["verification"]["citations"] = {k: ev_ver["counts"][k] for k in ("citations_valid", "citations_rejected")}
    s["minutes"] = run.get("stage_minutes", {})
    s["minutes"]["wall_total"] = run.get("wall_minutes")
    s["run"] = {k: run.get(k) for k in ("run_id", "document_id", "repo_id", "commit_sha", "status", "models")}
    s["label"] = LABEL
    out.mkdir(parents=True, exist_ok=True)
    (out / "scores.json").write_text(json.dumps(s, indent=2, default=str))
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with (out / "per_requirement.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(rows)
    return s, rows


def summarize(rows):
    """Metrics (with bootstrap CIs) from per-requirement rows; used per pair and pooled (micro)."""
    srch = [r for r in rows if r.get("ap") is not None]
    S = {"search": {"requirements": len(srch)}}
    for k, f in (("map", "ap"), ("mrr", "rr"), ("r@1", "r@1"), ("r@5", "r@5"), ("r@10", "r@10"), ("sr@|G|", "sr@|G|")):
        S["search"][k] = mean([r[f] for r in srch])
        S["search"][k + "_ci"] = boot(srch, lambda rs, f=f: mean([r[f] for r in rs]))
    mp = [r for r in rows if r["gold_status"] in ("implemented", "partial") and "dir_tp" in r]

    def mapping(rs, kind):
        return prf(sum(r[f"{kind}_tp"] for r in rs), sum(r[f"{kind}_fp"] for r in rs), sum(r[f"{kind}_fn"] for r in rs))
    S["mapping"] = {"requirements": len(mp)}
    for kind in ("dir", "all"):
        name = "direct" if kind == "dir" else "all_links"
        S["mapping"][name] = mapping(mp, kind)
        for met in ("precision", "recall", "f1", "f2"):
            S["mapping"][name][met + "_ci"] = boot(mp, lambda rs, kind=kind, met=met: mapping(rs, kind)[met])
    no_code = [r for r in rows if r["gold_status"] in ("not_implemented", "cross_cutting") and "dir_tp" in r]
    S["mapping"]["links_on_requirements_without_code"] = sum(r["dir_fp"] + r["all_fp"] - r["dir_fp"] for r in no_code)

    vr = [r for r in rows if r["expected"]]
    V = S["verification"] = {"requirements_judged": len(vr)}

    def exact(rs):
        return mean([float(r["correct"]) for r in rs])

    def macro_f1(rs):
        f = []
        for c in ("sup", "part", "not"):
            tp = sum(1 for r in rs if r["expected"] == c and r["pred_class"] == c)
            fp = sum(1 for r in rs if r["expected"] != c and r["pred_class"] == c)
            fn = sum(1 for r in rs if r["expected"] == c and r["pred_class"] != c)
            if tp + fn:
                f.append(prf(tp, fp, fn)["f1"] or 0.0)
        return mean(f)

    def kappa(rs):
        """Cohen's kappa, linear weights, ordinal not(=insuf/unverified) < part < sup."""
        if not rs:
            return None
        cats = [0, 1, 2]; n = len(rs)
        o = defaultdict(float)
        for r in rs:
            o[(ORD[r["expected"]], ORD.get(r["pred_class"], 0))] += 1
        pe = Counter(ORD[r["expected"]] for r in rs); pp = Counter(ORD.get(r["pred_class"], 0) for r in rs)
        w = lambda i, j: abs(i - j) / 2
        do = sum(w(i, j) * o[(i, j)] for i in cats for j in cats) / n
        de = sum(w(i, j) * pe[i] * pp[j] for i in cats for j in cats) / (n * n)
        return 1 - do / de if de else None

    def fsr(rs):
        neg = [r for r in rs if r["gold_status"] in ("partial", "not_implemented")]
        return ratio(sum(r["pred_class"] == "sup" for r in neg), len(neg))

    def fsr_strict(rs):
        neg = [r for r in rs if r["gold_status"] == "not_implemented"]
        return ratio(sum(r["pred_class"] in ("sup", "part") for r in neg), len(neg))

    def impl_recall(rs):
        imp = [r for r in rs if r["gold_status"] == "implemented"]
        return ratio(sum(r["pred_class"] == "sup" for r in imp), len(imp))

    def impl_recall_lenient(rs):
        imp = [r for r in rs if r["gold_status"] in ("implemented", "partial")]
        return ratio(sum(r["pred_class"] in ("sup", "part") for r in imp), len(imp))

    for name, fn in (("exact_accuracy", exact), ("macro_f1", macro_f1), ("weighted_kappa", kappa),
                     ("false_support_rate", fsr), ("false_support_not_implemented_sup_or_part", fsr_strict),
                     ("implemented_recall", impl_recall), ("implemented_or_partial_found", impl_recall_lenient)):
        V[name] = fn(vr)
        V[name + "_ci"] = boot(vr, fn)
    conf = defaultdict(Counter)
    for r in rows:
        conf[r["gold_status"]][r["predicted"]] += 1
    V["confusion"] = {k: dict(v) for k, v in conf.items() if k != "cross_cutting"}
    V["cross_cutting"] = dict(conf.get("cross_cutting", {}))
    V["supported"] = sum(1 for r in rows if r["predicted"] == "supported")
    V["errors"] = dict(Counter(r["error_label"] for r in rows if r.get("error_label")))
    return S


# --------------------------------------------------------------------------- report

def fmt(v, pct=False):
    if v is None:
        return "—"
    if isinstance(v, (int,)) and not isinstance(v, bool):
        return str(v)
    return f"{100 * v:.1f}%" if pct else f"{v:.3f}"


def ci(v, c, pct=False):
    return fmt(v, pct) + (f" [{fmt(c[0], pct)}, {fmt(c[1], pct)}]" if c else "")


def report(per, rows_all, micro, macro, runs):
    L = [f"# Tracelight — Final Testing V1 Report", "", f"> **{LABEL}.** One run per pair, default models, "
         "auto-approved review (no human). 95% bootstrap CIs over requirements in brackets.", ""]
    pairs = list(per)
    L += ["## Setup", "",
          "| Pair | Run | Components | Gold reqs (scored set / excluded) | Commit |", "|---|---|---|---|---|"]
    for p in pairs:
        g = json.loads((DATA / p / "gold_standard_v2.json").read_text())
        L.append(f"| {p} | {runs[p]['run_id']} | {runs[p].get('python_components')} | "
                 f"{len(g['requirements'])} / {len(g['excluded_requirements'])} | `{runs[p]['commit_sha'][:10]}` |")
    m = runs[pairs[0]].get("models") or {}
    L += ["", "Models: " + ", ".join(f"{k} `{v}`" for k, v in m.items()) + " (extractor thinking off). "
          f"Requirement matching: ID, else difflib ratio ≥ {TEXT_THRESHOLD} on normalised text.", ""]

    def table(title, cols):
        out = [f"## {title}", "", "| Pair | " + " | ".join(c[0] for c in cols) + " |",
               "|---|" + "---|" * len(cols)]
        for name, s in [*per.items(), ("**micro (pooled)**", micro), ("**macro (mean of pairs)**", macro)]:
            out.append(f"| {name} | " + " | ".join(c[1](s) for c in cols) + " |")
        return out + [""]

    g = lambda *ks: (lambda s: _get(s, ks))
    L += table("1. SRS extraction", [
        ("Extracted", lambda s: fmt(_get(s, ("extraction", "extracted")))),
        ("Precision", lambda s: fmt(_get(s, ("extraction", "precision")))),
        ("Recall", lambda s: ci(_get(s, ("extraction", "recall")), _get(s, ("extraction", "recall_ci")))),
        ("F1", lambda s: fmt(_get(s, ("extraction", "f1")))),
        ("Recall incl. excluded", lambda s: fmt(_get(s, ("extraction", "recall_incl_excluded"))))])
    L += table("2. Search (stored candidates used by mapping)", [
        ("MAP", lambda s: ci(_get(s, ("search", "map")), _get(s, ("search", "map_ci")))),
        ("MRR", lambda s: ci(_get(s, ("search", "mrr")), _get(s, ("search", "mrr_ci")))),
        ("R@1", lambda s: fmt(_get(s, ("search", "r@1")))), ("R@5", lambda s: fmt(_get(s, ("search", "r@5")))),
        ("R@10", lambda s: fmt(_get(s, ("search", "r@10")))),
        ("nDCG@10", lambda s: fmt(_get(s, ("search", "ndcg@10_stored_candidates")))),
        ("SR@\\|G\\|", lambda s: fmt(_get(s, ("search", "sr@|G|")))),
        ("MRR all_hybrid (evaluate)", lambda s: fmt(_get(s, ("search", "mrr_all_hybrid"))))])
    L += table("3. Mapping (micro over implemented + partial requirements)", [
        ("Direct P", lambda s: ci(_get(s, ("mapping", "direct", "precision")), _get(s, ("mapping", "direct", "precision_ci")))),
        ("Direct R", lambda s: ci(_get(s, ("mapping", "direct", "recall")), _get(s, ("mapping", "direct", "recall_ci")))),
        ("Direct F1", lambda s: fmt(_get(s, ("mapping", "direct", "f1")))),
        ("Direct F2", lambda s: fmt(_get(s, ("mapping", "direct", "f2")))),
        ("All P", lambda s: fmt(_get(s, ("mapping", "all_links", "precision")))),
        ("All R", lambda s: fmt(_get(s, ("mapping", "all_links", "recall")))),
        ("All F1", lambda s: fmt(_get(s, ("mapping", "all_links", "f1")))),
        ("All F2", lambda s: fmt(_get(s, ("mapping", "all_links", "f2"))))])
    L += table("4. Verification", [
        ("Judged", lambda s: fmt(_get(s, ("verification", "requirements_judged")))),
        ("Exact acc.", lambda s: ci(_get(s, ("verification", "exact_accuracy")), _get(s, ("verification", "exact_accuracy_ci")))),
        ("Macro-F1", lambda s: fmt(_get(s, ("verification", "macro_f1")))),
        ("Weighted κ", lambda s: fmt(_get(s, ("verification", "weighted_kappa")))),
        ("False support ↓", lambda s: ci(_get(s, ("verification", "false_support_rate")), _get(s, ("verification", "false_support_rate_ci")), True)),
        ("Impl. recall", lambda s: ci(_get(s, ("verification", "implemented_recall")), _get(s, ("verification", "implemented_recall_ci")), True)),
        ("Citation valid.", lambda s: fmt(_get(s, ("verification", "citation_validity"))))])
    L += ["*False support* = partial or not-implemented requirements declared `supported`. *Impl. recall* = "
          "implemented requirements declared `supported`. κ: linear weights on not (incl. insufficient / "
          "unverified) < partial < supported.", ""]
    # baseline
    mi = micro
    L += ["## 5. Against the Run 6 library baseline (CLAUDE.md)", "",
          "Run 6 is the library **dev** set (39 requirements, its own SRS); V1 is 4 unseen test pairs, so this "
          "is a sanity comparison, not a like-for-like one.", "",
          "| Metric | Run 6 (library, dev) | V1 micro (4 test pairs) |", "|---|---|---|",
          f"| Search MRR (all_hybrid) | {RUN6['search_mrr_all_hybrid']} | {fmt(mean([_get(s, ('search', 'mrr_all_hybrid')) for s in per.values()]))} (mean of pairs) |",
          f"| Mapping direct P / R | {RUN6['mapping_direct_p']} / {RUN6['mapping_direct_r']} | "
          f"{fmt(_get(mi, ('mapping', 'direct', 'precision')))} / {fmt(_get(mi, ('mapping', 'direct', 'recall')))} |",
          f"| Verifier exact accuracy | {RUN6['verifier_exact']} | {fmt(_get(mi, ('verification', 'exact_accuracy')))} |",
          f"| False support | {RUN6['false_support']} | {fmt(_get(mi, ('verification', 'false_support_rate')), True)} |",
          f"| Supported | {RUN6['supported']} | {sum(_get(s, ('verification', 'supported')) or 0 for s in per.values())}/"
          f"{sum(len(json.loads((DATA / p / 'gold_standard_v2.json').read_text())['requirements']) for p in per)} |",
          f"| Minutes per pair | {RUN6['minutes_total']} | " + ", ".join(
              f"{p.split('-')[0]} {fmt(_get(s, ('minutes', 'wall_total')))}" for p, s in per.items()) + " |", ""]
    # confusion
    L += ["## 6. Verdict confusion (gold status → predicted)", ""]
    preds = ["supported", "partially_supported", "not_supported_by_candidate", "not_found", "insufficient_evidence",
             "unverified"]
    L += ["| Pair | Gold status | " + " | ".join(preds) + " |", "|---|---|" + "---|" * len(preds)]
    for p, s in per.items():
        conf = dict(s["verification"]["confusion"]); conf["cross_cutting (not scored)"] = s["verification"]["cross_cutting"]
        for st, c in conf.items():
            L.append(f"| {p} | {st} | " + " | ".join(str(c.get(x, 0)) for x in preds) + " |")
    L += [""]
    # errors
    L += ["## 7. Error analysis (every wrong verdict)", "",
          "Label order: *extraction miss* (gold requirement not extracted) → *gold has no links* → *retrieval miss* "
          "(no gold primary among the stored candidates) → *mapping miss* (primary retrieved but not mapped) → "
          "*verifier error* (gold code was shown, or the requirement has no code).", "",
          "| Pair | " + " | ".join(["extraction miss", "gold has no links", "retrieval miss", "mapping miss",
                                     "verifier error", "total wrong"]) + " |", "|---|" + "---|" * 6]
    for name, s in [*per.items(), ("**all**", micro)]:
        e = s["verification"]["errors"]
        L.append(f"| {name} | " + " | ".join(str(e.get(k, 0)) for k in ("extraction miss", "gold has no links",
                                                                           "retrieval miss", "mapping miss",
                                                                           "verifier error"))
                 + f" | {sum(e.values())} |")
    L += [""]
    sev = {"not_implemented": 0, "implemented": 1, "partial": 2}
    worst = sorted([r for r in rows_all if r.get("error_label")],
                   key=lambda r: (0 if r["gold_status"] == "not_implemented" and r["pred_class"] in ("sup", "part")
                                  else 1 if r["gold_status"] == "implemented" and r["error_label"] == "verifier error"
                                  else 2 if r["gold_status"] == "implemented" else 3, sev.get(r["gold_status"], 9)))
    L += ["## 8. Worst failures", "",
          "Ordered: false support on not-implemented requirements, then implemented requirements rejected with the "
          "right code shown, then other implemented misses, then partial.", "",
          "| # | Pair | Requirement | Gold | Predicted | Label | First primary rank | Mapped direct |",
          "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(worst[:25], 1):
        L.append(f"| {i} | {r['pair']} | {r['requirement_id']} | {r['gold_status']} | {r['predicted']} | "
                 f"{r['error_label']} | {r.get('first_primary_rank') or '—'} | "
                 f"{(r.get('map_direct') or '—').replace(';', ', ')[:90]} |")
    L += ["", f"All {len(worst)} wrong verdicts are in `results/<pair>/per_requirement.csv` (`error_label`).", ""]
    # timings
    stages = list(dict.fromkeys(k for s in per.values() for k in s["minutes"] if k != "wall_total"))
    L += ["## 9. Minutes per stage", "", "| Pair | " + " | ".join(stages) + " | wall total |",
          "|---|" + "---|" * (len(stages) + 1)]
    for p, s in per.items():
        L.append(f"| {p} | " + " | ".join(fmt(s["minutes"].get(k)) for k in stages)
                 + f" | {fmt(s['minutes'].get('wall_total'))} |")
    L += ["", "Lanes A (code) and B (SRS) run in parallel, so stage minutes overlap.", ""]
    usage = RES / "resource_usage_summary.md"
    if usage.exists():
        L += ["## 10. GPU / CPU usage (sampled every 10 s)", "", usage.read_text(), ""]
    rerun_usage = RES / "resource_usage_proclinic_rerun_summary.md"
    if rerun_usage.exists():
        L += ["### Final ProClinic and Virtual-clinic runs (two Ollama servers in parallel)", "",
              rerun_usage.read_text(), ""]
    gv = RES / "gold_validation.json"
    if gv.exists():
        d = json.loads(gv.read_text())
        L += ["## 11. Gold validation (step 1; golds not edited)", "", "| Pair | Errors | Warnings |", "|---|---|---|"]
        for p, v in d["pairs"].items():
            L.append(f"| {p} | {len(v['errors'])}: {dict(Counter(e['check'] for e in v['errors']))} | "
                     f"{len(v['warnings'])}: {dict(Counter(w['check'] for w in v['warnings']))} |")
        L += [""]
    L += ["## 12. Caveats", "",
          "- One run per pair (no repeats); CIs cover requirement sampling only, not run-to-run variance.",
          "- Auto-approved review: no human resolved the review items.",
          "- Requirements the gold marks partial without links cannot be scored for search/mapping "
          "(see section 11).", ""]
    notes = HERE / "RUN_NOTES.md"         # hand-written notes on this V1 run (bugs found, reruns)
    if notes.exists():
        L += [notes.read_text(), ""]
    (HERE / "REPORT.md").write_text("\n".join(L))


def _get(d, ks):
    for k in ks:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def main() -> None:
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--pairs", nargs="*", default=PAIRS)
    args = ap_.parse_args()
    runs = json.loads((HERE / "runs.json").read_text())["pairs"]
    per, rows_all = {}, []
    for pair in args.pairs:
        run = runs.get(pair)
        if not run or run.get("status") != "completed":
            print(f"skip {pair}: no completed run")
            continue
        s, rows = score_pair(pair, run)
        per[pair], rows_all = s, rows_all + rows
        print(f"{pair}: scored {len(rows)} requirements")
    if not per:
        return
    micro = summarize(rows_all)
    ex = [s["extraction"] for s in per.values()]
    tot = lambda k: sum(e[k] for e in ex)
    micro["extraction"] = {"extracted": tot("extracted"), "precision": ratio(tot("matched_extracted"), tot("extracted"))}
    matched = sum(1 for r in rows_all if r["match_how"] != "unmatched")
    micro["extraction"]["recall"] = ratio(matched, len(rows_all))
    p, r = micro["extraction"]["precision"], micro["extraction"]["recall"]
    micro["extraction"]["f1"] = 2 * p * r / (p + r) if p and r else 0.0
    micro["extraction"]["recall_ci"] = boot(rows_all, lambda rs: mean([float(x["match_how"] != "unmatched") for x in rs]))
    micro["search"]["mrr_all_hybrid"] = None
    micro["minutes"] = {"wall_total": sum(s["minutes"].get("wall_total") or 0 for s in per.values())}

    def macro_of(path):
        return mean([_get(s, path) for s in per.values()])
    paths = [("extraction", "extracted"), ("extraction", "precision"), ("extraction", "recall"), ("extraction", "f1"),
             ("extraction", "recall_incl_excluded"),
             *[("search", k) for k in ("map", "mrr", "r@1", "r@5", "r@10", "sr@|G|", "ndcg@10_stored_candidates",
                                       "mrr_all_hybrid")],
             *[("mapping", a, b) for a in ("direct", "all_links") for b in ("precision", "recall", "f1", "f2")],
             *[("verification", k) for k in ("requirements_judged", "exact_accuracy", "macro_f1", "weighted_kappa",
                                             "false_support_rate", "implemented_recall", "citation_validity")],
             ("minutes", "wall_total")]
    macro = {}
    for pth in paths:
        cur = macro
        for k in pth[:-1]:
            cur = cur.setdefault(k, {})
        cur[pth[-1]] = macro_of(pth)
    micro["search"]["ndcg@10_stored_candidates"] = None
    micro["verification"]["citation_validity"] = ratio(
        sum(s["verification"]["citations"]["citations_valid"] for s in per.values()),
        sum(s["verification"]["citations"]["citations_valid"] + s["verification"]["citations"]["citations_rejected"]
            for s in per.values()))
    summary = {"label": LABEL, "pairs": per, "micro": micro, "macro": macro, "run6_library_baseline": RUN6,
               "text_threshold": TEXT_THRESHOLD, "bootstrap": {"resamples": B, "seed": SEED}}
    (RES / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    report(per, rows_all, micro, macro, runs)
    print(f"wrote {RES / 'summary.json'} and {HERE / 'REPORT.md'}")


if __name__ == "__main__":
    main()
