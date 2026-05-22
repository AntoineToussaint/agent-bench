"""Approach ABC + result type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from tool_selection.types import Catalog, PipelineStep, Task, Tool


@dataclass
class ApproachResult:
    surfaced_tools: list[Tool]
    pre_steps: list[PipelineStep]
    """Inner-pipeline telemetry (e.g. embedding lookup, router LLM call)."""


class Approach(ABC):
    id: str
    """Set on each subclass instance (or class). Approach IDs are stable
    strings like 'full', 'toolbox:bm25', 'hybrid:embed-openai-small+llm-haiku'."""

    @abstractmethod
    def surface(self, task: Task, catalog: Catalog) -> ApproachResult:
        """Return the tools surfaced to the final shot, plus any pre-step
        telemetry (embedding lookups, router calls, etc.)."""
