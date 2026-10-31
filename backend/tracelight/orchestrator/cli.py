"""
Tracelight pipeline from the terminal (no UI needed).

    python -m tracelight.orchestrator.cli init
    python -m tracelight.orchestrator.cli run --srs SRS.docx --folder path/to/code
    python -m tracelight.orchestrator.cli run --srs SRS.docx --git https://github.com/owner/repo [--ref main]
    python -m tracelight.orchestrator.cli run --srs SRS.docx --zip code.zip --auto-approve
    python -m tracelight.orchestrator.cli list
    python -m tracelight.orchestrator.cli status 3
    python -m tracelight.orchestrator.cli review 3                     # open items
    python -m tracelight.orchestrator.cli resolve 3 req:4 merged --into FR-004
    python -m tracelight.orchestrator.cli resolve 3 cand:C-0002 discarded
    python -m tracelight.orchestrator.cli skip-remaining 3
    python -m tracelight.orchestrator.cli continue 3                   # finish review, run the rest
    python -m tracelight.orchestrator.cli resume 3                     # after a failure or restart

Ctrl+C cancels the run (it can be resumed later).
Model overrides for one run: --model-docagent, --model-srs, --model-judge, --model-verifier.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any, Dict, List

from traceability.config import TraceabilityConfig

from .review import ReviewError
from .runner import Orchestrator
from .source import SourceError

COLORS = {"ok": "\033[32m", "warn": "\033[33m", "error": "\033[31m", "info": ""}
RESET = "\033[0m"


def _print_event(e: Dict[str, Any]) -> None:
    lane = f"[{e['lane']}] " if e.get("lane") else "    "
    color = COLORS.get(e.get("level", "info"), "")
    ts = e.get("ts")                      # stored events carry their time; live ones are "now"
    when = ts.astimezone() if ts is not None else datetime.now()
    print(f"{when:%H:%M:%S} {lane}{color}{e['message']}{RESET if color else ''}", flush=True)


def _orchestrator(args: argparse.Namespace, *, verbose: bool = True) -> Orchestrator:
    return Orchestrator(TraceabilityConfig(), docagent_test_mode=getattr(args, "docagent_test_mode", "none"),
                        on_event=_print_event if verbose else None)


def _follow(orch: Orchestrator, run_id: int, auto_approve: bool) -> int:
    thread = orch.start(run_id, auto_approve=auto_approve)
    try:
        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\nCancelling…", flush=True)
        orch.cancel(run_id)
        thread.join()
    with orch.store() as s:
        run = s.get_run(run_id)
    print(f"\nRun {run_id}: {run['status']}" + (f" — {run['error']}" if run["error"] else ""))
    if run["status"] == "paused":
        open_items = orch.review_state(run_id)["counts"]["open"]
        if open_items:
            print(f"{open_items} item(s) need your review:  python -m tracelight.orchestrator.cli review {run_id}")
        else:
            print("Nothing needs a decision. Check the items with "
                  f"`review {run_id} --all` if you like, then:")
        print(f"Continue:  python -m tracelight.orchestrator.cli continue {run_id}")
    if run["status"] == "completed":
        print(json.dumps(run["summary"], indent=2))
    return 0 if run["status"] in ("completed", "paused") else 1


def _overrides(args: argparse.Namespace) -> Dict[str, Any]:
    models = {k: getattr(args, f"model_{k}") for k in ("docagent", "srs", "judge", "verifier")
              if getattr(args, f"model_{k}", None)}
    out: Dict[str, Any] = {"models": models} if models else {}
    if args.sequential:
        out["ingest"] = {"parallel": False}
    return out


def cmd_run(args) -> int:
    orch = _orchestrator(args)
    orch.init()
    kind, ref = next((k, getattr(args, k)) for k in ("zip", "folder", "git") if getattr(args, k))
    run_id = orch.create_run(source_kind=kind, source_ref=ref, srs_path=args.srs, git_ref=args.ref,
                             name=args.name, overrides=_overrides(args))
    print(f"Run {run_id} created", flush=True)
    return _follow(orch, run_id, args.auto_approve)


def cmd_resume(args) -> int:
    return _follow(_orchestrator(args), args.run_id, args.auto_approve)


def cmd_continue(args) -> int:
    orch = _orchestrator(args)
    try:
        result = orch.complete_review(args.run_id)
    except ReviewError as exc:
        print(f"Review incomplete: {exc}" + (f"\n  items: {', '.join(exc.keys)}" if exc.keys else ""))
        return 1
    print(f"Review applied: {result}")
    return _follow(orch, args.run_id, False)


def cmd_list(args) -> int:
    with _orchestrator(args, verbose=False).store() as s:
        for r in s.list_runs():
            print(f"{r['run_id']:4d}  {r['status']:10s}  {r['created_at']:%Y-%m-%d %H:%M}  {r['name']}")
    return 0


def cmd_status(args) -> int:
    with _orchestrator(args, verbose=False).store() as s:
        run = s.get_run(args.run_id)
        if run is None:
            print("No such run")
            return 1
        print(f"Run {run['run_id']} · {run['name']} · {run['status']}"
              + (f" · {run['error']}" if run["error"] else ""))
        for st in s.stages(args.run_id):
            total = f"{st['done']}/{st['total']}" if st["total"] is not None else ""
            lane = st["lane"] or "-"
            print(f"  {lane} {st['stage']:15s} {st['status']:10s} {total:>9s}  {st['error'] or ''}")
        print()
        for e in s.events(args.run_id, after=0, limit=100000)[-args.tail:]:
            _print_event(e)
    return 0


def cmd_review(args) -> int:
    state = _orchestrator(args, verbose=False).review_state(args.run_id)
    c = state["counts"]
    print(f"{c['open']} open of {c['total']} ({c['open_by_category']})\n")
    if not c["open"] and not args.all:
        print(f"Nothing open. Use --all to see the resolved items, or run: continue {args.run_id}")
    for it in state["items"]:
        if it["resolution"] and not args.all:
            continue
        p = it["payload"]
        res = it["resolution"] or "OPEN"
        sugg = p.get("suggestion") or {}
        print(f"{it['item_key']:18s} {it['category']:10s} {res:10s} {it['requirement_id'] or '':10s} {p.get('title')}")
        for reason in p.get("reasons", []):
            print(f"{'':20s}- {reason}")
        if sugg:
            print(f"{'':20s}suggested: {sugg.get('action')} {sugg.get('target') or ''}")
    return 0


def cmd_resolve(args) -> int:
    data: Dict[str, Any] = {}
    if args.into:
        data["into"] = args.into
    if args.text:
        data["text"] = args.text
    if args.id:
        data["requirement_id"] = args.id
    with _orchestrator(args, verbose=False).store() as s:
        ok = s.resolve_review_item(args.run_id, args.item_key, args.resolution, data)
    print("resolved" if ok else f"no item {args.item_key!r} in run {args.run_id}")
    return 0 if ok else 1


def cmd_skip_remaining(args) -> int:
    n = _orchestrator(args, verbose=False).skip_remaining(args.run_id)
    print(f"{n} item(s) kept as unreviewed")
    return 0


def cmd_init(args) -> int:
    _orchestrator(args, verbose=False).init()
    print("Run-state tables ready")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tracelight", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the run-state tables").set_defaults(func=cmd_init)

    r = sub.add_parser("run", help="create and run a new job")
    r.add_argument("--srs", required=True, help="SRS file (.docx, .pdf, .md, .txt)")
    src = r.add_mutually_exclusive_group(required=True)
    src.add_argument("--zip")
    src.add_argument("--folder")
    src.add_argument("--git", help="https:// Git URL")
    r.add_argument("--ref", help="branch or tag (with --git)")
    r.add_argument("--name")
    r.add_argument("--sequential", action="store_true", help="run the SRS lane, then the code lane")
    for role in ("docagent", "srs", "judge", "verifier"):
        r.add_argument(f"--model-{role}")
    r.set_defaults(func=cmd_run)

    for name, func, helptext in (("resume", cmd_resume, "resume a failed, cancelled-before-start or paused run"),
                                 ("continue", cmd_continue, "apply the review and run the remaining stages")):
        c = sub.add_parser(name, help=helptext)
        c.add_argument("run_id", type=int)
        c.set_defaults(func=func)
    for c in (r, sub.choices["resume"]):
        c.add_argument("--auto-approve", action="store_true",
                       help="do not pause for review: open items are kept and marked unreviewed")
        c.add_argument("--docagent-test-mode", default="none", choices=["none", "placeholder"],
                       help="placeholder: DocAgent writes placeholder docstrings without an LLM")
    sub.choices["continue"].add_argument("--docagent-test-mode", default="none", choices=["none", "placeholder"])

    sub.add_parser("list", help="list runs").set_defaults(func=cmd_list)
    st = sub.add_parser("status", help="stages and recent events of a run")
    st.add_argument("run_id", type=int)
    st.add_argument("--tail", type=int, default=25)
    st.set_defaults(func=cmd_status)

    rv = sub.add_parser("review", help="show review items")
    rv.add_argument("run_id", type=int)
    rv.add_argument("--all", action="store_true", help="include resolved items")
    rv.set_defaults(func=cmd_review)

    rs = sub.add_parser("resolve", help="resolve one review item")
    rs.add_argument("run_id", type=int)
    rs.add_argument("item_key")
    rs.add_argument("resolution", choices=["kept", "edited", "discarded", "merged", "unreviewed"])
    rs.add_argument("--into", help="merge target requirement ID")
    rs.add_argument("--text", help="edited text")
    rs.add_argument("--id", help="new requirement ID")
    rs.set_defaults(func=cmd_resolve)

    sk = sub.add_parser("skip-remaining", help="keep all open items as unreviewed")
    sk.add_argument("run_id", type=int)
    sk.set_defaults(func=cmd_skip_remaining)
    return p


def main(argv: List[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (SourceError, ReviewError) as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
