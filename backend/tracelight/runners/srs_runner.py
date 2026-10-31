"""
Run the SRS Agent and report progress as JSON events.

Executed with **the SRS Agent's own Python** (its virtual environment).  It
imports the SRS Agent unchanged and turns its progress callbacks into
one-line JSON events on stdout (`@@tracelight {...}`).

Modes
-----
extract              parse → detect candidates → judge → extract (the full agent)
detect               parse → detect candidates only (no LLM; quick check)
extract-candidates   extract the given candidates only (used after the review
                     checkpoint, for uncertain candidates the user kept)

Files written to --out-dir
--------------------------
requirements.json          extracted requirements (SRS Agent Requirement records)
extraction_report.json     segmentation report, counts, failures, candidate_review
candidates.json            every detected candidate (text, source, confidence, ID)
document_blocks.json       the parsed document (headings, paragraphs, list items,
                           tables with locations) for the review page's source view

Models come from the SRS Agent's environment variables, which the
orchestrator sets: LLM_MODEL, JUDGE_MODEL, OLLAMA_HOST.

Uses the standard library only (plus the SRS Agent itself).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

PREFIX = "@@tracelight "


def emit(event: str, **data) -> None:
    sys.stdout.write(PREFIX + json.dumps({"event": event, **data}, default=str, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _requirement_dict(requirement):
    return requirement.model_dump(mode="json") if hasattr(requirement, "model_dump") else dict(requirement)


class EventProgress:
    """SRS Agent progress callback → JSON events (and the candidate review list)."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.review_items = []
        self.decisions = []

    def __call__(self, event, payload):
        if event == "stage":
            emit("stage", message=payload.get("message", ""))
        elif event == "segmentation":
            emit("segmentation", candidates=payload.get("candidates"), labelled=payload.get("labelled"),
                 skipped_sections=len(payload.get("skipped_sections") or []),
                 skipped_tables=len(payload.get("skipped_tables") or []),
                 warnings=payload.get("warnings") or [])
        elif event == "candidates":
            cands = payload.get("candidates") or []
            _dump(self.out_dir / "candidates.json", cands)
            conf = {}
            for c in cands:
                key = c.get("detection_confidence", "high")
                conf[key] = conf.get(key, 0) + 1
            emit("candidates", count=len(cands), confidence=conf)
        elif event == "judge_batch_start":
            emit("judge_batch_start", batch=payload.get("batch"), batches=payload.get("batches"),
                 candidates=payload.get("candidates"))
        elif event == "judge_batch_done":
            decisions = payload.get("decisions") or []
            self.decisions.extend(decisions)
            self.review_items.extend(d for d in decisions if d.get("decision") == "uncertain")
            emit("judge_batch_done", batch=payload.get("batch"), batches=payload.get("batches"),
                 kept=payload.get("kept_count"), discarded=payload.get("discarded_count"),
                 uncertain=payload.get("uncertain_count", 0), failure=payload.get("failure"),
                 decisions=[{k: d.get(k) for k in ("candidate_id", "decision", "confidence", "reason", "source")}
                            for d in decisions])
        elif event == "requirement_start":
            emit("requirement_start", index=payload.get("index"), total=payload.get("total"),
                 requirement_id=payload.get("requirement_id"))
        elif event == "requirement_done":
            req = _requirement_dict(payload["requirement"])
            emit("requirement_done", index=payload.get("index"), total=payload.get("total"),
                 requirement_id=req.get("requirement_id"), title=req.get("title"),
                 review_required=req.get("review_required", False))
        elif event == "requirement_error":
            emit("requirement_error", index=payload.get("index"), error=payload.get("error"))


def _document_blocks(app, input_path: str):
    """The parsed document as JSON-friendly blocks, for showing source context."""
    from processors.segmenter import block_to_dict, blocks_from_pdf, blocks_from_text

    adapted = app.InputAdapter().adapt(input_path)
    kind = adapted["type"]
    document = app.parse_input(adapted["data"], kind)
    if kind == "docx":
        blocks = document.get("blocks") or []
    elif kind == "pdf":
        blocks = [block_to_dict(b) for b in blocks_from_pdf(document)]
    else:
        blocks = [block_to_dict(b) for b in blocks_from_text(document.get("text", ""))]
    return kind, document, blocks


