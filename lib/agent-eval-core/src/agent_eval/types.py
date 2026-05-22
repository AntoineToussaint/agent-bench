"""Shared dataclasses + ABCs used across the library."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


ToolCallStatus = Literal["ok", "error"]


@dataclass
class ToolCall:
    """A single tool invocation emitted by a model."""

    name: str
    arguments: dict[str, Any]
    call_id: str


@dataclass
class ToolResult:
    """Result of applying a single tool call."""

    call_id: str
    status: ToolCallStatus
    content: str
    diff: str | None = None


@dataclass
class TurnUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class AssistantMessage:
    """One model response — possibly text, possibly tool calls."""

    text: str
    tool_calls: list[ToolCall]
    usage: TurnUsage
    raw: Any = None


@dataclass
class Transcript:
    """Provider-agnostic message log for one trial."""

    system: str
    entries: list[dict[str, Any]] = field(default_factory=list)

    def add_user_text(self, text: str) -> None:
        self.entries.append({"role": "user", "content": text})

    def add_tool_results(self, results: list[ToolResult]) -> None:
        self.entries.append(
            {
                "role": "tool",
                "results": [
                    {"call_id": r.call_id, "status": r.status, "content": r.content}
                    for r in results
                ],
            }
        )

    def add_assistant(self, msg: AssistantMessage) -> None:
        self.entries.append(
            {
                "role": "assistant",
                "text": msg.text,
                "tool_calls": [
                    {"name": c.name, "arguments": c.arguments, "call_id": c.call_id}
                    for c in msg.tool_calls
                ],
                "usage": msg.usage.__dict__,
            }
        )


@dataclass
class RunRecord:
    """Outcome of one trial — (task, model, condition).

    `condition` is the experiment's free axis (a "format" for code edits,
    a "selection strategy" for tool routing, a "retriever" for localization,
    etc.). The library is condition-agnostic; downstream picks the semantics.
    """

    task_id: str
    model: str
    condition: str
    passed: bool
    turns: int
    tool_calls: int
    invalid_tool_calls: int
    usage: TurnUsage
    latency_seconds: float
    cost_usd: float = 0.0
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    transcript_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class ModelClient(ABC):
    """Provider-specific client. The runner only talks to this interface."""

    name: str  # short id used in run records

    @abstractmethod
    def reset(self, system: str) -> None: ...

    @abstractmethod
    def add_user_text(self, text: str) -> None: ...

    @abstractmethod
    def add_tool_results(self, results: list[ToolResult]) -> None: ...

    @abstractmethod
    def step(self, tools: list[dict[str, Any]]) -> AssistantMessage: ...
