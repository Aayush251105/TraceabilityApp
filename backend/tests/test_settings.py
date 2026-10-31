from tracelight.settings import DEFAULTS, AppPaths, SettingsStore, effective_settings


def test_defaults_when_no_file(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    assert store.load() == DEFAULTS


def test_save_merges_nested_and_keeps_other_defaults(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.save({"models": {"verifier": "qwen2.5-coder:14b"}})
    loaded = store.load()
    assert loaded["models"]["verifier"] == "qwen2.5-coder:14b"
    assert loaded["models"]["srs"] == DEFAULTS["models"]["srs"]
    assert loaded["search"] == DEFAULTS["search"]


def test_save_does_not_mutate_defaults(tmp_path):
    SettingsStore(tmp_path / "settings.json").save({"models": {"srs": "other"}})
    assert DEFAULTS["models"]["srs"] == "llama3.1"


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert SettingsStore(path).load() == DEFAULTS


def test_run_overrides_apply_on_top(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.save({"ingest": {"parallel": False}})
    eff = effective_settings(store, {"models": {"docagent": "qwen2.5-coder:7b"}})
    assert eff["models"]["docagent"] == "qwen2.5-coder:7b"
    assert eff["ingest"]["parallel"] is False


def test_paths_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACELIGHT_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TRACELIGHT_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.delenv("TRACELIGHT_DOCAGENT_DIR", raising=False)
    paths = AppPaths.from_env()
    assert paths.docagent_dir == tmp_path / "DocAgent"
    assert paths.srsagent_dir == tmp_path / "SRSAgent"
    assert paths.runs_dir == tmp_path / "d" / "runs"
    assert ".venv" in str(paths.docagent_python)
