"""OpenAI embeddings selector (text-embedding-3-{small,large}).

The candidate corpus is re-embedded per call. For the catalog sizes in this
study (≤ 40 tools), that's cheap and not worth caching across runs.
"""

from __future__ import annotations

import os
import time

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

from tool_selection.pricing import cost_for
from tool_selection.types import PipelineStep

from .base import Selectable, Selection, Selector, fold_text

load_dotenv()


class OpenAIEmbedSelector(Selector):
    def __init__(self, model: str):
        if model not in ("text-embedding-3-small", "text-embedding-3-large"):
            raise ValueError(f"unsupported embedding model: {model}")
        self.model = model
        self.id = f"embed-openai-{'small' if 'small' in model else 'large'}"
        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def select(self, query: str, candidates: list[Selectable], k: int) -> Selection:
        t0 = time.perf_counter()
        inputs = [query] + [fold_text(c) for c in candidates]
        resp = self._client.embeddings.create(model=self.model, input=inputs)
        vecs = np.array([d.embedding for d in resp.data], dtype=np.float32)
        q = vecs[0]
        cands = vecs[1:]
        q_norm = q / (np.linalg.norm(q) + 1e-12)
        c_norm = cands / (np.linalg.norm(cands, axis=1, keepdims=True) + 1e-12)
        sims = c_norm @ q_norm
        order = np.argsort(-sims)[:k].tolist()
        latency_ms = (time.perf_counter() - t0) * 1000

        input_tokens = resp.usage.total_tokens if resp.usage else 0
        return Selection(
            selected_ids=[candidates[i].name for i in order],
            scores=[float(sims[i]) for i in order],
            steps=[
                PipelineStep(
                    kind="embedding",
                    model=self.model,
                    input_tokens=input_tokens,
                    output_tokens=0,
                    cost_usd=cost_for(self.model, input_tokens, 0),
                    latency_ms=latency_ms,
                    note=f"selected {k}/{len(candidates)}",
                )
            ],
        )
