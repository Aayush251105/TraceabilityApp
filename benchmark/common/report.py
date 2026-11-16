"""
Markdown report helpers. `standard_report` reproduces the section layout of
DocAgent/benchmark/results/final_report.md:

  Models Evaluated · 1. Pairwise Win Rate Ranking · 2. <Task> Time ·
  3. Pairwise Head-to-Head · 4. Full Metrics Summary · 5. Objective metrics ·
  6. Point-wise LLM Judge Scores · 7. Methodology
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

PROVISIONAL = ("> **PROVISIONAL.** Ground truth comes from the DRAFT gold workbooks (AI-drafted 2026-11-15, "
               "not yet reviewed by the two annotators). Raw outputs are saved, so the objective metrics can be "
               "re-scored without re-running any model once the golds are frozen.")


def md_table(headers: List[str], rows: List[List[Any]]) -> List[str]:
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("-" * max(3, len(h)) for h in headers) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def fmt_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


def f3(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.3f}"


def pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1%}"


# (header, key, formatter)
Col = Tuple[str, str, Callable[[Any], str]]


def standard_report(*, title: str, models: List[Dict[str, Any]], time_label: str, time_desc: str,
                    seconds: Dict[str, Optional[float]], pairwise: Optional[Dict[str, Any]],
                    n_judges_pair: int, objective: Dict[str, Dict[str, Any]], objective_cols: Sequence[Col],
                    objective_title: str, objective_desc: str,
                    pointwise: Optional[Dict[str, Dict[str, Any]]], rubrics: Dict[str, Dict[str, str]],
                    methodology: List[str], extra_sections: List[str] | None = None) -> str:
    names = [m["name"] for m in models]
    order = [r["model"] for r in pairwise["ranking"]] if pairwise else names
    tag = {m["name"]: m["ollama_model"] for m in models}
    rank = {r["model"]: r for r in pairwise["ranking"]} if pairwise else {}
    L = [f"# {title}", f"_Generated: {datetime.now():%Y-%m-%d %H:%M}_", "", PROVISIONAL, "",
         "## Models Evaluated", ""]
    L += [f"- **{n}** (`{tag[n]}`) — {time_label.lower()}: {fmt_time(seconds.get(n))}" for n in order]
    L += ["", "> **Judge protocol:** Leave-one-out. When model X is evaluated, judges are all other models.",
          "", "---", "", "## 1. Pairwise Win Rate Ranking", "",
          f"Primary metric. Each matchup is judged by the {n_judges_pair} remaining models.",
          "Position bias is controlled by running each pair in both orderings;",
          "a win is only counted when the judge agrees across both orderings.", ""]
    if pairwise:
        L += md_table(["Rank", "Model", "Win Rate", "W", "L", "T", "Total Decisions"],
                      [[i, r["model"], f"**{r['win_rate']:.1%}**", r["wins"], r["losses"], r["ties"], r["total"]]
                       for i, r in enumerate(pairwise["ranking"], 1)])
    else:
        L.append("_Pairwise judging not run yet._")
    L += ["", "---", "", f"## 2. {time_label}", "", time_desc, ""]
    L += md_table(["Model", "Ollama Tag", time_label], [[n, f"`{tag[n]}`", fmt_time(seconds.get(n))] for n in order])
    L += ["", "---", "", "## 3. Pairwise Head-to-Head Results", "",
          "Each cell shows `W / L / T` (wins, losses, ties) for the **row model** against the **column model**.", ""]
    if pairwise:
        h2h = pairwise["head_to_head"]
        L += md_table(["Model"] + order,
                      [[f"**{a}**"] + ["—" if a == b else "/".join(map(str, h2h[a][b])) for b in order] for a in order])
    else:
        L.append("_Pairwise judging not run yet._")
    dims = list(rubrics)
    L += ["", "---", "", "## 4. Full Metrics Summary", "",
          "Objective metrics need no LLM. LLM-judged scores are 1–5, averaged across leave-one-out judges.", ""]
    head = [time_label.split()[0] + " Time"] + [c[0] for c in objective_cols] + \
        [rubrics[d].get("short", rubrics[d]["label"].split()[0]) for d in dims] + ["LLM Avg", "Win Rate"]
    rows = []
    for n in order:
        o, p = objective.get(n, {}), (pointwise or {}).get(n, {})
        rows.append([n, fmt_time(seconds.get(n))] + [fmt(o.get(k)) for _, k, fmt in objective_cols] +
                    [f3(p.get(d)) for d in dims] + [f3(p.get("llm_avg")),
                                                     f"**{rank[n]['win_rate']:.1%}**" if n in rank else "—"])
    L += md_table(["Model"] + head, rows)
    L += ["", "---", "", f"## 5. {objective_title}", "", objective_desc, ""]
    L += md_table(["Model"] + [c[0] for c in objective_cols],
                  [[n] + [fmt(objective.get(n, {}).get(k)) for _, k, fmt in objective_cols] for n in order])
    L += ["", "---", "", "## 6. Point-wise LLM Judge Scores", "",
          "Each score is 1–5, averaged across all leave-one-out judges and sampled items.", ""]
    if pointwise:
        L += md_table(["Model"] + [rubrics[d]["label"] for d in dims] + ["Judgments", "Unparsed"],
                      [[n] + [f3(pointwise[n].get(d)) for d in dims] +
                       [pointwise[n]["n_judgments"], pointwise[n]["unparsed"]] for n in order])
    else:
        L.append("_Point-wise judging not run yet._")
    for sec in extra_sections or []:
        L += ["", "---", "", sec]
    L += ["", "---", "", "## 7. Methodology", ""] + [f"- {m}" for m in methodology] + [""]
    return "\n".join(L)
