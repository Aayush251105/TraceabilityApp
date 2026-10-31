"""
Fetch the code for a run: a ZIP upload, a local folder, or a Git URL.

The result is a pristine copy in <run>/source.  DocAgent later works on a
separate copy (<run>/work), because it writes docstrings into the files; the
pristine copy is what the code view shows, since its line numbers match the
parsed components.

Safety
------
- Nothing from the repository is executed: no install, no build, no hooks
  (git clone runs without repository hooks, submodules, LFS smudge or the
  file:// protocol; prompts for credentials are disabled).
- ZIP extraction refuses absolute paths, '..' segments, drive letters and
  symlinks, and caps the uncompressed size and file count (zip bombs).
- Only https:// Git URLs are accepted (no ssh, file:// or option-like values).
- Virtual environments, build output, VCS and cache folders are skipped.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence

SRS_EXTENSIONS = (".docx", ".pdf", ".md", ".txt")
MAX_ZIP_FILES = 20000
MAX_ZIP_BYTES = 1024 * 1024 * 1024          # 1 GiB uncompressed
GIT_TIMEOUT_SECONDS = 600


class SourceError(ValueError):
    """The source could not be fetched or is not acceptable (shown to the user)."""


@dataclass
class SourceStats:
    files: int = 0
    python_files: int = 0
    python_lines: int = 0
    bytes: int = 0
    classes: int = 0
    functions: int = 0
    methods: int = 0
    unparsable: List[str] = field(default_factory=list)   # .py files with syntax errors
    skipped_dirs: List[str] = field(default_factory=list)

    @property
    def components(self) -> int:
        return self.classes + self.functions + self.methods


@dataclass
class SourceInfo:
    kind: str                      # zip | folder | git
    ref: str                       # file name, folder path or URL
    root: Path                     # pristine copy
    name: str                      # repository name (for display and repo_id)
    commit_sha: Optional[str]
    git_ref: Optional[str]
    stats: SourceStats
    warnings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["root"] = str(self.root)
        out["stats"]["components"] = self.stats.components
        return out


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def _excluded(name: str, exclude: Sequence[str]) -> bool:
    return name in exclude or name.endswith(".egg-info")


def iter_files(root: Path, exclude: Sequence[str]) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _excluded(d, exclude))
        for name in sorted(filenames):
            yield Path(dirpath) / name


def inspect_tree(root: Path, exclude: Sequence[str] = ()) -> SourceStats:
    """Count files and Python components (parsed with ast, never imported)."""
    stats = SourceStats()
    for path in iter_files(root, exclude):
        stats.files += 1
        try:
            stats.bytes += path.stat().st_size
        except OSError:
            continue
        if path.suffix != ".py":
            continue
        stats.python_files += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
        except (SyntaxError, ValueError, OSError):
            stats.unparsable.append(path.relative_to(root).as_posix())
            continue
        stats.python_lines += text.count("\n") + 1
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                stats.classes += 1
                stats.methods += sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in node.body)
        stats.functions += sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in tree.body)
    return stats


def size_warnings(stats: SourceStats, limits: Dict[str, Any]) -> List[Dict[str, Any]]:
    warnings = []
    if stats.python_files == 0:
        warnings.append({"code": "no_python", "level": "error",
                         "message": "No Python files found. DocAgent and the mapping support Python only."})
    if stats.python_files > limits.get("large_repo_files", 400):
        warnings.append({"code": "large_repo", "level": "warn",
                         "message": f"{stats.python_files} Python files. Docstring generation runs one "
                                    f"LLM pass per component and may take hours."})
    if stats.components > limits.get("large_repo_components", 1500):
        warnings.append({"code": "many_components", "level": "warn",
                         "message": f"{stats.components} components to document."})
    if stats.unparsable:
        warnings.append({"code": "syntax_errors", "level": "warn",
                         "message": f"{len(stats.unparsable)} Python file(s) do not parse and will be skipped.",
                         "files": stats.unparsable[:20]})
    return warnings


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


def _safe_member(name: str) -> Optional[PurePosixPath]:
    """The archive member as a relative path, or None if it would escape the target."""
    name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    path = PurePosixPath(name)
    if any(part == ".." for part in path.parts):
        return None
    return path


def _single_top_dir(root: Path) -> Path:
    """GitHub 'Download ZIP' archives wrap everything in one folder; use it as the root."""
    entries = [p for p in root.iterdir() if p.name not in ("__MACOSX",)]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return root


def extract_zip(zip_path: Path, dest: Path, exclude: Sequence[str] = (), *,
                max_files: int = MAX_ZIP_FILES, max_bytes: int = MAX_ZIP_BYTES) -> Path:
    """Safely extract a ZIP into dest; returns the repository root inside it."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise SourceError(f"Not a valid ZIP archive: {exc}") from exc
    dest.mkdir(parents=True, exist_ok=True)
    with archive:
        members = archive.infolist()
        if len(members) > max_files:
            raise SourceError(f"The archive has {len(members)} entries (limit {max_files}).")
        total = sum(m.file_size for m in members)
        if total > max_bytes:
            raise SourceError(f"The archive expands to {total // (1024 * 1024)} MB "
                              f"(limit {max_bytes // (1024 * 1024)} MB).")
        for member in members:
            rel = _safe_member(member.filename)
            if rel is None:
                raise SourceError(f"Unsafe path in archive: {member.filename!r}")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise SourceError(f"Symbolic links are not allowed in the archive: {member.filename!r}")
            if any(_excluded(part, exclude) for part in rel.parts[:-1 if not member.is_dir() else None]):
                continue
            target = dest.joinpath(*rel.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return _single_top_dir(dest)


def copy_folder(src: Path, dest: Path, exclude: Sequence[str] = ()) -> Path:
    src = src.resolve()
    if not src.is_dir():
        raise SourceError(f"Folder not found: {src}")
    dest_resolved = dest.resolve()
    if dest_resolved == src or src in dest_resolved.parents:
        raise SourceError("The run folder cannot be inside the source folder.")
    shutil.copytree(src, dest, ignore=lambda d, names: [n for n in names if _excluded(n, exclude)],
                    symlinks=False, ignore_dangling_symlinks=True)
    return dest


_GIT_URL = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d+)?/[A-Za-z0-9._~/-]+?(?:\.git)?/?$")
_GIT_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


