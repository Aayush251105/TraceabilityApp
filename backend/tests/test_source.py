import os
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

from tracelight.orchestrator.source import (SourceError, clone_git, copy_folder, extract_zip,
                                            fetch_source, inspect_tree, make_working_copy,
                                            repo_name_from_url, size_warnings, validate_git_url,
                                            validate_srs_file)
from tracelight.settings import DEFAULTS, AppPaths

EXCLUDE = DEFAULTS["source"]["exclude_dirs"]
LIBRARY = AppPaths.from_env().workspace / "library_traceability_dataset"

APP_PY = '''
class Shop:
    def buy(self):
        pass

    async def refund(self):
        pass

    class Inner:
        def x(self):
            pass

def helper():
    def nested():
        pass
'''


def _zip(path: Path, entries: dict, symlink: str = None) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return path


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def test_inspect_counts_components_like_docagent(tmp_path):
    (tmp_path / "app.py").write_text(APP_PY, encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def (:\n", encoding="utf-8")
    venv = tmp_path / "venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "dep.py").write_text("def a(): pass\n", encoding="utf-8")
    s = inspect_tree(tmp_path, EXCLUDE)
    assert (s.files, s.python_files) == (3, 2)
    assert (s.classes, s.methods, s.functions) == (2, 3, 1)      # nested functions are not components
    assert s.unparsable == ["broken.py"]


@pytest.mark.skipif(not LIBRARY.exists(), reason="library dataset not available")
def test_inspect_library_matches_docagent_parse():
    s = inspect_tree(LIBRARY / "codebase", EXCLUDE)
    assert (s.classes, s.methods, s.functions) == (5, 27, 9)     # DocAgent: 41 components
    assert s.components == 41


def test_size_warnings():
    from tracelight.orchestrator.source import SourceStats
    limits = {"large_repo_files": 10, "large_repo_components": 100}
    assert [w["code"] for w in size_warnings(SourceStats(), limits)] == ["no_python"]
    big = SourceStats(python_files=11, classes=60, methods=50, unparsable=["a.py"])
    assert [w["code"] for w in size_warnings(big, limits)] == ["large_repo", "many_components", "syntax_errors"]
    assert size_warnings(SourceStats(python_files=3, functions=4), limits) == []


# ---------------------------------------------------------------------------
# ZIP
# ---------------------------------------------------------------------------


def test_zip_unwraps_single_top_folder_and_skips_excluded(tmp_path):
    z = _zip(tmp_path / "repo-main.zip", {
        "repo-main/pkg/app.py": APP_PY,
        "repo-main/venv/lib/x.py": "x = 1",
        "repo-main/pkg/__pycache__/app.cpython-312.pyc": "bin",
        "repo-main/node_modules/a/index.js": "",
    })
    root = extract_zip(z, tmp_path / "out", EXCLUDE)
    assert root == tmp_path / "out" / "repo-main"
    assert (root / "pkg" / "app.py").exists()
    assert not (root / "venv").exists() and not (root / "node_modules").exists()
    assert not (root / "pkg" / "__pycache__").exists()


def test_zip_without_top_folder(tmp_path):
    z = _zip(tmp_path / "flat.zip", {"a.py": "x=1", "b/c.py": "y=2"})
    assert extract_zip(z, tmp_path / "out") == tmp_path / "out"


@pytest.mark.parametrize("bad", ["../evil.py", "a/../../evil.py", "/abs/evil.py", "C:/evil.py", "..\\evil.py"])
def test_zip_rejects_escaping_paths(tmp_path, bad):
    z = _zip(tmp_path / "bad.zip", {"ok.py": "", bad: "boom"})
    with pytest.raises(SourceError, match="Unsafe path"):
        extract_zip(z, tmp_path / "out")
    assert not (tmp_path / "evil.py").exists()


def test_zip_rejects_symlinks(tmp_path):
    z = _zip(tmp_path / "link.zip", {"a.py": ""}, symlink="link")
    with pytest.raises(SourceError, match="Symbolic links"):
        extract_zip(z, tmp_path / "out")


def test_zip_limits(tmp_path):
    z = _zip(tmp_path / "many.zip", {f"f{i}.py": "x" * 100 for i in range(5)})
    with pytest.raises(SourceError, match="entries"):
        extract_zip(z, tmp_path / "o1", max_files=3)
    with pytest.raises(SourceError, match="expands to"):
        extract_zip(z, tmp_path / "o2", max_bytes=200)


def test_not_a_zip(tmp_path):
    p = tmp_path / "fake.zip"
    p.write_text("not a zip", encoding="utf-8")
    with pytest.raises(SourceError, match="Not a valid ZIP"):
        extract_zip(p, tmp_path / "out")


# ---------------------------------------------------------------------------
# Folder
# ---------------------------------------------------------------------------


def test_copy_folder_excludes(tmp_path):
    src = tmp_path / "proj"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "a.py").write_text("x=1", encoding="utf-8")
    (src / ".venv" / "Lib").mkdir(parents=True)
    (src / "pkg.egg-info").mkdir()
    out = copy_folder(src, tmp_path / "copy", EXCLUDE)
    assert (out / "pkg" / "a.py").exists()
    assert not (out / ".venv").exists() and not (out / "pkg.egg-info").exists()


def test_copy_folder_refuses_dest_inside_source(tmp_path):
    (tmp_path / "a.py").write_text("x=1", encoding="utf-8")
    with pytest.raises(SourceError, match="inside the source"):
        copy_folder(tmp_path, tmp_path / "runs" / "1" / "source")


def test_copy_missing_folder(tmp_path):
    with pytest.raises(SourceError, match="not found"):
        copy_folder(tmp_path / "nope", tmp_path / "out")


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["https://github.com/owner/repo", "https://github.com/owner/repo.git",
                                 "https://gitlab.example.org:8443/group/sub/repo/"])
