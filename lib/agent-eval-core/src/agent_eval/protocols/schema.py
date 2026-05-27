"""Schema-enforced tool_use backend.

Same wire format as `native` — the provider's tool_use channel — but with
`tool_choice={"type": "any"}` (Anthropic) / `"required"` (OpenAI), forcing
the model to emit AT LEAST ONE tool call per turn. The model can't emit
free-form text instead, and it can't produce `<function_calls>` mimicry
because the decoder is constrained to start a real tool_use block.

This is the cheapest reliable counter to "format anchoring" — the failure
mode where a model RL'd on tool_use reverts to that format even when asked
for a different one. By keeping tool_use as the wire format but TIGHTENING
the choice, we get the model's training prior on our side.

Caveats:
  - It can't force GOOD tool calls — the model can still call the wrong
    tool with the wrong args. Schema enforcement is about format, not
    semantics.
  - On every turn the model MUST emit a tool. If the work is done, the
    trial needs a `done` / `submit` tool in the surface, otherwise the
    model has no way to say "I'm finished."
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_eval.types import ModelClient, ToolCall, ToolResult

from .types import ActionResponse, ToolSpec


@dataclass
class SchemaEnforcedBackend:
    name: str = "schema_enforced"

    def system_prompt_addendum(self, tools: list[ToolSpec]) -> str:
        return ""

    def request(
        self,
        client: ModelClient,
        tools: list[ToolSpec],
    ) -> ActionResponse:
        schemas = [t.as_anthropic_tool() for t in tools]
        # Anthropic-shape tool_choice. Each client translates as needed.
        msg = client.step(schemas, tool_choice={"type": "any"})
        return ActionResponse(
            actions=msg.tool_calls,
            raw_text=msg.text,
            invalid_attempts=0,
            usage=msg.usage,
            backend_name=self.name,
        )

    def send_results(
        self,
        client: ModelClient,
        calls: list[ToolCall],
        results: list[ToolResult],
    ) -> None:
        client.add_tool_results(results)

    def send_hint(self, client: ModelClient, hint: str) -> None:
        client.add_user_text(hint)

    def render_results_text(
        self,
        calls: list[ToolCall],
        results: list[ToolResult],
    ) -> str:
        return "\n".join(
            f"[{c.name} / {r.call_id}] {r.status}: {r.content}"
            for c, r in zip(calls, results)
        )

    def request_terminal(
        self,
        client: ModelClient,
        tools: list[ToolSpec],
        terminal_tool: str,
    ) -> ActionResponse:
        # Schema-enforced's whole problem is the model can't decide to
        # stop exploring under tool_choice=any. Force the terminal tool
        # so we always get an answer instead of timing out.
        schemas = [t.as_anthropic_tool() for t in tools]
        msg = client.step(
            schemas,
            tool_choice={"type": "tool", "name": terminal_tool},
        )
        return ActionResponse(
            actions=msg.tool_calls,
            raw_text=msg.text,
            invalid_attempts=0,
            usage=msg.usage,
            backend_name=self.name,
        )
