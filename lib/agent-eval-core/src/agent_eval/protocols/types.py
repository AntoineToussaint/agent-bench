"""Backend-agnostic contract for "ask the model for structured actions".

A `ToolBackend` is one *mechanism* for getting structured actions out of an
LLM. The experiment trial doesn't care which mechanism is in use — it
declares a tool surface (`list[ToolSpec]`), calls `backend.request(client,
tools)`, and receives a parsed `ActionResponse`.

Three concrete backends live next to this file:

  - native.py        — tool_use API, tool_choice="auto" (model can also
                       emit narration; what `turn_loop_trial.py` did).

  - schema.py        — tool_use API, tool_choice={"type":"any"} (model
                       MUST call a tool; can't emit free-form text or
                       tool-format mimicry).

  - prompt_json.py   — text-only fenced JSON + mimicry detection; tools
                       are described in the system prompt addendum.

This abstraction exists because we kept finding that the *choice of
mechanism* drives outcomes more than the choice of model or prompt.
Putting it behind a swappable interface lets the sweep treat backend as
just another axis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_eval.types import ModelClient, ToolCall, ToolResult, TurnUsage


@dataclass(frozen=True)
class ToolSpec:
    """One tool the model can choose to call.

    Shape is JSON-Schema-style and intentionally matches Anthropic's
    `tool_use` input shape 1:1 — that's the most common provider format
    and OpenAI/Gemini conversions are mechanical.
    """

    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema

    def as_anthropic_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class ActionResponse:
    """One turn's worth of structured actions extracted from the model.

    Fields:
        actions:           parsed, validated ToolCalls (the actual work)
        raw_text:          model narration outside the structured part
        invalid_attempts:  parse errors, mimicry tags, malformed actions
        usage:             provider-reported token counts
        backend_name:      "native" | "schema_enforced" | "prompt_json"
        error:             non-None on hard failure (model emitted nothing
                           we could turn into actions or narration)
    """

    actions: list[ToolCall]
    raw_text: str
    invalid_attempts: int
    usage: TurnUsage
    backend_name: str
    error: str | None = None
    # Optional structured hints the trial can render back into the next
    # user message (e.g. "you used `<function_calls>` syntax — please use
    # fenced JSON instead").
    hints: list[str] = field(default_factory=list)


class ToolBackend(Protocol):
    """The one interface every backend implements.

    A backend is stateless — the per-trial state (messages, transcript,
    usage tallies) lives on the `ModelClient` and on the caller. The
    backend's job is the round-trip: send one step, parse the response
    into actions.
    """

    name: str

    def system_prompt_addendum(self, tools: list[ToolSpec]) -> str:
        """Text to append to the trial's system prompt to teach the
        model about the available tools.

        Returns "" when the backend conveys tools through the API
        (native, schema-enforced). Returns a rendered markdown block
        for backends that have to describe tools in the prompt
        (prompt_json).
        """
        ...

    def request(
        self,
        client: ModelClient,
        tools: list[ToolSpec],
    ) -> ActionResponse:
        """Issue one step against the client; return parsed actions."""
        ...

    def send_results(
        self,
        client: ModelClient,
        calls: list[ToolCall],
        results: list[ToolResult],
    ) -> None:
        """Append tool results to the conversation, in this backend's wire format.

        Native/Schema:  uses the API's tool_result blocks (call_ids must match
                        the ToolCalls returned by the most recent request()).
        PromptJSON:     formats results as a JSON block in a user text message,
                        including the `op` name from `calls` so the model can
                        line results up with its requests.

        `calls` and `results` are parallel lists in the same order.
        """
        ...

    def send_hint(
        self,
        client: ModelClient,
        hint: str,
    ) -> None:
        """Append a non-result nudge to the conversation.

        Used when the last turn yielded NO actions to dispatch (model
        narrated only, mimicked the wrong format, etc.). Implementations
        must NOT call `add_tool_results` here — there's nothing to match.
        """
        ...

    def render_results_text(
        self,
        calls: list[ToolCall],
        results: list[ToolResult],
    ) -> str:
        """Optional: render results as plain text for transcript logging."""
        ...

    def request_terminal(
        self,
        client: ModelClient,
        tools: list[ToolSpec],
        terminal_tool: str,
    ) -> ActionResponse:
        """Last-turn variant of request(): force the model to call `terminal_tool`.

        Backends with format constraints that suppress the model's
        natural "I'm done" reasoning (e.g. SchemaEnforcedBackend with
        tool_choice=any) need this escape valve so a long run still
        produces a final answer. Backends without that problem default
        to plain request().
        """
        ...