def test_valid_git_urls(url):
    assert validate_git_url(url) == url.rstrip("/")


@pytest.mark.parametrize("url", ["git@github.com:owner/repo.git", "file:///etc", "http://github.com/a/b",
                                 "--upload-pack=evil", "https://github.com/a/b;rm -rf", "C:\\repo",
                                 "https://user:pw@github.com/a/b"])
def test_invalid_git_urls(url):
    with pytest.raises(SourceError):
        validate_git_url(url)


def test_repo_name_from_url():
    assert repo_name_from_url("https://github.com/owner/repo.git") == "repo"
    assert repo_name_from_url("https://github.com/owner/repo/") == "repo"


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                   check=True, capture_output=True)


@pytest.fixture()
def local_repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    repo = tmp_path / "origin"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "app.py").write_text(APP_PY, encoding="utf-8")
    (repo / "venv").mkdir()
    (repo / "venv" / "junk.py").write_text("x=1", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "first")
    _git(repo, "tag", "v1")
    (repo / "pkg" / "new.py").write_text("def f(): pass\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "second")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    return repo, head


def test_clone_records_sha_and_drops_git_and_excluded(local_repo, tmp_path):
    repo, head = local_repo
    dest = tmp_path / "clone"
    sha = clone_git(str(repo), dest, EXCLUDE, allow_local=True)
    assert sha == head
    assert (dest / "pkg" / "new.py").exists()
    assert not (dest / ".git").exists() and not (dest / "venv").exists()


def test_clone_tag(local_repo, tmp_path):
    repo, head = local_repo
    sha = clone_git(str(repo), tmp_path / "clone", EXCLUDE, ref="v1", allow_local=True)
    assert sha != head and not (tmp_path / "clone" / "pkg" / "new.py").exists()


def test_clone_rejects_bad_ref_and_reports_failure(local_repo, tmp_path):
    repo, _ = local_repo
    with pytest.raises(SourceError, match="Invalid branch"):
        clone_git(str(repo), tmp_path / "c1", ref="--upload-pack=x", allow_local=True)
    with pytest.raises(SourceError, match="git clone failed"):
        clone_git(str(repo), tmp_path / "c2", ref="no-such-branch", allow_local=True)


def test_clone_local_path_refused_by_default(local_repo, tmp_path):
    repo, _ = local_repo
    with pytest.raises(SourceError, match="https://"):
        clone_git(str(repo), tmp_path / "c")


@pytest.mark.skipif(os.environ.get("TRACELIGHT_NETWORK_TESTS") != "1",
                    reason="set TRACELIGHT_NETWORK_TESTS=1 to clone from GitHub")
def test_clone_from_github(tmp_path):
    info = fetch_source("git", "https://github.com/pallets/itsdangerous", tmp_path, DEFAULTS)
    assert len(info.commit_sha) == 40 and info.stats.python_files > 0 and info.name == "itsdangerous"


# ---------------------------------------------------------------------------
# fetch_source / working copy / SRS validation
# ---------------------------------------------------------------------------


def test_fetch_source_zip(tmp_path):
    z = _zip(tmp_path / "shop.zip", {"shop-main/shop/app.py": APP_PY})
    info = fetch_source("zip", str(z), tmp_path / "run", DEFAULTS)
    assert info.name == "shop-main" and info.commit_sha is None
    assert info.stats.components == 6 and info.warnings == []
    assert info.to_dict()["stats"]["components"] == 6
    # fetching again replaces the previous copy
    info2 = fetch_source("zip", str(z), tmp_path / "run", DEFAULTS)
    assert info2.root == info.root


def test_fetch_source_folder_git_checkout(local_repo, tmp_path):
    repo, head = local_repo
    info = fetch_source("folder", str(repo), tmp_path / "run", DEFAULTS)
    assert info.commit_sha == head and info.name == "origin"
    assert not (info.root / ".git").exists()


def test_fetch_source_git(local_repo, tmp_path):
    repo, head = local_repo
    info = fetch_source("git", str(repo), tmp_path / "run", DEFAULTS, allow_local_git=True)
    assert info.commit_sha == head and info.root == tmp_path / "run" / "source"


def test_fetch_source_no_python_warns(tmp_path):
    z = _zip(tmp_path / "docs.zip", {"README.md": "hi"})
    info = fetch_source("zip", str(z), tmp_path / "run", DEFAULTS)
    assert info.warnings[0]["code"] == "no_python"


def test_unknown_kind(tmp_path):
    with pytest.raises(SourceError, match="Unknown source kind"):
        fetch_source("svn", "x", tmp_path, DEFAULTS)


def test_working_copy_is_independent(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "a.py").write_text("x=1", encoding="utf-8")
    work = make_working_copy(src, tmp_path / "work")
    (work / "a.py").write_text("x=2", encoding="utf-8")
    assert (src / "a.py").read_text(encoding="utf-8") == "x=1"
    make_working_copy(src, work)                        # replaced on retry
    assert (work / "a.py").read_text(encoding="utf-8") == "x=1"


def test_validate_srs_file(tmp_path):
    good = tmp_path / "srs.docx"
    good.write_bytes(b"PK..")
    validate_srs_file(good, max_mb=1)
    with pytest.raises(SourceError, match="Unsupported"):
        validate_srs_file(tmp_path / "srs.exe", 1)
    empty = tmp_path / "e.pdf"
    empty.write_bytes(b"")
    with pytest.raises(SourceError, match="empty"):
        validate_srs_file(empty, 1)
    with pytest.raises(SourceError, match="not found"):
        validate_srs_file(tmp_path / "missing.md", 1)
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(SourceError, match="larger than"):
        validate_srs_file(big, 1)
