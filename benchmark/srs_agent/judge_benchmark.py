"""
SRS Agent — candidate-judge benchmark (small models only).

The candidate judge (SRSAgent/agents/candidate_judge.py) decides, for every
candidate the detector was NOT sure about (detection_confidence medium/low),
whether it is a requirement (keep), not one (discard) or unclear (uncertain;
review-only, not extracted). High-confidence candidates bypass the judge, so
they are identical for every model and are excluded from the judge metrics.

Ground truth per judged candidate, from the (DRAFT) gold requirement texts:
    requirement      >= 0.80 of the candidate's content words are in one gold requirement
    not requirement  <  0.50
    ambiguous        otherwise (fragments, headings with partial overlap) — not scored

Each model runs the real CandidateJudge with no fallback model, so a failed
batch counts against the model that failed.

    SRSAgent/.venv/bin/python TraceabilityApp/benchmark/srs_agent/judge_benchmark.py            # all
    SRSAgent/.venv/bin/python TraceabilityApp/benchmark/srs_agent/judge_benchmark.py --model qwen3-4b
    SRSAgent/.venv/bin/python TraceabilityApp/benchmark/srs_agent/judge_benchmark.py --report-only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from common.config import WORKSPACE, load_config, ws_path  # noqa: E402
from common.report import fmt_time, md_table  # noqa: E402
from common.textmatch import coverage, coverage_of_union  # noqa: E402

sys.path.insert(0, str(WORKSPACE / "SRSAgent"))

POS, NEG = 0.80, 0.50


def label(text: str, gold_reqs: List[Dict[str, Any]]) -> str:
    best = max((coverage(text, g["text"] or "") for g in gold_reqs), default=0.0)
    return "requirement" if best >= POS else ("not_requirement" if best < NEG else "ambiguous")


def gold_recall(retained_texts: List[str], gold_reqs: List[Dict[str, Any]]) -> int:
    """Gold requirements whose words are covered by the retained candidates that belong to them."""
    found = 0
    for g in gold_reqs:
        parts = [t for t in retained_texts if coverage(t, g["text"] or "") >= POS]
        found += coverage_of_union(g["text"] or "", parts) >= POS
    return found


# ── run ──────────────────────────────────────────────────────────────────────

def run_model(cfg: Dict[str, Any], entry: Dict[str, Any], out_dir: Path) -> Dict[str, Any]:
    from agents.candidate_judge import CandidateJudge
    from llm.ollama_provider import OllamaProvider

    provider = OllamaProvider(model=entry["ollama_model"], host=cfg["ollama"]["host"])
    per_pair = {}
    total_s = 0.0
    for pair in cfg["pairs"]:
        cands = json.loads((ws_path(cfg["paths"]["srs_results"]) / "candidates" / f"{pair['id']}.json")
                           .read_text(encoding="utf-8"))["candidates"]
        decisions, failures = [], []

        def progress(event, payload):
            if event == "judge_batch_done":
                decisions.extend(payload["decisions"])
                if payload.get("failure"):
                    failures.append(payload["failure"])

        judge = CandidateJudge(provider, fallback_provider=None)
        t0 = time.time()
        retained = judge.filter_candidates(cands, progress_callback=progress)
        secs = time.time() - t0
        total_s += secs
        per_pair[pair["id"]] = {"seconds": round(secs, 1), "retained": retained, "decisions": decisions,
                                "failed_batches": failures}
        print(f"  {pair['id']}: judged {len(decisions)}, retained {len(retained)}, "
              f"{len(failures)} failed batch(es), {secs:.0f}s", flush=True)
    res = {"model": entry["name"], "ollama_model": entry["ollama_model"], "seconds": round(total_s, 1),
           "pairs": per_pair}
    (out_dir / f"{entry['name']}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str),
                                                   encoding="utf-8")
    return res


# ── score ────────────────────────────────────────────────────────────────────

def score(cfg: Dict[str, Any], res: Dict[str, Any]) -> Dict[str, Any]:
    tot = {"tp": 0, "fn": 0, "fp": 0, "tn": 0, "uncertain_pos": 0, "uncertain_neg": 0, "ambiguous": 0,
           "judged": 0, "failed_batches": 0, "gold_found": 0, "gold_total": 0}
    per_pair = {}
    for pair in cfg["pairs"]:
        gold = json.loads((ws_path(cfg["paths"]["gold_json"]) / f"{pair['id']}.json").read_text(encoding="utf-8"))
        pr = res["pairs"][pair["id"]]
        p = {k: 0 for k in tot}
        for d in pr["decisions"]:
            lab = label(d["text"], gold["requirements"])
            kept = d["decision"] == "keep"
            p["judged"] += 1
            if lab == "ambiguous":
                p["ambiguous"] += 1
            elif lab == "requirement":
                p["tp" if kept else "fn"] += 1
                p["uncertain_pos"] += d["decision"] == "uncertain"
            else:
                p["fp" if kept else "tn"] += 1
                p["uncertain_neg"] += d["decision"] == "uncertain"
        p["failed_batches"] = len(pr["failed_batches"])
        p["gold_total"] = len(gold["requirements"])
        p["gold_found"] = gold_recall([c["text"] for c in pr["retained"]], gold["requirements"])
        p["seconds"] = pr["seconds"]
        per_pair[pair["id"]] = p
        for k in tot:
            tot[k] += p[k]
    tp, fp, fn = tot["tp"], tot["fp"], tot["fn"]
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    f2 = 5 * prec * rec / (4 * prec + rec) if prec + rec else 0.0
    scored = tp + fp + fn + tot["tn"]
    acc = (tp + tot["tn"]) / scored if scored else 0.0
    unc = (tot["uncertain_pos"] + tot["uncertain_neg"]) / max(1, scored)
    return {"model": res["model"], "ollama_model": res["ollama_model"], "seconds": res["seconds"],
            **tot, "precision": prec, "recall": rec, "f1": f1, "f2": f2, "accuracy": acc,
            "uncertain_rate": unc, "gold_recall": tot["gold_found"] / max(1, tot["gold_total"]),
            "per_pair": per_pair}


# ── report ───────────────────────────────────────────────────────────────────

def write_report(cfg: Dict[str, Any], rows: List[Dict[str, Any]], path: Path) -> None:
    rows = sorted(rows, key=lambda r: (-r["f1"], -r["recall"], r["seconds"]))
    n_pos = rows[0]["tp"] + rows[0]["fn"] if rows else 0
    n_neg = rows[0]["fp"] + rows[0]["tn"] if rows else 0
    L = [
        "# SRS Agent Candidate Judge — Model Benchmark Report",
        f"_Generated: {datetime.now():%Y-%m-%d %H:%M}_",
        "",
        "> **PROVISIONAL.** Ground truth comes from the DRAFT gold workbooks (AI-drafted 2026-11-15, "
        "not yet reviewed by the two annotators). Re-score with `--report-only` after the golds are frozen.",
        "",
        "## Models Evaluated",
        "",
    ]
    L += [f"- **{r['model']}** (`{r['ollama_model']}`) — judge time: {fmt_time(r['seconds'])}" for r in rows]
    L += [
        "",
        f"> **Task:** {rows[0]['judged'] if rows else 0} candidates over {len(cfg['pairs'])} SRS documents reach "
        f"the judge (detection confidence medium/low). By the draft gold, {n_pos} are requirements, "
        f"{n_neg} are not, {rows[0]['ambiguous'] if rows else 0} are ambiguous (not scored). "
        "High-confidence candidates bypass the judge and are the same for every model.",
        "",
        "---",
        "",
        "## 1. Ranking (F1 on judged candidates)",
        "",
        "Primary metric. A candidate counts as *kept* only when the judge says `keep` with medium/high "
        "confidence — exactly what the SRS Agent sends on to extraction. `uncertain` and low-confidence "
        "keeps go to human review only.",
        "",
    ]
    L += md_table(["Rank", "Model", "F1", "Precision", "Recall", "F2", "Accuracy", "Judge Time"],
                  [[i, r["model"], f"**{r['f1']:.3f}**", f"{r['precision']:.3f}", f"{r['recall']:.3f}",
                    f"{r['f2']:.3f}", f"{r['accuracy']:.3f}", fmt_time(r["seconds"])]
                   for i, r in enumerate(rows, 1)])
    L += ["", "---", "", "## 2. Judge Time", "",
          "Wall-clock time for the judge over all judged candidates of the 4 SRS documents.", ""]
    L += md_table(["Model", "Ollama Tag", "Judge Time"] + [p["id"] for p in cfg["pairs"]],
                  [[r["model"], f"`{r['ollama_model']}`", fmt_time(r["seconds"])] +
                   [fmt_time(r["per_pair"][p["id"]]["seconds"]) for p in cfg["pairs"]] for r in rows])
    L += ["", "---", "", "## 3. Confusion Counts", "",
          "TP = requirement kept, FN = requirement not kept (discarded or uncertain), FP = non-requirement "
          "kept, TN = non-requirement not kept. *Unc.* = how many of the not-kept items were `uncertain` "
          "(sent to review rather than dropped).", ""]
    L += md_table(["Model", "TP", "FN", "FP", "TN", "Unc. (req)", "Unc. (non-req)", "Uncertain Rate",
                   "Failed Batches"],
                  [[r["model"], r["tp"], r["fn"], r["fp"], r["tn"], r["uncertain_pos"], r["uncertain_neg"],
                    f"{r['uncertain_rate']:.1%}", r["failed_batches"]] for r in rows])
    L += ["", "---", "", "## 4. Full Metrics Summary", "",
          "*Gold recall (end to end)* = gold requirements whose text is covered (≥80% of content words) by "
          "the candidates retained for extraction (fast-path + judge-kept). Its ceiling is set by the "
          "detector, which is the same for all models.", ""]
    L += md_table(["Model", "Judge Time", "Precision", "Recall", "F1", "F2", "Accuracy", "Uncertain",
                   "Gold Recall (e2e)"],
                  [[r["model"], fmt_time(r["seconds"]), f"{r['precision']:.3f}", f"{r['recall']:.3f}",
                    f"**{r['f1']:.3f}**", f"{r['f2']:.3f}", f"{r['accuracy']:.3f}", f"{r['uncertain_rate']:.1%}",
                    f"{r['gold_found']}/{r['gold_total']} ({r['gold_recall']:.1%})"] for r in rows])
    L += ["", "---", "", "## 5. Per-Document Results", "",
          "Each cell: `F1 · gold recall (e2e)`.", ""]

    def pf1(p):
        pr = p["tp"] / (p["tp"] + p["fp"]) if p["tp"] + p["fp"] else 0.0
        rc = p["tp"] / (p["tp"] + p["fn"]) if p["tp"] + p["fn"] else 0.0
        return 2 * pr * rc / (pr + rc) if pr + rc else 0.0
    L += md_table(["Model"] + [p["id"] for p in cfg["pairs"]],
                  [[r["model"]] + [f"{pf1(r['per_pair'][p['id']]):.3f} · {r['per_pair'][p['id']]['gold_found']}/"
                                   f"{r['per_pair'][p['id']]['gold_total']}" for p in cfg["pairs"]] for r in rows])
    L += ["", "---", "", "## 6. Methodology", "",
          "- **Input:** each SRS is parsed and segmented once (`prepare_candidates.py`, no LLM); all models judge "
          "the identical candidate list.",
          "- **Judge code:** the unmodified `CandidateJudge` (batches of ≤20 candidates / 7000 chars, structured "
          "JSON output, temperature 0, seed 42). No fallback model, so failures count against the judge.",
          f"- **Labels:** text matching against the draft gold requirement texts (requirement ≥ {POS:.2f} of the "
          f"candidate's content words inside one gold requirement; not a requirement < {NEG:.2f}; otherwise "
          "ambiguous and not scored). Matching is by text, not ID, because gold IDs were renamed for some pairs.",
          "- **No LLM-as-judge here:** the judge is a classifier with a ground truth, so it is scored objectively "
          "(the leave-one-out LLM judging is used for the extractor and verifier, whose outputs are free text).",
          "- Single run per model (deterministic decoding).",
          ""]
    path.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", help="judge model name(s) from config srs_judge_models")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    out_dir = ws_path(cfg["paths"]["srs_results"]) / "judge"
    raw_dir = out_dir / "raw_decisions"
    raw_dir.mkdir(parents=True, exist_ok=True)
    models = [m for m in cfg["srs_judge_models"] if not args.model or m["name"] in args.model]
    if not args.report_only:
        for m in models:
            print(f"\n=== judge {m['name']} ({m['ollama_model']})", flush=True)
            run_model(cfg, m, raw_dir)
    rows = []
    for m in cfg["srs_judge_models"]:
        f = raw_dir / f"{m['name']}.json"
        if f.exists():
            rows.append(score(cfg, json.loads(f.read_text(encoding="utf-8"))))
    (out_dir / "judge_metrics.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    write_report(cfg, rows, out_dir / "final_report.md")
    print(f"\nreport: {out_dir / 'final_report.md'}")


if __name__ == "__main__":
    main()