def validate_git_url(url: str) -> str:
    url = url.strip()
    if not _GIT_URL.match(url):
        raise SourceError("Enter an https:// Git URL, e.g. https://github.com/owner/repo")
    return url.rstrip("/")


def repo_name_from_url(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def _git_env() -> Dict[str, str]:
    env = dict(os.environ)
    env.update(GIT_TERMINAL_PROMPT="0", GIT_LFS_SKIP_SMUDGE="1", GCM_INTERACTIVE="never",
               GIT_ASKPASS="echo", SSH_ASKPASS="echo")
    return env


def _git(args: List[str], cwd: Optional[Path] = None, timeout: int = GIT_TIMEOUT_SECONDS) -> str:
    i = 0
    while i < len(args) and args[i] == "-c":       # skip "-c key=value" options
        i += 2
    command = args[i] if i < len(args) else "git"
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, env=_git_env(),
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as exc:
        raise SourceError("git is not installed or not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise SourceError(f"git {command} timed out after {timeout} s.") from exc
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip().splitlines()
        raise SourceError(f"git {command} failed: {msg[-1] if msg else 'unknown error'}")
    return proc.stdout.strip()


def _remove_tree(path: Path) -> None:
    def retry_writable(func, p, _exc):   # git objects are read-only on Windows
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry_writable)
    else:
        shutil.rmtree(path, onerror=retry_writable)


def clone_git(url: str, dest: Path, exclude: Sequence[str] = (), *, ref: Optional[str] = None,
              allow_local: bool = False) -> str:
    """Shallow-clone url (optionally a branch/tag) into dest; returns the commit SHA."""
    if not allow_local:
        url = validate_git_url(url)
    if ref is not None and (not _GIT_REF.match(ref) or ref.startswith("-")):
        raise SourceError(f"Invalid branch or tag name: {ref!r}")
    args = ["-c", "protocol.file.allow=" + ("always" if allow_local else "never"),
            "-c", "core.hooksPath=" + os.devnull, "-c", "core.symlinks=false",
            "clone", "--depth", "1", "--single-branch", "--no-recurse-submodules", "--quiet"]
    if ref:
        args += ["--branch", ref]
    args += ["--", url, str(dest)]
    _git(args)
    sha = _git(["rev-parse", "HEAD"], cwd=dest)
    _remove_tree(dest / ".git")
    for path in list(dest.rglob("*")):
        if path.is_dir() and _excluded(path.name, exclude) and path.exists():
            _remove_tree(path)
    return sha


def local_commit_sha(folder: Path) -> Optional[str]:
    """The HEAD commit of a local folder that is a Git checkout (None otherwise)."""
    if not (folder / ".git").exists():
        return None
    try:
        return _git(["rev-parse", "HEAD"], cwd=folder, timeout=30)
    except SourceError:
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def fetch_source(kind: str, ref: str, run_dir: Path, settings: Dict[str, Any], *,
                 git_ref: Optional[str] = None, allow_local_git: bool = False) -> SourceInfo:
    """
    Put the code into <run_dir>/source and describe it.

    kind: 'zip' (ref = path of the uploaded archive), 'folder' (ref = local
    path) or 'git' (ref = https URL, git_ref = optional branch/tag).
    """
    exclude = settings["source"]["exclude_dirs"]
    dest = run_dir / "source"
    if dest.exists():
        _remove_tree(dest)
    sha: Optional[str] = None
    if kind == "zip":
        root = extract_zip(Path(ref), dest, exclude)
        name = root.name if root != dest else Path(ref).stem
    elif kind == "folder":
        root = copy_folder(Path(ref), dest, exclude)
        name = Path(ref).resolve().name
        sha = local_commit_sha(Path(ref))
    elif kind == "git":
        sha = clone_git(ref, dest, exclude, ref=git_ref, allow_local=allow_local_git)
        root = dest
        name = repo_name_from_url(ref)
    else:
        raise SourceError(f"Unknown source kind: {kind!r}")
    stats = inspect_tree(root, exclude)
    return SourceInfo(kind=kind, ref=ref, root=root, name=name, commit_sha=sha, git_ref=git_ref,
                      stats=stats, warnings=size_warnings(stats, settings["limits"]))


def make_working_copy(source_root: Path, work_dir: Path) -> Path:
    """The copy DocAgent edits (replaced if it exists)."""
    if work_dir.exists():
        _remove_tree(work_dir)
    shutil.copytree(source_root, work_dir)
    return work_dir


def validate_srs_file(path: Path, max_mb: int) -> None:
    if path.suffix.lower() not in SRS_EXTENSIONS:
        raise SourceError(f"Unsupported SRS format {path.suffix!r}; use {', '.join(SRS_EXTENSIONS)}.")
    if not path.is_file():
        raise SourceError(f"SRS file not found: {path.name}")
    size = path.stat().st_size
    if size == 0:
        raise SourceError("The SRS file is empty.")
    if size > max_mb * 1024 * 1024:
        raise SourceError(f"The SRS file is larger than {max_mb} MB.")
