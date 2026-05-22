"""Local sentence-transformers selector (MiniLM by default).

Free, ~10ms/query, CPU-only. The model is loaded lazily and cached on the
class so the same instance is reused across calls within a process.
"""

from __future__ import annotations

import time
from typing import ClassVar

import numpy as np

from tool_selection.types import PipelineStep

from .base import Selectable, Selection, Selector, fold_text


class LocalEmbedSelector(Selector):
    _model_cache: ClassVar[dict[str, object]] = {}

    def __init__(self, model: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model = model
        # Short id like "embed-local" or "embed-local-mpnet"
        if "MiniLM" in model:
            self.id = "embed-local"
        elif "mpnet" in model:
            self.id = "embed-local-mpnet"
        else:
            self.id = f"embed-local-{model.split('/')[-1]}"

    def _get_model(self):
        if self.model not in self._model_cache:
            from sentence_transformers import SentenceTransformer

            self._model_cache[self.model] = SentenceTransformer(self.model)
        return self._model_cache[self.model]

    def select(self, query: str, candidates: list[Selectable], k: int) -> Selection:
        model = self._get_model()
        t0 = time.perf_counter()
        texts = [query] + [fold_text(c) for c in candidates]
        vecs = np.asarray(model.encode(texts, normalize_embeddings=True))
        q = vecs[0]
        cands = vecs[1:]
        sims = cands @ q
        order = np.argsort(-sims)[:k].tolist()
        latency_ms = (time.perf_counter() - t0) * 1000
        return Selection(
            selected_ids=[candidates[i].name for i in order],
            scores=[float(sims[i]) for i in order],
            steps=[
                PipelineStep(
                    kind="embedding",
                    model=self.model,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    latency_ms=latency_ms,
                    note=f"selected {k}/{len(candidates)}",
                )
            ],
        )
