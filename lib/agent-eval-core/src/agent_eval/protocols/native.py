"""Native tool_use backend.

The model is given the tool schemas through the provider's native tool_use
channel (Anthropic `tools=`, OpenAI `tools=`, etc.). `tool_choice="auto"`,
so the model can choose to call a tool OR to emit free-form text instead.

This is the *current* `turn_loop_trial.py` behavior, just wrapped in the
backend interface. We use it as the baseline because it's what every
agent today does — including Claude Code, Cursor, Aider, ChatGPT.

What it can't prevent: the model emitting narration around tool calls,
or producing zero tool calls in a turn. That's where SchemaEnforcedBackend
goes further by setting `tool_choice="any"`.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_eval.types import ModelClient, ToolCall, ToolResult

from .types import ActionResponse, ToolSpec


@dataclass
class NativeToolUseBackend:
    name: str = "native"

    def system_prompt_addendum(self, tools: list[ToolSpec]) -> str:
        # Tools are conveyed through the API; nothing to add to the prompt.
        return ""

    def request(
        self,
        client: ModelClient,
        tools: list[ToolSpec],
    ) -> ActionResponse:
        schemas = [t.as_anthropic_tool() for t in tools]
        msg = client.step(schemas)
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
        # Native has no format constraint suppressing the model's reasoning;
        # the model would normally decide to call `done` on its own. We
        # nudge it via tool_choice; if the model still has reasoning to do
        # it'll mix text + the forced call.
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
