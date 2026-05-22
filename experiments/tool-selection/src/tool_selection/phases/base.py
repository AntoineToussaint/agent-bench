"""Phase ABC + result type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from tool_selection.types import PipelineStep, Task, Tool


@dataclass
class PhaseResult:
    final_calls: list[dict[str, Any]]
    final_text: str
    steps: list[PipelineStep]
    error: str | None = None


class Phase(ABC):
    id: str

    @abstractmethod
    def execute(self, task: Task, surfaced_tools: list[Tool], model: str) -> PhaseResult: ...
