"""
Run DocAgent's docstring generation and report progress as JSON events.

Executed with **DocAgent's own Python** (its virtual environment), not the
backend's.  It imports DocAgent unchanged and replaces its terminal
visualizers (progress bar, agent ASCII art, screen clearing) with one-line
JSON events on stdout:

    @@tracelight {"event": "plan", "total": 41, "types": {...}}
    @@tracelight {"event": "component", "id": "...", "status": "processing", ...}
    @@tracelight {"event": "agent", "agent": "writer", "message": "Generating docstring..."}
    @@tracelight {"event": "graph_saved", "path": "..."}
    @@tracelight {"event": "finished", ...} | {"event": "error", ...}

Everything else DocAgent prints (its log lines) passes through as plain text.
DocAgent edits the files under --repo-path in place, so the orchestrator
passes a working copy.  The dependency graph is written under --workdir.

Uses the standard library only (it runs inside another project's venv).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

PREFIX = "@@tracelight "


def emit(event: str, **data) -> None:
    sys.stdout.write(PREFIX + json.dumps({"event": event, **data}, default=str) + "\n")
    sys.stdout.flush()


def _patch_visualizers(workdir: str) -> None:
    """Replace DocAgent's terminal visualizers with event emitters."""
    import importlib

    def progress_initialize(self):
        self.start_time = time.time()
        self._tl_started = set()
        types = {}
        for cid in self.sorted_order:
            comp = self.components.get(cid)
            if comp is not None:
                types[comp.component_type] = types.get(comp.component_type, 0) + 1
        emit("plan", total=len(self.sorted_order), types=types)

    def progress_update(self, component_id=None, status="processing"):
        if component_id is None:
            return
        comp = self.components.get(component_id)
        started = getattr(self, "_tl_started", set())
        if status == "processing":
            started.add(component_id)
            self.current = component_id
        else:
            self.processed.add(component_id)
        outcome = status
        if status == "completed" and component_id not in started:
            outcome = "skipped"            # completed without being processed
        emit("component", id=component_id, status=outcome,
             type=getattr(comp, "component_type", None),
             file=getattr(comp, "relative_path", None) or getattr(comp, "file_path", None),
             done=len(self.processed), total=len(self.sorted_order))

    def progress_finalize(self):
        emit("finished", processed=len(self.processed), total=len(self.sorted_order),
             seconds=round(time.time() - self.start_time, 1))

    def silent(self, *args, **kwargs):
        return None

    def status_update(self, active_agent, status_message=""):
        self.active_agent = active_agent
        emit("agent", agent=active_agent, message=status_message,
             component=getattr(self, "_current_component", None))

    def status_set_component(self, focal_component, file_path):
        self._current_component = focal_component
        self._current_file = file_path

    for name in ("src.visualizer.progress", "visualizer.progress"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        mod.ProgressVisualizer.initialize = progress_initialize
        mod.ProgressVisualizer.update = progress_update
        mod.ProgressVisualizer.finalize = progress_finalize
        mod.ProgressVisualizer.show_dependency_stats = silent
    for name in ("src.visualizer.status", "visualizer.status"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        mod.StatusVisualizer.update = status_update
        mod.StatusVisualizer.set_current_component = status_set_component
        mod.StatusVisualizer._clear_screen = silent
        mod.StatusVisualizer.reset = silent

    parser_mod = importlib.import_module("src.dependency_analyzer")
    cls = parser_mod.DependencyParser
    original_save = cls.save_dependency_graph

    def save_and_report(self, output_path):
        # DocAgent writes output/dependency_graphs/<repo>_dependency_graph.json relative to
        # its own folder; each run keeps its graph in its run folder instead.
        target = os.path.join(workdir, "output", "dependency_graphs", os.path.basename(output_path))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        result = original_save(self, target)
        components = getattr(self, "components", {}) or {}
        emit("graph_saved", path=os.path.abspath(target), components=len(components))
        return result

    cls.save_dependency_graph = save_and_report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--docagent-dir", required=True, help="DocAgent project folder")
    ap.add_argument("--repo-path", required=True, help="working copy to document (edited in place)")
    ap.add_argument("--config-path", required=True, help="DocAgent YAML config")
    ap.add_argument("--workdir", required=True, help="where output/dependency_graphs/ is written")
    ap.add_argument("--test-mode", default="none", choices=["none", "placeholder"],
                    help="placeholder: no LLM calls (placeholder docstrings), for testing")
    ap.add_argument("--overwrite-docstrings", action="store_true")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    docagent_dir = os.path.abspath(args.docagent_dir)
    workdir = os.path.abspath(args.workdir)
    os.makedirs(workdir, exist_ok=True)
    # DocAgent resolves some paths relative to its own folder (its Orchestrator agent
    # loads config/agent_config.yaml without the --config-path), so it runs from there.
    os.chdir(docagent_dir)
    sys.path.insert(0, docagent_dir)
    sys.argv = ["generate_docstrings.py", "--repo-path", os.path.abspath(args.repo_path),
                "--config-path", os.path.abspath(args.config_path), "--test-mode", args.test_mode]
    if args.overwrite_docstrings:
        sys.argv.append("--overwrite-docstrings")

    try:
        import generate_docstrings
        _patch_visualizers(workdir)
        emit("started", repo_path=os.path.abspath(args.repo_path), test_mode=args.test_mode)
        generate_docstrings.main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            emit("error", message=f"DocAgent exited with code {exc.code}")
            return int(exc.code) if isinstance(exc.code, int) else 1
    except BaseException as exc:          # report anything, including KeyboardInterrupt
        emit("error", message=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
