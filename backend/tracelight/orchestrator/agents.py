"""
Launch DocAgent and the SRS Agent as subprocesses (each in its own virtual
environment) through the wrapper scripts in tracelight/runners/, and turn
their output into events.

Output protocol: a line starting with "@@tracelight " carries one JSON event
(see the runner scripts); every other line is a plain log line.  All output
is also written to a log file in the run folder.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..settings import AppPaths

PREFIX = "@@tracelight "

EventHandler = Callable[[Dict[str, Any]], None]
LogHandler = Callable[[str], None]


class AgentError(RuntimeError):
    """The agent process failed (non-zero exit or an error event)."""


class AgentCancelled(RuntimeError):
    """The agent process was stopped because the run was cancelled."""


def parse_line(line: str) -> Optional[Dict[str, Any]]:
    """The event carried by an output line, or None for a plain log line."""
    if not line.startswith(PREFIX):
        return None
    try:
        event = json.loads(line[len(PREFIX):])
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) and "event" in event else None


@dataclass
class AgentResult:
    returncode: int
    events: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def last(self, name: str) -> Optional[Dict[str, Any]]:
        return next((e for e in reversed(self.events) if e.get("event") == name), None)


def run_agent(cmd: List[str], *, cwd: Path, env: Dict[str, str], log_path: Path,
              on_event: Optional[EventHandler] = None, on_log: Optional[LogHandler] = None,
              cancel: Optional[threading.Event] = None, poll_seconds: float = 0.5) -> AgentResult:
    """
    Run one agent process to completion, streaming its output.

    Raises AgentCancelled if `cancel` is set while it runs (the process is
    terminated), AgentError if it exits non-zero or reports an error event.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    result = AgentResult(returncode=-1)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"$ {' '.join(cmd)}\n")
        log.flush()
        proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                encoding="utf-8", errors="replace", bufsize=1,
                                creationflags=creationflags)

        def pump() -> None:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                log.write(line + "\n")
                log.flush()
                event = parse_line(line)
                if event is not None:
                    result.events.append(event)
                    if event["event"] == "error":
                        result.error = event.get("message")
                    if on_event:
                        on_event(event)
                elif line.strip() and on_log:
                    on_log(line)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        cancelled = False
        while True:
            try:
                proc.wait(timeout=poll_seconds)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    _stop(proc)
                    break
        reader.join(timeout=10)
        result.returncode = proc.returncode if proc.returncode is not None else -1
        log.write(f"[exit {result.returncode}]\n")

    if cancelled:
        raise AgentCancelled("stopped by user")
    if result.returncode != 0 or result.error:
        raise AgentError(result.error or f"exited with code {result.returncode} (see {log_path.name})")
    return result


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _base_env(extra: Dict[str, str]) -> Dict[str, str]:
    env = dict(os.environ)
    # The agents' own venvs must not pick up the backend's environment.
    for key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"):
        env.pop(key, None)
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    env.update(extra)
    return env


# ---------------------------------------------------------------------------
# DocAgent
# ---------------------------------------------------------------------------


def docagent_config_yaml(settings: Dict[str, Any]) -> str:
    """DocAgent config for a run (same shape as runs/library_yicoder9b.yaml)."""
    host = settings["ollama_host"].rstrip("/")
    model = settings["models"]["docagent"]
    overwrite = "true" if settings["ingest"].get("overwrite_docstrings", True) else "false"
    return (
        "# Written by Tracelight for this run.\n"
        "llm:\n"
        "  type: ollama\n"
        f"  model: {json.dumps(model)}\n"
        f"  api_base: {json.dumps(host + '/v1')}\n"
        "  api_key: ollama\n"
        "  temperature: 0.1\n"
        "  max_output_tokens: 4096\n"
        "  max_input_tokens: 8000\n"
        "flow_control:\n"
        "  max_reader_search_attempts: 2\n"
        "  max_verifier_rejections: 1\n"
        "  status_sleep_time: 0\n"
        "docstring_options:\n"
        f"  overwrite_docstrings: {overwrite}\n"
    )


def docagent_command(paths: AppPaths, *, repo_path: Path, config_path: Path, workdir: Path,
                     test_mode: str = "none", overwrite: bool = True) -> List[str]:
    cmd = [str(paths.docagent_python), str(paths.runners_dir / "docagent_runner.py"),
           "--docagent-dir", str(paths.docagent_dir), "--repo-path", str(repo_path),
           "--config-path", str(config_path), "--workdir", str(workdir), "--test-mode", test_mode]
    if overwrite:
        cmd.append("--overwrite-docstrings")
    return cmd


def run_docagent(paths: AppPaths, settings: Dict[str, Any], *, repo_path: Path, out_dir: Path,
                 log_path: Path, test_mode: str = "none", **kw: Any) -> AgentResult:
    """Generate docstrings in `repo_path` (edited in place); the graph is written under out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    config_path = out_dir / "docagent_config.yaml"
    config_path.write_text(docagent_config_yaml(settings), encoding="utf-8")
    cmd = docagent_command(paths, repo_path=repo_path, config_path=config_path, workdir=out_dir,
                           test_mode=test_mode,
                           overwrite=settings["ingest"].get("overwrite_docstrings", True))
    return run_agent(cmd, cwd=out_dir, env=_base_env({}), log_path=log_path, **kw)


# ---------------------------------------------------------------------------
# SRS Agent
# ---------------------------------------------------------------------------


def srs_env(settings: Dict[str, Any]) -> Dict[str, str]:
    return _base_env({
        "LLM_PROVIDER": "ollama",
        "LLM_MODEL": settings["models"]["srs"],
        "JUDGE_MODEL": settings["models"]["judge"],
        "OLLAMA_HOST": settings["ollama_host"],
    })


def srs_command(paths: AppPaths, mode: str, *, out_dir: Path, input_path: Optional[Path] = None,
                candidates_path: Optional[Path] = None) -> List[str]:
    cmd = [str(paths.srsagent_python), str(paths.runners_dir / "srs_runner.py"), mode,
           "--srsagent-dir", str(paths.srsagent_dir), "--out-dir", str(out_dir)]
    if input_path is not None:
        cmd += ["--input", str(input_path)]
    if candidates_path is not None:
        cmd += ["--candidates", str(candidates_path)]
    return cmd


def run_srs(paths: AppPaths, settings: Dict[str, Any], mode: str, *, out_dir: Path, log_path: Path,
            input_path: Optional[Path] = None, candidates_path: Optional[Path] = None,
            **kw: Any) -> AgentResult:
    cmd = srs_command(paths, mode, out_dir=out_dir, input_path=input_path,
                      candidates_path=candidates_path)
    return run_agent(cmd, cwd=paths.srsagent_dir, env=srs_env(settings), log_path=log_path, **kw)


def check_agents(paths: AppPaths) -> Dict[str, Dict[str, Any]]:
    """Which agent folders / Python interpreters exist (for the Settings page and startup)."""
    out = {}
    for name, folder, python, marker in (
            ("docagent", paths.docagent_dir, paths.docagent_python, "generate_docstrings.py"),
            ("srsagent", paths.srsagent_dir, paths.srsagent_python, "app.py")):
        out[name] = {"dir": str(folder), "python": str(python),
                     "dir_ok": (folder / marker).exists(), "python_ok": python.exists()}
    return out
