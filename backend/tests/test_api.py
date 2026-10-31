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
    db = h["database"]
    assert db["connection"].startswith("postgresql://") and "password" not in json.dumps(db).lower()
    assert db["pgvector"] and db["bytes"] > 0 and db["latency_ms"] >= 0
    assert h["embeddings"]["local"] is True
    assert api.get("/api/health", params={"host": "http://127.0.0.1:9"}).json()["ollama_host"] == "http://127.0.0.1:9"
    assert api.get("/api/health", params={"host": "ftp://x"}).status_code == 400
    assert h["models"]["verifier"] == {"name": "qwen2.5-coder:14b", "pulled": None}
    assert h["agents"]["docagent"]["dir_ok"]


# ---------------------------------------------------------------------------
# Results (6b)
# ---------------------------------------------------------------------------


@pytest.fixture()
def done_run(api):
    run_id = create(api, start="false")["run_id"]
    assert api.orch.execute(run_id, auto_approve=True) == "completed"
    return run_id


def test_results_table_and_summary(api, done_run):
    r = api.get(f"/api/runs/{done_run}/results").json()
    assert r["ready"]
    s = r["summary"]
    assert s["requirements"] == 5 and s["pending"] == 0
    assert s["counts"]["not_supported_by_candidate"] == 1 and s["likely_not_implemented"] == 1
    assert s["unreviewed"] == 1 and s["components"]["total"] == 5
    rows = {x["requirement_id"]: x for x in r["requirements"]}
    assert rows["FR-004"]["verdict"] == {"status": "not_supported_by_candidate", "source": "verifier",
                                         "machine": "not_supported_by_candidate"}
    assert rows["FR-001"]["links"]["direct"] >= 1 and rows["FR-001"]["claims"]["total"] >= 1
    assert [f["code"] for f in rows["REQ-001"]["flags"]] == ["unreviewed", "added_at_review"]


def test_requirement_detail(api, done_run):
    d = api.get(f"/api/runs/{done_run}/requirements/FR-002").json()
    assert d["requirement"]["title"] == "Cart total" and d["verdict"]["status"] == "supported"
    assert d["verification"]["model"] == "fake-verifier"
    comp = d["components"][0]
    assert comp["role"] == "direct" and comp["code"] and comp["code"][0]["n"] == comp["start_line"]
    claim = d["claims"][0]
    assert claim["verdict"] == "supported" and claim["evidence"][0]["quote"]
    assert d["search"] and any(c["mapped"] for c in d["search"])
    assert d["history"][0]["kind"] == "verification"
    assert api.get(f"/api/runs/{done_run}/requirements/FR-999").status_code == 404


def test_override_and_clear(api, done_run):
    url = f"/api/runs/{done_run}/requirements/FR-004/override"
    assert api.post(url, json={"status": "nonsense"}).status_code == 400
    assert api.post(f"/api/runs/{done_run}/requirements/FR-999/override",
                    json={"status": "supported"}).status_code == 404
    r = api.post(url, json={"status": "supported", "note": "export runs in cron, outside this repo"}).json()
    assert r["verdict"]["status"] == "supported" and r["verdict"]["source"] == "human"
    assert r["verdict"]["machine"] == "not_supported_by_candidate"
    summary = api.get(f"/api/runs/{done_run}/results").json()["summary"]
    assert summary["overridden"] == 1 and summary["counts"]["not_supported_by_candidate"] == 0
    d = api.get(f"/api/runs/{done_run}/requirements/FR-004").json()
    assert d["history"][0]["kind"] == "override" and d["history"][0]["note"].startswith("export")
    r = api.post(url, json={"status": "cleared"}).json()
    assert r["verdict"]["status"] == "not_supported_by_candidate" and r["verdict"]["source"] == "verifier"
    rows = {x["requirement_id"]: x for x in api.get(f"/api/runs/{done_run}/results").json()["requirements"]}
    assert rows["FR-004"]["human"] is None
    api.post(url, json={"status": "not_supported_by_candidate", "note": "accepted"})      # confirming = accepting
    rows = {x["requirement_id"]: x for x in api.get(f"/api/runs/{done_run}/results").json()["requirements"]}
    assert rows["FR-004"]["human"] == "Accepted" and rows["FR-004"]["verdict"]["source"] == "human"
    api.post(url, json={"status": "supported", "note": "changed my mind"})
    rows = {x["requirement_id"]: x for x in api.get(f"/api/runs/{done_run}/results").json()["requirements"]}
    assert rows["FR-004"]["human"] == "Overridden"


