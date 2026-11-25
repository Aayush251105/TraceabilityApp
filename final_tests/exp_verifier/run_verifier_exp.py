"""
Experiment E3/E5: verifier model x prompt, on the stored V1 runs.

Only the VERIFY stage is re-run. Requirements, docstrings, search candidates and
the mapping are reused from the V1 runs, so each configuration takes minutes per
pair instead of hours. All scoring uses the frozen V1 golds (../v1/gold/).

    SRS_to_code_traceability/.venv/bin/python TraceabilityApp/final_tests/exp_verifier/run_verifier_exp.py
        [--configs 7b-strict 14b-behavioral ...] [--pairs ProClinic ...]
        [--ollama-host http://localhost:11434] [--force] [--report-only] [--list]

What it does, per configuration and pair:
  1. traceability.cli verify on the requirements that V1 scored (the gold
     requirements that the SRS Agent extracted), with --keep-link-status and
     pipeline version "verification-exp-<config>". The V1 verdicts
     (verification-v1) and the link statuses the app shows are left untouched.
  2. traceability.cli evaluate-verification for that pipeline version.
  3. The V1 per-requirement rows (mapping unchanged) with the new verdict.

Then it writes results/summary.json and REPORT.md: pooled and per-pair verdict
metrics with 95% bootstrap CIs (same definitions as V1's score_v1.py), the
"right code was shown" split, citation validity, minutes, and exact McNemar
tests of every configuration against the V1 verdicts.

Resumable: a (config, pair) whose eval file exists is skipped unless --force.

Selection rule, fixed before running (no tuning on the results):
  primary metric = pooled macro-F1; a configuration only counts as better than
  V1 if its pooled false-support rate stays <= 10%.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
V1 = HERE.parent / "v1"
RES = HERE / "results"


def _workspace() -> Path:
    """The folder that holds SRS_to_code_traceability/ (works from DOC_Agent/ or a repo copy)."""
    for p in [HERE, *HERE.parents]:
        if (p / "SRS_to_code_traceability").is_dir():
            return p
    sys.exit("Cannot find the SRS_to_code_traceability folder above " + str(HERE))


WS = _workspace()
_BIN = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
PY = WS / "SRS_to_code_traceability" / ".venv" / _BIN

sys.path.insert(0, str(V1))
from score_v1 import EXPECTED, ORD, PRED, PAIRS, boot, mean, prf, ratio  # noqa: E402

# name -> (Ollama model, prompt, think). think: "default" | "on" | "off"
CONFIGS = {
    "7b-strict":        ("qwen2.5-coder:7b",  "strict",     "default"),   # V1 setting, re-run (determinism check)
    "7b-behavioral":    ("qwen2.5-coder:7b",  "behavioral", "default"),
    "14b-strict":       ("qwen2.5-coder:14b", "strict",     "default"),
    "14b-behavioral":   ("qwen2.5-coder:14b", "behavioral", "default"),
    "qwen3-14b-strict": ("qwen3:14b",         "strict",     "off"),
    "qwen3-14b-behavioral": ("qwen3:14b",     "behavioral", "off"),
}
OPTIONAL = {
    # Slower (hidden reasoning pass); run only with --configs.
    "qwen3-14b-think-behavioral": ("qwen3:14b", "behavioral", "on"),
}
BASELINE = "v1"          # the stored V1 verdicts (qwen2.5-coder:7b, strict)
FSR_LIMIT = 0.10


# --------------------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def cli(args, log_path: Path | None = None):
    r = subprocess.run([str(PY), "-m", "traceability.cli", *args], cwd=WS, capture_output=True, text=True)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"$ traceability.cli {' '.join(args)}\n{r.stdout}\n{r.stderr}\n")
    if r.returncode != 0:
        raise RuntimeError(f"traceability.cli {args[0]} failed ({r.returncode}): {r.stderr[-800:]}")
    return r


def pulled_models(host: str) -> set[str]:
    with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=10) as resp:
        names = {m["name"] for m in json.loads(resp.read())["models"]}
    return names | {n.removesuffix(":latest") for n in names}


def gold_path(pair: str) -> Path:
    p = V1 / "gold" / f"{pair}_gold_standard_v2.json"
    if not p.exists():
        sys.exit(f"Missing frozen V1 gold: {p}")
    return p


def v1_rows(pair: str) -> list[dict]:
    path = V1 / "results" / pair / "per_requirement.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["primary_in_mapping"] = r.get("primary_in_mapping") == "True"
    return rows


def with_predictions(rows: list[dict], predicted: dict[str, str] | None) -> list[dict]:
    """Copy of the V1 rows; predicted=None keeps the V1 verdicts."""
    out = []
    for r in rows:
        r = dict(r)
        if predicted is not None:
            r["predicted"] = predicted.get(r["requirement_id"], "unverified")
        st = r["gold_status"]
        r["pred_class"] = PRED.get(r["predicted"], r["predicted"])
        r["expected"] = EXPECTED.get(st)
        r["correct"] = (r["pred_class"] == EXPECTED[st]) if st in EXPECTED else None
        out.append(r)
    return out


# --------------------------------------------------------------------------- metrics (as score_v1.py)

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
    if not rs:
        return None
    cats, n = [0, 1, 2], len(rs)
    o = Counter((ORD[r["expected"]], ORD.get(r["pred_class"], 0)) for r in rs)
    pe = Counter(ORD[r["expected"]] for r in rs)
    pp = Counter(ORD.get(r["pred_class"], 0) for r in rs)
    w = lambda i, j: abs(i - j) / 2  # noqa: E731
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


def impl_recall_shown(rs):
    """Implemented requirements whose gold primary code reached the verifier: judged supported."""
    imp = [r for r in rs if r["gold_status"] == "implemented" and r["primary_in_mapping"]]
    return ratio(sum(r["pred_class"] == "sup" for r in imp), len(imp))


def partial_shown(rs):
    """Partial requirements whose gold primary code reached the verifier: judged partially_supported."""
    p = [r for r in rs if r["gold_status"] == "partial" and r["primary_in_mapping"]]
    return ratio(sum(r["pred_class"] == "part" for r in p), len(p))


METRICS = [("exact_accuracy", exact), ("macro_f1", macro_f1), ("weighted_kappa", kappa),
           ("false_support_rate", fsr), ("false_support_not_implemented", fsr_strict),
           ("implemented_recall", impl_recall), ("implemented_recall_code_shown", impl_recall_shown),
           ("partial_found_code_shown", partial_shown)]


def verdict_metrics(rows):
    vr = [r for r in rows if r["expected"]]
    out = {"requirements_judged": len(vr)}
    for name, fn in METRICS:
        out[name] = fn(vr)
        out[name + "_ci"] = boot(vr, fn)
    out["confusion"] = {k: dict(v) for k, v in _confusion(vr).items()}
    return out


def _confusion(rows):
    c = defaultdict(Counter)
    for r in rows:
        c[r["gold_status"]][r["predicted"]] += 1
    return c


def mcnemar(base_rows, rows):
    """Exact two-sided McNemar on per-requirement correctness (same requirements, paired)."""
    a = {(r["pair"], r["requirement_id"]): r["correct"] for r in base_rows if r["expected"]}
    b_only = c_only = 0
    for r in rows:
        k = (r["pair"], r["requirement_id"])
        if r["expected"] and k in a:
            if a[k] and not r["correct"]:
                b_only += 1          # baseline right, this config wrong
            elif r["correct"] and not a[k]:
                c_only += 1          # this config right, baseline wrong
    n = b_only + c_only
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, k) for k in range(min(b_only, c_only) + 1)) / 2 ** n)
    return {"baseline_right_config_wrong": b_only, "config_right_baseline_wrong": c_only, "p_value": p}


def agreement(base_rows, rows):
    a = {(r["pair"], r["requirement_id"]): r["predicted"] for r in base_rows if r["expected"]}
    same = [a[(r["pair"], r["requirement_id"])] == r["predicted"]
            for r in rows if r["expected"] and (r["pair"], r["requirement_id"]) in a]
    return mean([float(x) for x in same])


# --------------------------------------------------------------------------- running

def run_config(name: str, spec, pair: str, run: dict, host: str | None, force: bool) -> dict:
    model, prompt, think = spec
    out = RES / name / pair
    ev_path = out / "eval_verification.json"
    meta_path = out / "run.json"
    pv = f"verification-exp-{name}"
    rows = v1_rows(pair)
    ids = sorted({r["matched_to"] for r in rows if r["expected"] and r["matched_to"]})
    if force or not ev_path.exists():
        out.mkdir(parents=True, exist_ok=True)
        log(f"{name} / {pair}: verifying {len(ids)} requirements with {model} ({prompt}, think={think})")
        args = ["verify", "--document-id", run["document_id"], "--model", model, "--prompt", prompt,
                "--think", think, "--pipeline-version", pv, "--keep-link-status", "--json",
                "--requirements", ",".join(ids)]
        if host:
            args += ["--ollama-host", host]
        t0 = time.time()
        cli(args, RES / "logs" / f"{name}__{pair}.log")
        minutes = round((time.time() - t0) / 60, 2)
        cli(["evaluate-verification", "--gold", str(gold_path(pair)), "--document-id", run["document_id"],
             "--pipeline-version", pv, "--out", str(ev_path)], RES / "logs" / f"{name}__{pair}.log")
        meta_path.write_text(json.dumps({"config": name, "model": model, "prompt": prompt, "think": think,
                                         "pipeline_version": pv, "requirements": len(ids), "minutes": minutes,
                                         "document_id": run["document_id"]}, indent=2))
        log(f"{name} / {pair}: done in {minutes} min")
    ev = json.loads(ev_path.read_text())
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    predicted = {d["requirement_id"]: d["predicted"] for d in ev["per_requirement"]}
    new_rows = with_predictions(rows, predicted)
    keys = list(dict.fromkeys(k for r in new_rows for k in r))
    with (out / "per_requirement.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(new_rows)
    return {"rows": new_rows, "eval": ev, "minutes": meta.get("minutes")}


# --------------------------------------------------------------------------- report

def fmt(v, pct=False):
    if v is None:
        return "—"
    return f"{100 * v:.1f}%" if pct else f"{v:.3f}"


def fci(v, c, pct=False):
    return fmt(v, pct) + (f" [{fmt(c[0], pct)}, {fmt(c[1], pct)}]" if c else "")


def citation_validity(evals):
    valid = sum(e["counts"].get("citations_valid", 0) for e in evals)
    rej = sum(e["counts"].get("citations_rejected", 0) for e in evals)
    return ratio(valid, valid + rej)


def report(summary: dict, specs: dict) -> str:
    cfgs = summary["configs"]
    base = cfgs[BASELINE]["pooled"]
    L = ["# Verifier experiment: model × prompt on the V1 runs", "",
         "Only the verify stage was re-run; requirements, docstrings, candidates and mapping are the V1 ones, "
         "scored against the frozen V1 golds. 95% bootstrap CIs over requirements in brackets. "
         f"`{BASELINE}` = the verdicts stored by V1 (qwen2.5-coder:7b, strict prompt).", "",
         f"**Selection rule (fixed before running):** best pooled macro-F1 among configurations whose pooled "
         f"false-support rate is ≤ {FSR_LIMIT:.0%}.", "",
         "## 1. Pooled over the 4 pairs", "",
         "| Config | Model | Prompt | Think | Exact acc. | Macro-F1 | Weighted κ | False support ↓ | "
         "FS not-impl ↓ | Impl. recall | Impl. recall (code shown) | Partial found (code shown) | "
         "Citation valid. | Minutes | McNemar vs v1 (b/c, p) |",
         "|" + "---|" * 15]
    for name, c in cfgs.items():
        p = c["pooled"]
        m, pr, th = specs.get(name, ("qwen2.5-coder:7b", "strict", "default"))
        mc = c.get("mcnemar_vs_v1")
        mcs = f"{mc['baseline_right_config_wrong']}/{mc['config_right_baseline_wrong']}, p={mc['p_value']:.3f}" if mc else "—"
        L.append(f"| **{name}** | `{m}` | {pr} | {th} | {fci(p['exact_accuracy'], p['exact_accuracy_ci'])} | "
                 f"{fci(p['macro_f1'], p['macro_f1_ci'])} | {fmt(p['weighted_kappa'])} | "
                 f"{fci(p['false_support_rate'], p['false_support_rate_ci'], True)} | "
                 f"{fmt(p['false_support_not_implemented'], True)} | "
                 f"{fci(p['implemented_recall'], p['implemented_recall_ci'], True)} | "
                 f"{fmt(p['implemented_recall_code_shown'], True)} | {fmt(p['partial_found_code_shown'], True)} | "
                 f"{fmt(c.get('citation_validity'))} | {c.get('minutes') or '—'} | {mcs} |")
    L += ["", "*b* = requirements V1 got right and this configuration got wrong; *c* = the reverse. "
          "*Code shown* = the gold primary component was among the mapped components the verifier saw.", ""]
    eligible = {n: c for n, c in cfgs.items() if (c["pooled"]["false_support_rate"] or 0) <= FSR_LIMIT}
    if eligible:
        best = max(eligible, key=lambda n: eligible[n]["pooled"]["macro_f1"] or 0)
        bp = cfgs[best]["pooled"]
        L += [f"**By the selection rule: `{best}`** (macro-F1 {fmt(bp['macro_f1'])} vs {fmt(base['macro_f1'])} for v1). "
              "Check its McNemar p-value and CIs before calling it better.", ""]
    if "7b-strict" in cfgs:
        L += [f"Determinism check: `7b-strict` (the V1 setting, re-run) gives the same verdict as V1 on "
              f"{fmt(cfgs['7b-strict'].get('agreement_with_v1'), True)} of the requirements.", ""]
    L += ["## 2. Per pair", "", "| Config | Pair | Judged | Exact acc. | Macro-F1 | False support ↓ | Impl. recall |",
          "|---|---|---|---|---|---|---|"]
    for name, c in cfgs.items():
        for pair, p in c["per_pair"].items():
            L.append(f"| {name} | {pair} | {p['requirements_judged']} | {fmt(p['exact_accuracy'])} | "
                     f"{fmt(p['macro_f1'])} | {fmt(p['false_support_rate'], True)} | {fmt(p['implemented_recall'], True)} |")
    L += ["", "## 3. Verdict confusion, pooled (gold → predicted)", ""]
    for name, c in cfgs.items():
        L.append(f"**{name}**: " + "; ".join(f"{g} → " + ", ".join(f"{k} {v}" for k, v in sorted(d.items()))
                                             for g, d in sorted(c["pooled"]["confusion"].items())))
        L.append("")
    L += ["## 4. Caveats", "",
          "- One run per configuration at temperature 0 (deterministic up to GPU numerics); CIs cover requirement "
          "sampling only.",
          "- The model also splits compound claims (`--claims clauses`), so a model change affects claims and verdicts.",
          "- Requirements that the SRS Agent did not extract stay `unverified` (wrong) in every configuration.",
          "- These 4 pairs are the test set: report the selected configuration once; do not iterate prompts on them.",
          ""]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--configs", nargs="*", default=list(CONFIGS))
    ap.add_argument("--pairs", nargs="*", default=PAIRS)
    ap.add_argument("--ollama-host", default=None)
    ap.add_argument("--force", action="store_true", help="re-run even when results exist")
    ap.add_argument("--report-only", action="store_true", help="only rebuild summary.json and REPORT.md")
    ap.add_argument("--list", action="store_true", help="list the configurations and exit")
    a = ap.parse_args()

    specs = {**CONFIGS, **OPTIONAL}
    if a.list:
        for n, s in specs.items():
            print(f"{n:28s} {s[0]:20s} prompt={s[1]:10s} think={s[2]}{'  (optional)' if n in OPTIONAL else ''}")
        return
    unknown = [c for c in a.configs if c not in specs]
    if unknown:
        sys.exit(f"Unknown config(s): {unknown}. See --list.")
    if not PY.exists():
        sys.exit(f"Python not found: {PY}")
    runs = json.loads((V1 / "runs.json").read_text())["pairs"]

    if not a.report_only:
        host = a.ollama_host or "http://localhost:11434"
        have = pulled_models(host)
        missing = sorted({specs[c][0] for c in a.configs} - have)
        if missing:
            sys.exit("Pull these models first: " + "  ".join(f"ollama pull {m}" for m in missing))

    summary = {"configs": {}, "pairs": a.pairs, "fsr_limit": FSR_LIMIT}
    base_rows = [r for p in a.pairs for r in with_predictions(v1_rows(p), None)]
    v1_evals = [json.loads((V1 / "results" / p / "eval_verification.json").read_text()) for p in a.pairs]
    summary["configs"][BASELINE] = {
        "pooled": verdict_metrics(base_rows),
        "per_pair": {p: verdict_metrics([r for r in base_rows if r["pair"] == p]) for p in a.pairs},
        "citation_validity": citation_validity(v1_evals)}

    for name in a.configs:
        rows_all, evals, minutes = [], [], 0.0
        for pair in a.pairs:
            if a.report_only and not (RES / name / pair / "eval_verification.json").exists():
                continue
            try:
                got = run_config(name, specs[name], pair, runs[pair], a.ollama_host, a.force)
            except Exception as exc:                                   # keep going with the other pairs
                log(f"{name} / {pair}: FAILED: {exc}")
                continue
            rows_all += got["rows"]
            evals.append(got["eval"])
            minutes += got["minutes"] or 0
        if not rows_all:
            continue
        done = sorted({r["pair"] for r in rows_all})
        base_same = [r for r in base_rows if r["pair"] in done]
        summary["configs"][name] = {
            "pairs_done": done,
            "pooled": verdict_metrics(rows_all),
            "per_pair": {p: verdict_metrics([r for r in rows_all if r["pair"] == p]) for p in done},
            "citation_validity": citation_validity(evals),
            "minutes": round(minutes, 1),
            "mcnemar_vs_v1": mcnemar(base_same, rows_all),
            "agreement_with_v1": agreement(base_same, rows_all)}

    RES.mkdir(parents=True, exist_ok=True)
    (RES / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (HERE / "REPORT.md").write_text(report(summary, specs), encoding="utf-8")
    log(f"Wrote {RES / 'summary.json'} and {HERE / 'REPORT.md'}")


if __name__ == "__main__":
    main()
