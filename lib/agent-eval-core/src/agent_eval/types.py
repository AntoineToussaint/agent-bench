"""Shared dataclasses + ABCs used across the library."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from agent_eval.context.types import ContextPolicy
    from agent_eval.protocols.types import ToolBackend


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
    # 0..N-1; non-zero only when running with Sweep(repetitions=N>1). Same
    # (task, model, condition) cell yields N records distinguished by this.
    replicate: int = 0
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
    def step(
        self,
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
    ) -> AssistantMessage:
        """Issue one model round-trip.

        Args:
            tools: provider-native tool schemas (Anthropic shape; clients
                convert as needed). Pass [] to disable tool_use.
            tool_choice: optional provider-specific constraint on which tool
                the model must call. None = "auto" (model decides). For
                Anthropic: `{"type": "any"}` forces a tool call;
                `{"type": "tool", "name": "X"}` forces a specific tool.
                Backends not supporting it can ignore.
        """
        ...


@dataclass
class ModelHandle:
    """A model paired with its tool-use backend.

    This is the unit trials accept. The handle hides whether the backend
    is provider-native tool_use, schema-enforced, or prompt-based JSON,
    and whether the context policy is keep-everything or pruning — those
    are configuration of the trial, not the trial's concern.

    Build with `agent_eval.models.make_model(name)` for the defaults, or
    `make_model(name, backend=..., context_policy=...)` to override.
    """

    client: ModelClient
    backend: "ToolBackend"
    context_policy: "ContextPolicy | None" = None

    @property
    def name(self) -> str:
        return self.client.name
