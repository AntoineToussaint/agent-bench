from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from semble import SembleIndex


@dataclass
class SembleIdx:
    inner: SembleIndex


class SembleRetriever:
    """Adapter over semble's SembleIndex. Returns chunks, deduped to file paths."""

    name = "semble"

    def __init__(self, mode: str = "hybrid", over_fetch: int = 5) -> None:
        self.mode = mode
        self.over_fetch = over_fetch

    def index(self, repo_path: Path) -> SembleIdx:
        return SembleIdx(inner=SembleIndex.from_path(repo_path))

    def query(self, index: SembleIdx, query: str, k: int) -> list[str]:
        # Over-fetch chunks then dedupe to distinct file paths in rank order.
        results = index.inner.search(query, top_k=k * self.over_fetch, mode=self.mode)
        seen: list[str] = []
        for r in results:
            fp = r.chunk.file_path
            if fp not in seen:
                seen.append(fp)
            if len(seen) >= k:
                break
        return seen