def test_reverify_selected(api, done_run):
    assert api.post(f"/api/runs/{done_run}/verify", json={"requirement_ids": []}).status_code == 400
    assert api.post(f"/api/runs/{done_run}/verify", json={"requirement_ids": ["FR-999"]}).status_code == 404
    r = api.post(f"/api/runs/{done_run}/verify", json={"requirement_ids": ["FR-001"]})
    assert r.status_code == 200
    deadline = time.monotonic() + 60
    while api.orch.is_active(done_run) and time.monotonic() < deadline:
        time.sleep(0.2)
    d = api.get(f"/api/runs/{done_run}/requirements/FR-001").json()
    assert [h["kind"] for h in d["history"]].count("verification") == 2
    assert api.get(f"/api/runs/{done_run}").json()["status"] == "completed"


def test_reverify_needs_completed_run(api):
    run_id = create(api, start="false")["run_id"]
    assert api.post(f"/api/runs/{run_id}/verify", json={"requirement_ids": ["FR-001"]}).status_code == 409


def test_code_view_component_and_files(api, done_run):
    cv = api.get(f"/api/runs/{done_run}/code").json()
    assert cv["components"] == 5 and 0 < cv["traced"] <= 5
    f = cv["files"][0]
    assert f["path"] == "shop/cart.py" and f["total"] == 5
    traced = next(c for c in f["components"] if c["traced"])
    assert traced["requirements"][0]["verdict"] in ("supported", "partially_supported", "not_supported_by_candidate")
    comp = api.get(f"/api/runs/{done_run}/code/component", params={"component_id": traced["component_id"]}).json()
    assert comp["code"][0]["n"] == comp["start_line"] and comp["requirements"]
    assert api.get(f"/api/runs/{done_run}/code/component", params={"component_id": "nope"}).status_code == 404
    lines = api.get(f"/api/runs/{done_run}/files", params={"path": "shop/cart.py"}).json()["lines"]
    assert "\n".join(l["text"] for l in lines) == CART.rstrip("\n")          # pristine source
    for bad in ("../secret.txt", "/etc/passwd", "C:/Windows/win.ini", "shop/../../x.py"):
        assert api.get(f"/api/runs/{done_run}/files", params={"path": bad}).status_code == 404


def test_exports(api, done_run):
    r = api.get(f"/api/runs/{done_run}/export.csv")
    assert r.headers["content-disposition"].endswith(f'tracelight-run-{done_run}.csv"')
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("requirement_id,title") and len(lines) == 6
    j = api.get(f"/api/runs/{done_run}/export.json").json()
    assert j["summary"]["requirements"] == 5 and len(j["requirements"]) == 5
    assert j["requirements"][0]["claims"]


def test_results_before_tracing(api):
    run_id = create(api, start="false")["run_id"]
    assert api.get(f"/api/runs/{run_id}/results").json() == {"ready": False, "summary": None, "requirements": []}
    assert api.get(f"/api/runs/{run_id}/export.csv").status_code == 409
    assert api.get(f"/api/runs/{run_id}/code").json()["files"] == []


def test_inspect_uses_run_exclusions(api):
    tests_dir = api.env["repo"] / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_cart.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    base = {"source_kind": "folder", "folder": str(api.env["repo"])}
    assert api.post("/api/inspect", data=base).json()["stats"]["components"] == 6
    r = api.post("/api/inspect", data={**base, "exclude_dirs": json.dumps(["tests"])}).json()
    assert r["stats"]["components"] == 5
    assert api.post("/api/inspect", data={**base, "exclude_dirs": "{bad"}).status_code == 400


def test_search_run(api, done_run):
    r = api.get(f"/api/runs/{done_run}/search", params={"q": "discount code"}).json()
    assert r["mode"] == "text" and r["scope"] == {"requirements": True, "code": True}
    assert r["requirements"][0]["requirement_id"] == "FR-003"          # "apply a 10% discount for the code SAVE10"
    top = r["requirements"][0]
    assert top["title"] == "Discount code" and top["verdict"] in ("supported", "partially_supported", "not_supported_by_candidate")
    assert top["components"] and top["components"][0]["role"] == "direct"
    assert any(c["component_id"].endswith("apply_discount") for c in r["components"][:3])
    linked = next(c for c in r["components"] if c["component_id"].endswith("apply_discount"))
    assert linked["requirements"]
    assert linked["match"]["keyword"] or linked["match"]["semantic"]

    by_id = api.get(f"/api/runs/{done_run}/search", params={"q": "FR-004"}).json()
    assert by_id["mode"] == "id" and by_id["requirements"][0]["requirement_id"] == "FR-004"
    assert by_id["requirements"][0]["match"] == {"exact_id": True}
    unknown_id = api.get(f"/api/runs/{done_run}/search", params={"q": "FR-999"}).json()
    assert unknown_id["mode"] == "text"                                # not an ID here: searched as text
    assert api.get(f"/api/runs/{done_run}/search", params={"q": "  "}).json()["requirements"] == []


def test_search_before_indexing(api):
    run_id = create(api, start="false")["run_id"]
    r = api.get(f"/api/runs/{run_id}/search", params={"q": "cart"}).json()
    assert r["scope"] == {"requirements": False, "code": False} and r["components"] == []
