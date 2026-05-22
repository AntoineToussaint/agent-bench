from __future__ import annotations

import subprocess
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "codeloc-bench"
CLONES = CACHE_DIR / "clones"
WORKTREES = CACHE_DIR / "worktrees"


def _safe(repo: str) -> str:
    return repo.replace("/", "__")


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _clone(repo: str) -> Path:
    path = CLONES / _safe(repo)
    if (path / ".git").exists() or (path / "HEAD").exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "git", "clone", "--filter=blob:none", "--no-checkout",
        f"https://github.com/{repo}.git", str(path),
    ])
    return path


def _ensure_commit(clone: Path, commit: str) -> None:
    try:
        _run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=clone)
        return
    except subprocess.CalledProcessError:
        pass
    try:
        _run(["git", "fetch", "origin", commit], cwd=clone)
    except subprocess.CalledProcessError:
        _run(["git", "fetch", "--all", "--tags"], cwd=clone)


def prepare(repo: str, base_commit: str, repo_path: str = "") -> Path:
    """Return the path that the retriever should index for this task.

    If `repo_path` is set, it's used directly (no clone, no checkout — the
    caller is responsible for the working-tree state). Otherwise the repo is
    cloned and a detached worktree at `base_commit` is materialized in the
    cache.
    """
    if repo_path:
        path = Path(repo_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"repo_path does not exist: {path}")
        return path
    clone = _clone(repo)
    wt = WORKTREES / f"{_safe(repo)}__{base_commit[:12]}"
    if (wt / ".git").exists():
        return wt
    wt.parent.mkdir(parents=True, exist_ok=True)
    _ensure_commit(clone, base_commit)
    _run(["git", "worktree", "add", "--detach", str(wt), base_commit], cwd=clone)
    return wt
