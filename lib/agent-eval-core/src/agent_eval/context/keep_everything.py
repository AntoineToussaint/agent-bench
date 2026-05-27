"""Baseline policy: keep every message verbatim.

This is what the trial loop did before `ContextPolicy` existed. It
maximizes prompt-cache hits (the prefix never changes between turns)
at the cost of unbounded context growth.

Use as the control arm of any context-policy ablation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import Provider


@dataclass
class KeepEverything:
    name: str = "keep_everything"

    def prepare(
        self,
        messages: list[dict[str, Any]],
        *,
        provider: Provider,
        turn_idx: int,
    ) -> list[dict[str, Any]]:
        return list(messages)
