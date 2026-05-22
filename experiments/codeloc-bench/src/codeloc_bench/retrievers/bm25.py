from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")

# Heuristic include-list: keep the index small and focused on code/text.
# Cheaper than reading every binary, and avoids tokenizing minified JS bundles.
INCLUDE_EXT = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs",
    ".rb", ".php", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".kt",
    ".swift", ".scala", ".sh", ".bash", ".lua", ".ex", ".exs", ".hs",
    ".zig", ".md", ".rst", ".txt", ".yaml", ".yml", ".toml", ".cfg",
    ".ini", ".sql",
}

EXCLUDE_DIR = {
    ".git", "node_modules", "vendor", "dist", "build", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".idea",
    "target", "out",
}

MAX_BYTES = 512 * 1024  # cap per-file read to keep BM25 stats sane


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIR for part in path.parts):
            continue
        if path.suffix.lower() not in INCLUDE_EXT:
            continue
        yield path


@dataclass
class BM25Index:
    paths: list[str]
    bm25: BM25Okapi


class BM25Retriever:
    name = "bm25"

    def index(self, repo_path: Path) -> BM25Index:
        paths: list[str] = []
        docs: list[list[str]] = []
        for fp in _iter_files(repo_path):
            try:
                with fp.open("rb") as f:
                    raw = f.read(MAX_BYTES)
                text = raw.decode("utf-8", errors="ignore")
            except OSError:
                continue
            tokens = _tokenize(text)
            if not tokens:
                continue
            paths.append(str(fp.relative_to(repo_path)))
            docs.append(tokens)
        if not docs:
            docs = [[""]]
            paths = ["__empty__"]
        return BM25Index(paths=paths, bm25=BM25Okapi(docs))

    def query(self, index: BM25Index, query: str, k: int) -> list[str]:
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = index.bm25.get_scores(tokens)
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [index.paths[i] for i in order[:k] if scores[i] > 0]
