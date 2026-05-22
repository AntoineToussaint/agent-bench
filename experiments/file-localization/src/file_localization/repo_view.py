"""RepoView protocol + local-directory implementation.

A `RepoView` is a read-only window onto a repo at some commit/state. It's
deliberately small: list_files / grep / view_file. Anything that needs to
inspect a repo (the turn-loop trial, the structured trial, future agents)
takes a `RepoView` rather than a concrete `Path` so we can later plug in
e.g. a remote view, an indexed view, a worktree-cached view, etc.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class RepoView(Protocol):
    """Read-only view of a repo at a specific commit/state."""

    def list_files(self, subpath: str = "") -> list[str]: ...
    def grep(
        self, pattern: str, glob: str = "", limit: int = 50
    ) -> list[tuple[str, int, str]]: ...
    def view_file(
        self, path: str, line_range: tuple[int, int] | None = None
    ) -> str: ...


@dataclass
class LocalRepoView:
    """A RepoView backed by a local directory.

    Excludes typical noise dirs (.git, __pycache__, node_modules, .venv) from
    listings + grep. Read-only — no methods that mutate disk.
    """

    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()

    def _safe(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError(f"path escapes repo: {rel}")
        return p

    def list_files(self, subpath: str = "") -> list[str]:
        base = self._safe(subpath) if subpath else self.root
        if not base.exists() or not base.is_dir():
            return []
        out: list[str] = []
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            parts = p.relative_to(self.root).parts
            if any(
                seg in {".git", "__pycache__", "node_modules", ".venv"} for seg in parts
            ):
                continue
            out.append(str(p.relative_to(self.root)))
        return sorted(out)

    def grep(
        self, pattern: str, glob: str = "", limit: int = 50
    ) -> list[tuple[str, int, str]]:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"bad regex {pattern!r}: {e}") from e
        hits: list[tuple[str, int, str]] = []
        for rel in self.list_files():
            if glob and not fnmatch.fnmatch(rel, glob):
                continue
            try:
                text = (self.root / rel).read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if rx.search(line):
                    snippet = line[:200].rstrip()
                    hits.append((rel, i, snippet))
                    if len(hits) >= limit:
                        return hits
        return hits

    def view_file(
        self, path: str, line_range: tuple[int, int] | None = None
    ) -> str:
        p = self._safe(path)
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        if line_range is None:
            return text
        lines = text.splitlines()
        start, end = line_range
        return "\n".join(lines[max(0, start - 1) : min(len(lines), end)])
