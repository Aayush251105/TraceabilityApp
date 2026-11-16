"""
Leave-one-out LLM judging, shared by the SRS Agent and verifier benchmarks.

Same protocol as DocAgent/benchmark/llm_judge:
  * Leave-one-out: model X's output is never judged by X. Point-wise: judges are
    the other N-1 models. Pairwise A vs B: judges are the other N-2 models.
  * Position-bias control: every pairwise item is judged twice with A/B
    swapped; a win counts only when both orderings pick the same model,
    otherwise it is a TIE.
  * Win rate (wins / all decisions) is the primary metric.

Difference from DocAgent (to keep N small and fast): the point-wise judge scores
all rubric dimensions in ONE call per item (DocAgent made one call per
dimension). Calls are grouped by judge model so Ollama does not swap models
on every call, and every judgment is appended to a JSONL cache so an
interrupted run resumes where it stopped.
"""

from __future__ import annotations

import itertools
import json
import random
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from common.ollama_chat import OllamaChat

# items_by_model: {model_name: {item_id: output}}  — output is whatever render() accepts.
Render = Callable[[str, Any], str]          # (item_id, output) -> text shown to the judge
Context = Callable[[str], str]               # item_id -> the shared input (e.g. the requirement)


def sample_items(common_ids: Sequence[str], n: int, seed: int) -> List[str]:
    ids = sorted(common_ids)
    rng = random.Random(seed)
    return ids if len(ids) <= n else sorted(rng.sample(ids, n))