def run_extract(app, args, out_dir: Path) -> dict:
    progress = EventProgress(out_dir)
    report: dict = {}
    kind, _, blocks = _document_blocks(app, args.input)
    _dump(out_dir / "document_blocks.json", {"type": kind, "blocks": blocks})
    started = time.monotonic()
    requirements = app.main(args.input, progress_callback=progress, report=report)
    reqs = [_requirement_dict(r) for r in requirements]
    report["candidate_review"] = progress.review_items
    report["judge_decisions"] = progress.decisions
    _dump(out_dir / "requirements.json", reqs)
    _dump(out_dir / "extraction_report.json", report)
    return {"requirements": len(reqs), "uncertain": len(progress.review_items),
            "failed": len(report.get("extraction_failures") or []),
            "seconds": round(time.monotonic() - started, 1)}


def run_detect(app, args, out_dir: Path) -> dict:
    kind, document, blocks = _document_blocks(app, args.input)
    _dump(out_dir / "document_blocks.json", {"type": kind, "blocks": blocks})
    detector = app.RequirementDetector()
    if kind in ("pdf", "docx"):
        candidates = detector.detect(document, kind)
    else:
        candidates = detector.detect_text(document["text"])
    _dump(out_dir / "candidates.json", candidates)
    seg = detector.last_report
    report = {"segmentation": {"skipped_sections": seg.skipped_sections, "skipped_tables": seg.skipped_tables,
                               "warnings": seg.warnings} if seg is not None else {},
              "counts": {"candidates": len(candidates)}}
    _dump(out_dir / "extraction_report.json", report)
    emit("candidates", count=len(candidates),
         labelled=sum(1 for c in candidates if c.get("source_requirement_id")))
    return {"candidates": len(candidates)}


def run_extract_candidates(app, args, out_dir: Path) -> dict:
    candidates = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    progress = EventProgress(out_dir)
    config = app.LLMConfig()
    agent = app.SRSAgent(llm_provider=app.create_provider(config))
    requirements = agent.extract(candidates, progress_callback=progress)
    reqs = [_requirement_dict(r) for r in requirements]
    _dump(out_dir / "requirements.json", reqs)
    _dump(out_dir / "extraction_report.json", {"extraction_failures": agent.failures,
                                               "counts": {"candidates": len(candidates),
                                                          "extracted": len(reqs),
                                                          "failed": len(agent.failures)}})
    return {"requirements": len(reqs), "failed": len(agent.failures)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mode", choices=["extract", "detect", "extract-candidates"])
    ap.add_argument("--srsagent-dir", required=True, help="SRS Agent project folder")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--input", help="SRS file (.docx / .pdf / .md / .txt) for extract and detect")
    ap.add_argument("--candidates", help="JSON list of candidates for extract-candidates")
    args = ap.parse_args(argv)
    if args.mode in ("extract", "detect") and not args.input:
        ap.error("--input is required for extract and detect")
    if args.mode == "extract-candidates" and not args.candidates:
        ap.error("--candidates is required for extract-candidates")

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.input:
        # The SRS Agent treats a string that is not an existing file as literal
        # SRS text, so a missing file must be caught here.
        if not Path(args.input).is_file():
            emit("error", message=f"SRS file not found: {args.input}")
            return 1
        args.input = str(Path(args.input).resolve())
    sys.path.insert(0, str(Path(args.srsagent_dir).resolve()))
    try:
        import app
        emit("started", mode=args.mode, input=args.input,
             model=os.environ.get("LLM_MODEL"), judge_model=os.environ.get("JUDGE_MODEL"))
        runner = {"extract": run_extract, "detect": run_detect,
                  "extract-candidates": run_extract_candidates}[args.mode]
        result = runner(app, args, out_dir)
        emit("finished", out_dir=str(out_dir), **result)
    except BaseException as exc:          # report anything, including KeyboardInterrupt
        emit("error", message=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
