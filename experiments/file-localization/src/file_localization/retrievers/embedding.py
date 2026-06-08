"""`embedding` retriever — pure code-RAG: embed each source file, embed the
issue, rank files by cosine similarity.

This is the cheap, self-contained "vector index" arm for the localization
bake-off (agentic-search vs RAG). It embeds the SOURCE FILES directly (no
LLM-generated wiki, unlike repowise), so it isolates the "do dense embeddings
of code beat keyword search (bm25/ripgrep) at finding the file to edit?"
question the no-indexing debate turns on.

Uses OpenAI embeddings (text-embedding-3-small: $0.02/Mtok ≈ a couple cents per
repo). Needs OPENAI_API_KEY. File contents are truncated to the model's window;
for localization the head of a file (imports, defs, docstrings) carries most of
the signal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from file_localization.retrievers.bm25 import MAX_BYTES, _iter_files

_MODEL = "text-embedding-3-small"
_MAX_TOKENS = 8000           # model hard cap is 8192; truncate by real tokens
_MAX_CHARS = 8000            # fallback when tiktoken is unavailable (chars >= tokens, so safe)
_BATCH = 32                  # keep per-request total tokens under the ~300k budget


def _truncate(text: str) -> str:
    """Truncate to <= _MAX_TOKENS for the embedding model. Uses tiktoken when
    available (keeps far more content); else a char cap that can't exceed the
    token limit (token count <= char count)."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        toks = enc.encode(text)
        if len(toks) <= _MAX_TOKENS:
            return text
        return enc.decode(toks[:_MAX_TOKENS])
    except Exception:  # noqa: BLE001 — tiktoken missing or any encode hiccup
        return text[:_MAX_CHARS]


@dataclass
class EmbeddingIndex:
    paths: list[str]
    vectors: list[list[float]]  # unit-normalized


def _client():
    from openai import OpenAI  # local import so the dep is optional

    return OpenAI()


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _embed_batch(client, texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=_MODEL, input=texts)
    return [_normalize(d.embedding) for d in resp.data]


class EmbeddingRetriever:
    name = "embedding"

    def __init__(self, model: str = _MODEL) -> None:
        self.model = model

    def index(self, repo_path: Path) -> EmbeddingIndex:
        paths: list[str] = []
        texts: list[str] = []
        for fp in _iter_files(repo_path):
            try:
                raw = fp.open("rb").read(MAX_BYTES)
            except OSError:
                continue
            text = raw.decode("utf-8", errors="ignore").strip()
            if not text:
                continue
            rel = str(fp.relative_to(repo_path))
            # Prefix the path so the filename's tokens contribute to the vector.
            texts.append(_truncate(f"{rel}\n\n{text}"))
            paths.append(rel)
        if not paths:
            return EmbeddingIndex(paths=["__empty__"], vectors=[[0.0]])
        client = _client()
        vectors: list[list[float]] = []
        for i in range(0, len(texts), _BATCH):
            vectors.extend(_embed_batch(client, texts[i : i + _BATCH]))
        return EmbeddingIndex(paths=paths, vectors=vectors)

    def query(self, index: EmbeddingIndex, query: str, k: int) -> list[str]:
        if index.paths == ["__empty__"]:
            return []
        qv = _embed_batch(_client(), [_truncate(query)])[0]
        # cosine = dot product (both unit-normalized)
        scored = [
            (sum(a * b for a, b in zip(qv, vec)), path)
            for path, vec in zip(index.paths, index.vectors)
        ]
        scored.sort(reverse=True)
        return [path for _, path in scored[:k]]
