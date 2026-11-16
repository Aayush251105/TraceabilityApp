"""
Agent launching: the output protocol, process handling (errors, cancel), the
generated DocAgent config, and — when the agents' virtual environments are
present — the real wrappers on the library dataset without any LLM
(DocAgent placeholder mode, SRS Agent detect mode).
"""

import json
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from tracelight.orchestrator.agents import (AgentCancelled, AgentError, PREFIX, _base_env,
                                            check_agents, docagent_command, docagent_config_yaml,
                                            parse_line, run_agent, run_docagent, run_srs,
                                            srs_command, srs_env)
from tracelight.settings import DEFAULTS, AppPaths, effective_settings, SettingsStore

PATHS = AppPaths.from_env()
LIBRARY = PATHS.workspace / "library_traceability_dataset"


def _script(tmp_path, body: str) -> list:
    path = tmp_path / "fake_agent.py"
    path.write_text("import json, sys, time\n"
                    f"P = {PREFIX!r}\n"
                    "def emit(e, **d): print(P + json.dumps({'event': e, **d}), flush=True)\n"
                    + body, encoding="utf-8")
    return [sys.executable, str(path)]


def _run(tmp_path, body, **kw):
    events, logs = [], []
    result = run_agent(_script(tmp_path, body), cwd=tmp_path, env=_base_env({}),
                       log_path=tmp_path / "logs" / "agent.log",
                       on_event=events.append, on_log=logs.append, **kw)
    return result, events, logs


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


def test_parse_line():
    assert parse_line(PREFIX + '{"event": "plan", "total": 3}') == {"event": "plan", "total": 3}
    assert parse_line("2026-10-31 - INFO - Processing method: a.b") is None
    assert parse_line(PREFIX + "{broken") is None
    assert parse_line(PREFIX + '{"no_event": 1}') is None
    assert parse_line(PREFIX + "[1, 2]") is None


# ---------------------------------------------------------------------------
# Process handling
# ---------------------------------------------------------------------------


def test_events_and_logs_are_split_and_logged(tmp_path):
    result, events, logs = _run(tmp_path, "emit('plan', total=2)\nprint('plain log line')\n"
                                          "print('', flush=True)\nemit('finished', processed=2)\n")
    assert result.returncode == 0
    assert [e["event"] for e in events] == ["plan", "finished"]
    assert logs == ["plain log line"]                       # blank lines dropped
    assert result.last("finished") == {"event": "finished", "processed": 2}
    log = (tmp_path / "logs" / "agent.log").read_text(encoding="utf-8")
    assert "plain log line" in log and "[exit 0]" in log


def test_stderr_is_captured(tmp_path):
    _, _, logs = _run(tmp_path, "print('to stderr', file=sys.stderr, flush=True)\n")
    assert logs == ["to stderr"]


def test_unicode_output(tmp_path):
    _, events, logs = _run(tmp_path, "print('Judge: p.7 \\u00a73.4 \\u2192 uncertain \\u2713')\n"
                                     "emit('stage', message='\\u201cquoted\\u201d')\n")
    assert logs == ["Judge: p.7 §3.4 → uncertain ✓"]
    assert events[0]["message"] == "“quoted”"


def test_nonzero_exit_raises(tmp_path):
    with pytest.raises(AgentError, match="exited with code 3"):
        _run(tmp_path, "sys.exit(3)\n")


def test_error_event_raises_with_message(tmp_path):
    with pytest.raises(AgentError, match="ConnectionError: Ollama unreachable"):
        _run(tmp_path, "emit('error', message='ConnectionError: Ollama unreachable')\nsys.exit(1)\n")


def test_error_event_raises_even_with_zero_exit(tmp_path):
    with pytest.raises(AgentError, match="bad"):
        _run(tmp_path, "emit('error', message='bad')\n")


def test_cancel_stops_the_process(tmp_path):
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(AgentCancelled):
        _run(tmp_path, "emit('plan', total=1)\ntime.sleep(60)\n", cancel=cancel, poll_seconds=0.1)
    assert time.monotonic() - started < 20


