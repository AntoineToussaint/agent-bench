"""BM25 lexical selector — zero cost, sub-millisecond latency baseline."""

from __future__ import annotations

import re
import time

from rank_bm25 import BM25Okapi

from tool_selection.types import PipelineStep

from .base import Selectable, Selection, Selector, fold_text

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class BM25Selector(Selector):
    id = "bm25"

    def select(self, query: str, candidates: list[Selectable], k: int) -> Selection:
        t0 = time.perf_counter()
        docs = [_tokenize(fold_text(c)) for c in candidates]
        bm25 = BM25Okapi(docs)
        scores = bm25.get_scores(_tokenize(query))
        order = sorted(range(len(candidates)), key=lambda i: -scores[i])[:k]
        latency_ms = (time.perf_counter() - t0) * 1000
        return Selection(
            selected_ids=[candidates[i].name for i in order],
            scores=[float(scores[i]) for i in order],
            steps=[
                PipelineStep(
                    kind="embedding",
                    model="bm25",
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    latency_ms=latency_ms,
                    note=f"selected {len(order)}/{len(candidates)}",
                )
            ],
        )
