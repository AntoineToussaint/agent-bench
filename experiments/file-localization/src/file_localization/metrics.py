from __future__ import annotations

import math
from collections.abc import Iterable


def _norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


def _hit_vector(predicted: Iterable[str], gold: set[str]) -> list[int]:
    gold_n = {_norm(g) for g in gold}
    return [1 if _norm(p) in gold_n else 0 for p in predicted]


def recall_at_k(predicted: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 0.0
    return sum(_hit_vector(predicted[:k], gold)) / len(gold)


def ndcg_at_k(predicted: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 0.0
    hits = _hit_vector(predicted[:k], gold)
    dcg = sum(h / math.log2(i + 2) for i, h in enumerate(hits))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
    return dcg / ideal if ideal else 0.0