def test_env_isolates_agent_venv(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/backend/venv")
    monkeypatch.setenv("PYTHONPATH", "/backend/src")
    env = _base_env({"X": "1"})
    assert "VIRTUAL_ENV" not in env and "PYTHONPATH" not in env
    assert env["PYTHONIOENCODING"] == "utf-8" and env["X"] == "1"


# ---------------------------------------------------------------------------
# Commands and config
# ---------------------------------------------------------------------------


def test_docagent_config_uses_run_settings(tmp_path):
    settings = effective_settings(SettingsStore(tmp_path / "s.json"),
                                  {"models": {"docagent": "qwen2.5-coder:7b"},
                                   "ollama_host": "http://gpu-box:11434/",
                                   "ingest": {"overwrite_docstrings": False}})
    text = docagent_config_yaml(settings)
    assert 'model: "qwen2.5-coder:7b"' in text
    assert 'api_base: "http://gpu-box:11434/v1"' in text
    assert "overwrite_docstrings: false" in text
    yaml = pytest.importorskip("yaml")
    parsed = yaml.safe_load(text)
    assert parsed["llm"]["model"] == "qwen2.5-coder:7b" and parsed["llm"]["type"] == "ollama"


def test_commands(tmp_path):
    cmd = docagent_command(PATHS, repo_path=tmp_path / "work", config_path=tmp_path / "c.yaml",
                           workdir=tmp_path, test_mode="placeholder", overwrite=False)
    assert cmd[0] == str(PATHS.docagent_python) and cmd[1].endswith("docagent_runner.py")
    assert "--overwrite-docstrings" not in cmd and cmd[cmd.index("--test-mode") + 1] == "placeholder"
    cmd = srs_command(PATHS, "extract-candidates", out_dir=tmp_path, candidates_path=tmp_path / "c.json")
    assert cmd[2] == "extract-candidates" and "--input" not in cmd and "--candidates" in cmd


def test_srs_env_sets_models():
    env = srs_env(DEFAULTS)
    assert env["LLM_MODEL"] == "llama3.1" and env["JUDGE_MODEL"] == "qwen2.5:3b"
    assert env["OLLAMA_HOST"] == DEFAULTS["ollama_host"]


def test_check_agents_reports_missing(tmp_path):
    paths = AppPaths(workspace=tmp_path, data_dir=tmp_path, docagent_dir=tmp_path / "DocAgent",
                     docagent_python=tmp_path / "nope.exe", srsagent_dir=tmp_path / "SRSAgent",
                     srsagent_python=tmp_path / "nope.exe")
    status = check_agents(paths)
    assert not status["docagent"]["dir_ok"] and not status["srsagent"]["python_ok"]


# ---------------------------------------------------------------------------
# Real agents, no LLM (skipped when the agent venvs or the dataset are missing)
# ---------------------------------------------------------------------------

_agents = check_agents(PATHS)
needs_docagent = pytest.mark.skipif(
    not (_agents["docagent"]["dir_ok"] and _agents["docagent"]["python_ok"] and LIBRARY.exists()),
    reason="DocAgent venv or library dataset not available")
needs_srsagent = pytest.mark.skipif(
    not (_agents["srsagent"]["dir_ok"] and _agents["srsagent"]["python_ok"] and LIBRARY.exists()),
    reason="SRS Agent venv or library dataset not available")


@needs_docagent
def test_docagent_wrapper_placeholder_mode(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(LIBRARY / "codebase", work, ignore=shutil.ignore_patterns("__pycache__"))
    events = []
    result = run_docagent(PATHS, DEFAULTS, repo_path=work, out_dir=tmp_path / "docagent",
                          log_path=tmp_path / "docagent.log", test_mode="placeholder",
                          on_event=events.append)
    plan = result.last("plan")
    assert plan["total"] == 41 and plan["types"] == {"method": 27, "class": 5, "function": 9}
    comps = [e for e in events if e["event"] == "component"]
    finals = [e for e in comps if e["status"] != "processing"]
    assert len(finals) == 41 and finals[-1]["done"] == 41
    assert sum(e["status"] == "skipped" for e in finals) == 5          # the __init__ methods
    graph = Path(result.last("graph_saved")["path"])
    data = json.loads(graph.read_text(encoding="utf-8"))
    assert len(data["components"]) == 41
    assert result.last("finished")["processed"] == 41
    # placeholder docstrings were written into the working copy, not the dataset
    assert (LIBRARY / "codebase").exists()


@needs_srsagent
def test_srs_wrapper_detect_mode(tmp_path):
    srs = LIBRARY / "srs" / "SRS_Library_Management_System.docx"
    out = tmp_path / "srs"
    result = run_srs(PATHS, DEFAULTS, "detect", out_dir=out, log_path=tmp_path / "srs.log", input_path=srs)
    assert result.last("finished")["candidates"] == 40
    candidates = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
    ids = {c.get("source_requirement_id") for c in candidates}
    assert {"FR-001", "FR-036"} <= ids
    blocks = json.loads((out / "document_blocks.json").read_text(encoding="utf-8"))
    assert blocks["type"] == "docx"
    assert {b["kind"] for b in blocks["blocks"]} >= {"heading", "paragraph", "list_item"}
    report = json.loads((out / "extraction_report.json").read_text(encoding="utf-8"))
    assert report["segmentation"]["skipped_sections"]


@needs_srsagent
def test_srs_wrapper_reports_a_missing_file(tmp_path):
    with pytest.raises(AgentError):
        run_srs(PATHS, DEFAULTS, "detect", out_dir=tmp_path / "srs", log_path=tmp_path / "srs.log",
                input_path=tmp_path / "missing.docx")


@needs_docagent
def test_docagent_wrapper_real_mode_initialises_agents(tmp_path):
    """Real (LLM) mode builds DocAgent's agents, which read config relative to DocAgent's folder.
    A repo without functions needs no LLM call, so this runs without Ollama."""
    repo = tmp_path / "work"
    repo.mkdir()
    (repo / "settings.py").write_text("DEBUG = True\n", encoding="utf-8")
    out = tmp_path / "docagent"
    result = run_docagent(PATHS, DEFAULTS, repo_path=repo, out_dir=out, log_path=tmp_path / "docagent.log",
                          test_mode="none")
    assert result.last("plan")["total"] == 0 and result.last("finished") is not None
    graph = Path(result.last("graph_saved")["path"])
    assert graph.parent == out / "output" / "dependency_graphs"      # in the run folder, not DocAgent/output
    assert graph.exists()
