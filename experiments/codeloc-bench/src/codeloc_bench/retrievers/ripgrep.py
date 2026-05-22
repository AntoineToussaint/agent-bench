from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "for", "to", "of",
    "in", "on", "at", "by", "with", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "should", "could", "may", "might", "must", "can", "this", "that", "these",
    "those", "you", "he", "she", "it", "we", "they", "what", "which", "who",
    "when", "where", "why", "how", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "no", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "also", "into", "out", "up", "down", "over",
    "under", "again", "further", "there", "here", "about", "between", "through",
}


@dataclass
class RipgrepIndex:
    repo_path: Path


class RipgrepRetriever:
    name = "ripgrep"

    def index(self, repo_path: Path) -> RipgrepIndex:
        return RipgrepIndex(repo_path=repo_path)

    @staticmethod
    def _keywords(query: str, cap: int = 20) -> list[str]:
        seen: list[str] = []
        for tok in WORD_RE.findall(query):
            if tok.lower() in STOPWORDS or len(tok) < 3:
                continue
            if tok not in seen:
                seen.append(tok)
            if len(seen) >= cap:
                break
        return seen

    def query(self, index: RipgrepIndex, query: str, k: int) -> list[str]:
        keywords = self._keywords(query)
        if not keywords:
            return []
        per_file: Counter[str] = Counter()
        for kw in keywords:
            try:
                out = subprocess.run(
                    ["rg", "-l", "--fixed-strings", "--ignore-case", "--no-messages", kw, "."],
                    cwd=index.repo_path, capture_output=True, text=True, timeout=30,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
            for line in out.stdout.splitlines():
                path = line.lstrip("./").strip()
                if path:
                    per_file[path] += 1
        return [p for p, _ in per_file.most_common(k)]