class _Cache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.done: Dict[str, Dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.done[rec["key"]] = rec

    def add(self, rec: Dict[str, Any]) -> None:
        self.done[rec["key"]] = rec
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ── point-wise ───────────────────────────────────────────────────────────────

def pointwise_prompt(rubrics: Dict[str, Dict[str, str]], task: str, context: str, output: str) -> str:
    dims = "\n\n".join(f"### {k} — {v['label']}\n{v['instruction']}" for k, v in rubrics.items())
    tags = "\n".join(f'<score name="{k}">N</score>' for k in rubrics)
    return (f"{task}\n\n## Input\n{context}\n\n## Output to evaluate\n{output}\n\n"
            f"## Rubrics (score each 1-5)\n{dims}\n\n"
            f"Think briefly, then end your answer with exactly these lines, N being an integer 1-5:\n{tags}")


def parse_scores(text: str, dims: Sequence[str]) -> Dict[str, Optional[int]]:
    out = {}
    for d in dims:
        m = re.search(rf'<score\s+name="?{re.escape(d)}"?\s*>\s*([1-5])\s*</score>', text, re.I)
        out[d] = int(m.group(1)) if m else None
    return out


def run_pointwise(*, models: List[Dict[str, Any]], ollama_cfg: Dict[str, Any],
                  items_by_model: Dict[str, Dict[str, Any]], item_ids: List[str],
                  context: Context, render: Render, system: str, task: str,
                  rubrics: Dict[str, Dict[str, str]], cache_path: Path) -> List[Dict[str, Any]]:
    cache = _Cache(cache_path)
    names = [m["name"] for m in models]
    dims = list(rubrics)
    for judge in models:                                 # judge-major: one model load per judge
        llm = OllamaChat.from_config(judge, ollama_cfg)
        todo = [(t, i) for t in names if t != judge["name"] for i in item_ids
                if i in items_by_model.get(t, {}) and f"pw|{t}|{judge['name']}|{i}" not in cache.done]
        print(f"  point-wise judge {judge['name']}: {len(todo)} calls", flush=True)
        for target, item in todo:
            prompt = pointwise_prompt(rubrics, task, context(item), render(item, items_by_model[target][item]))
            try:
                reply = llm.chat(system, prompt)
            except RuntimeError as exc:
                reply = f"[judge error] {exc}"
            cache.add({"key": f"pw|{target}|{judge['name']}|{item}", "target": target, "judge": judge["name"],
                       "item": item, "scores": parse_scores(reply, dims), "response": reply})
    return list(cache.done.values())


def summarize_pointwise(records: List[Dict[str, Any]], names: List[str], dims: List[str]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for n in names:
        recs = [r for r in records if r["target"] == n]
        row: Dict[str, Any] = {}
        for d in dims:
            vals = [r["scores"][d] for r in recs if r["scores"].get(d) is not None]
            row[d] = sum(vals) / len(vals) if vals else None
        got = [v for v in row.values() if v is not None]
        row["llm_avg"] = sum(got) / len(got) if got else None
        row["n_judgments"] = len(recs)
        row["unparsed"] = sum(1 for r in recs for d in dims if r["scores"].get(d) is None)
        out[n] = row
    return out


# ── pairwise ─────────────────────────────────────────────────────────────────

def pairwise_prompt(task: str, criteria: str, context: str, out_a: str, out_b: str) -> str:
    return (f"{task}\n\n## Input\n{context}\n\n## Output A\n{out_a}\n\n## Output B\n{out_b}\n\n"
            f"## What makes an output better\n{criteria}\n\n"
            "Compare the two outputs. Think briefly, then end with exactly one of:\n"
            "<winner>A</winner>\n<winner>B</winner>\n<winner>TIE</winner>")


def parse_winner(text: str) -> Optional[str]:
    m = re.findall(r"<winner>\s*(A|B|TIE)\s*</winner>", text, re.I)
    return m[-1].upper() if m else None


def run_pairwise(*, models: List[Dict[str, Any]], ollama_cfg: Dict[str, Any],
                 items_by_model: Dict[str, Dict[str, Any]], item_ids: List[str],
                 context: Context, render: Render, system: str, task: str, criteria: str,
                 cache_path: Path) -> List[Dict[str, Any]]:
    cache = _Cache(cache_path)
    names = [m["name"] for m in models]
    pairs = list(itertools.combinations(names, 2))
    for judge in models:
        llm = OllamaChat.from_config(judge, ollama_cfg)
        todo = []
        for a, b in pairs:
            if judge["name"] in (a, b):
                continue
            for i in item_ids:
                if i in items_by_model.get(a, {}) and i in items_by_model.get(b, {}):
                    if f"pp|{a}|{b}|{judge['name']}|{i}" not in cache.done:
                        todo.append((a, b, i))
        print(f"  pairwise judge {judge['name']}: {len(todo)} items x 2 orderings", flush=True)
        for a, b, item in todo:
            ctx = context(item)
            ra, rb = render(item, items_by_model[a][item]), render(item, items_by_model[b][item])
            replies = []
            for first, second in ((ra, rb), (rb, ra)):
                try:
                    replies.append(llm.chat(system, pairwise_prompt(task, criteria, ctx, first, second)))
                except RuntimeError as exc:
                    replies.append(f"[judge error] {exc}")
            wf, wr = parse_winner(replies[0]), parse_winner(replies[1])
            # forward: A=a; reversed: A=b. Agreement needed for a win.
            fwd = {"A": a, "B": b}.get(wf or "", "TIE")
            rev = {"A": b, "B": a}.get(wr or "", "TIE")
            final = fwd if fwd == rev and fwd != "TIE" else "TIE"
            cache.add({"key": f"pp|{a}|{b}|{judge['name']}|{item}", "model_a": a, "model_b": b,
                       "judge": judge["name"], "item": item, "winner_forward": wf, "winner_reversed": wr,
                       "final_winner": final, "response_forward": replies[0], "response_reversed": replies[1]})
    return list(cache.done.values())


def summarize_pairwise(records: List[Dict[str, Any]], names: List[str]) -> Dict[str, Any]:
    h2h = {a: {b: [0, 0, 0] for b in names if b != a} for a in names}     # row vs col: W/L/T
    for r in records:
        a, b, w = r["model_a"], r["model_b"], r["final_winner"]
        if w == a:
            h2h[a][b][0] += 1
            h2h[b][a][1] += 1
        elif w == b:
            h2h[b][a][0] += 1
            h2h[a][b][1] += 1
        else:
            h2h[a][b][2] += 1
            h2h[b][a][2] += 1
    ranking = []
    for n in names:
        w = sum(v[0] for v in h2h[n].values())
        lo = sum(v[1] for v in h2h[n].values())
        t = sum(v[2] for v in h2h[n].values())
        tot = w + lo + t
        ranking.append({"model": n, "wins": w, "losses": lo, "ties": t, "total": tot,
                        "win_rate": w / tot if tot else 0.0})
    ranking.sort(key=lambda r: (-r["win_rate"], r["losses"]))
    return {"head_to_head": h2h, "ranking": ranking}
