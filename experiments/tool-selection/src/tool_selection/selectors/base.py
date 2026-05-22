"""Selector ABC, Selectable protocol, Selection result."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol

from tool_selection.types import PipelineStep


class Selectable(Protocol):
    """Anything a Selector can rank — must expose a name and a description."""

    name: str
    description: str


@dataclass
class Selection:
    selected_ids: list[str]
    """Top-k item names, in rank order (best first)."""

    scores: list[float] = field(default_factory=list)
    """Optional per-item scores aligned with selected_ids (higher = better).
    Empty for selectors that don't expose scores (e.g. some LLM rankers)."""

    steps: list[PipelineStep] = field(default_factory=list)
    """One or more PipelineStep entries covering the cost/latency of this
    selection. An approach concatenates these into its pre_steps."""


class Selector(ABC):
    id: str
    """Set on each subclass instance (or class) — used in approach IDs and
    pipeline-step telemetry. Parametric selectors (LLM, OpenAI embed) set this
    in __init__ from the underlying model name."""

    @abstractmethod
    def select(self, query: str, candidates: list[Selectable], k: int) -> Selection:
        """Return top-k candidate names by relevance to the query."""


def fold_text(item: Selectable) -> str:
    """Default text representation used for ranking: 'name — description'."""
    return f"{item.name}\n{item.description}"
