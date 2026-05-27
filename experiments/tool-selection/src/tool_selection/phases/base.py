"""Phase ABC + result type.

`execute` accepts an optional `ModelHandle` so the trial can drive the
final shot through a chosen `ToolBackend` (native tool_use, schema-
enforced, prompt-JSON). When `handle is None`, phases fall back to
`agent_eval.make_client(model)` with the default backend, preserving
the original behavior.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agent_eval.types import ModelHandle

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
    def execute(
        self,
        task: Task,
        surfaced_tools: list[Tool],
        model: str,
        handle: ModelHandle | None = None,
    ) -> PhaseResult: ...
