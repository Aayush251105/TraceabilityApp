"""
HTTP API, driven through a real run (DocAgent placeholder mode, fake SRS
Agent and verifier LLM — see test_runner.py), on the test database.
"""

import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tracelight.api import create_app

from test_runner import CART, FakeSRS, env, make_orch, pytestmark  # noqa: F401  (fixture + markers)


@pytest.fixture()
def api(env):
    orch = make_orch(env)
    with TestClient(create_app(orch, poll_seconds=0.05)) as client:
        client.env = env
        client.orch = orch
        yield client


def create(api, **form):
    data = {"source_kind": "folder", "folder": str(api.env["repo"]), **form}
    with open(api.env["srs"], "rb") as fh:
        r = api.post("/api/runs", data=data, files={"srs": ("Shop_SRS.md", fh, "text/markdown")})
    assert r.status_code == 201, r.text
    return r.json()


def wait_for(api, run_id, statuses, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = api.get(f"/api/runs/{run_id}").json()
        if run["status"] in statuses and not run["active"]:
            return run
        time.sleep(0.3)
    raise AssertionError(f"run {run_id} did not reach {statuses}: {run['status']}")


def test_run_review_and_complete_over_http(api):
    created = create(api)
    run_id = created["run_id"]
    assert created["status"] in ("queued", "running") and created["srs_filename"] == "Shop_SRS.md"

    run = wait_for(api, run_id, ("paused",))
    assert run["review"]["open"] == 1
    rail = {r["group"]: r["status"] for r in run["rail"]}
    assert rail["ingest"] == "done" and rail["review"] == "waiting" and rail["verify"] == "queued"
    lanes = {l["lane"]: l for l in run["lanes"]}
    assert [s["stage"] for s in lanes["A"]["stages"]] == ["fetch", "docstrings", "index_code"]
    assert any("Docstring written" in e["message"] for e in lanes["A"]["log"])
    assert 0.4 < run["progress"]["fraction"] < 0.8

    review = api.get(f"/api/runs/{run_id}/review").json()
    assert review["ready"] and review["status"] == "waiting"
    assert [i["item_key"] for i in review["items"]] == ["cand:C-0005"]
    assert {r["requirement_id"] for r in review["requirements"]} == {"FR-001", "FR-002", "FR-003", "FR-004"}
    doc = api.get(f"/api/runs/{run_id}/document").json()
    assert doc["type"] == "text" and doc["blocks"][1]["text"].startswith("The system shall add")

    # completing with an open item is refused, naming the item
    r = api.post(f"/api/runs/{run_id}/review/complete")
    assert r.status_code == 409 and r.json()["keys"] == ["cand:C-0005"]

    targets = api.get(f"/api/runs/{run_id}/review/targets", params={"item": "cand:C-0005"}).json()["targets"]
    assert len(targets) == 4 and targets[0]["similarity"] >= targets[-1]["similarity"]

    key = "cand:C-0005"
    assert api.put(f"/api/runs/{run_id}/review/items/{key}", json={"resolution": "nonsense"}).status_code == 400
    assert api.put(f"/api/runs/{run_id}/review/items/{key}", json={"resolution": "merged"}).status_code == 400
    assert api.put(f"/api/runs/{run_id}/review/items/missing", json={"resolution": "kept"}).status_code == 404
    r = api.put(f"/api/runs/{run_id}/review/items/{key}", json={"resolution": "discarded"})
    assert r.json()["counts"]["open"] == 0
    assert api.delete(f"/api/runs/{run_id}/review/items/{key}").json()["counts"]["open"] == 1     # undo
    api.put(f"/api/runs/{run_id}/review/items/{key}", json={"resolution": "discarded"})

    r = api.post(f"/api/runs/{run_id}/review/complete")
    assert r.status_code == 200 and r.json()["requirements"] == 4
    run = wait_for(api, run_id, ("completed",))
    assert run["summary"]["requirements"] == 4
    assert run["summary"]["status_counts"]["not_supported_by_candidate"] == 1
    assert run["progress"]["fraction"] == 1.0
    assert api.put(f"/api/runs/{run_id}/review/items/{key}", json={"resolution": "kept"}).status_code == 409

    listed = api.get("/api/runs").json()["runs"]
    assert listed[0]["run_id"] == run_id and listed[0]["status"] == "completed"

    events = api.get(f"/api/runs/{run_id}/events", params={"lane": "B"}).json()["events"]
    assert events and all(e["lane"] == "B" for e in events)
    later = api.get(f"/api/runs/{run_id}/events", params={"after": events[-1]["event_id"]}).json()["events"]
    assert all(e["event_id"] > events[-1]["event_id"] for e in later)

    assert api.post(f"/api/runs/{run_id}/cancel").status_code == 409          # already completed
    assert api.post(f"/api/runs/{run_id}/resume").status_code == 409


def test_bulk_skip_and_cancel_paused(api):
    run_id = create(api)["run_id"]
    wait_for(api, run_id, ("paused",))
    r = api.post(f"/api/runs/{run_id}/review/bulk", json={"keys": ["cand:C-0005", "nope"], "resolution": "kept"})
    assert r.json()["resolved"] == 1 and r.json()["missing"] == ["nope"]
    assert api.post(f"/api/runs/{run_id}/review/bulk",
                    json={"keys": ["cand:C-0005"], "resolution": "merged"}).status_code == 400
    api.delete(f"/api/runs/{run_id}/review/items/cand:C-0005")
    assert api.post(f"/api/runs/{run_id}/review/skip-remaining").json()["skipped"] == 1
    assert api.post(f"/api/runs/{run_id}/cancel").json()["cancelling"]
    assert api.get(f"/api/runs/{run_id}").json()["status"] == "cancelled"


def test_stream_sends_run_snapshot_and_log(api):
    run_id = create(api, start="false")["run_id"]
    with api.stream("GET", f"/api/runs/{run_id}/stream") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        seen = set()
        for line in r.iter_lines():
            if line.startswith("event: "):
                seen.add(line[7:])
            if {"log", "run"} <= seen:
                break
    assert {"log", "run"} <= seen


def test_delete_run_removes_files_and_traceability_rows(api):
    run_id = create(api)["run_id"]
    run = wait_for(api, run_id, ("paused",))
    workdir = Path(api.orch.store().get_run(run_id)["workdir"])
    assert workdir.exists()
    api.post(f"/api/runs/{run_id}/cancel")
    assert api.delete(f"/api/runs/{run_id}").json()["deleted"]
    assert api.get(f"/api/runs/{run_id}").status_code == 404
    assert not workdir.exists()
    import psycopg2
    cfg = api.env["cfg"]
    with psycopg2.connect(cfg.build_dsn()) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {cfg.table_repositories} WHERE repo_id = %s", (run["repo_id"],))
        assert cur.fetchone()[0] == 0


def test_create_run_errors(api, tmp_path):
    with open(api.env["srs"], "rb") as fh:
        r = api.post("/api/runs", data={"source_kind": "folder", "folder": str(tmp_path / "nope")},
                     files={"srs": ("Shop_SRS.md", fh, "text/markdown")})
    assert r.status_code == 400 and "Folder not found" in r.json()["detail"]
    r = api.post("/api/runs", data={"source_kind": "git", "git_url": "git@github.com:a/b.git"},
                 files={"srs": ("s.md", b"# x", "text/markdown")})
    assert r.status_code == 400 and "https://" in r.json()["detail"]
    r = api.post("/api/runs", data={"source_kind": "folder", "folder": str(api.env["repo"]), "overrides": "{bad"},
                 files={"srs": ("s.md", b"# x", "text/markdown")})
    assert r.status_code == 400
    r = api.post("/api/runs", data={"source_kind": "folder", "folder": str(api.env["repo"])},
                 files={"srs": ("s.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400 and "Unsupported" in r.json()["detail"]
    assert api.get("/api/runs/999999").status_code == 404


def test_create_from_zip_with_overrides(api):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("shop-main/shop/__init__.py", "")
        zf.writestr("shop-main/shop/cart.py", CART)
    with open(api.env["srs"], "rb") as fh:
        r = api.post("/api/runs", data={"source_kind": "zip", "start": "false",
                                        "overrides": json.dumps({"models": {"verifier": "qwen2.5-coder:14b"}})},
                     files={"srs": ("Shop_SRS.md", fh, "text/markdown"),
                            "zip": ("shop-main.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["models"]["verifier"] == "qwen2.5-coder:14b" and run["status"] == "queued"
    assert run["source"]["kind"] == "zip" and run["source"]["ref"].endswith("shop-main.zip")


def test_inspect(api, tmp_path):
    r = api.post("/api/inspect", data={"source_kind": "folder", "folder": str(api.env["repo"])}).json()
    assert r["stats"]["components"] == 5 and r["warnings"] == []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.md", "no code")
    r = api.post("/api/inspect", data={"source_kind": "zip"},
                 files={"zip": ("docs.zip", buf.getvalue(), "application/zip")}).json()
    assert r["warnings"][0]["code"] == "no_python"
    r = api.post("/api/inspect", data={"source_kind": "git", "git_url": "https://github.com/owner/repo"}).json()
    assert r["url"] == "https://github.com/owner/repo" and r["stats"] is None
    assert api.post("/api/inspect", data={"source_kind": "git", "git_url": "file:///x"}).status_code == 400


def test_settings_and_health(api):
    s = api.get("/api/settings").json()
    assert s["settings"]["verification"]["claims"] == "rules"          # saved by the fixture
    r = api.put("/api/settings", json={"models": {"verifier": "qwen2.5-coder:14b"},
                                       "ollama_host": "http://127.0.0.1:9"}).json()
    assert r["settings"]["models"]["verifier"] == "qwen2.5-coder:14b"
    assert r["settings"]["models"]["srs"] == "llama3.1"
    assert api.put("/api/settings", json={"nope": 1}).status_code == 400
    h = api.get("/api/health").json()
    assert h["database"]["ok"] and not h["ollama"]["ok"]
    assert h["models"]["verifier"] == {"name": "qwen2.5-coder:14b", "pulled": None}
    assert h["agents"]["docagent"]["dir_ok"]
