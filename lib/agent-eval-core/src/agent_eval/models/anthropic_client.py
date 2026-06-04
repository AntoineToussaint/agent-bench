"""Anthropic Messages API client.

Quirks handled:
  - The Opus 4 family (4.7, 4.8) deprecated `temperature`; skip the param for
    those models.
  - System prompt gets ephemeral cache control to enable prompt caching.
  - tool_use blocks are translated into provider-agnostic ToolCall objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic
from anthropic.types import Message

from agent_eval.types import AssistantMessage, ModelClient, ToolCall, ToolResult, TurnUsage


ANTHROPIC_MODELS: dict[str, str] = {
    "claude-opus-4-8": "claude-opus-4-8",   # current flagship (2026)
    "claude-opus-4-7": "claude-opus-4-7",   # legacy, still callable
    "claude-sonnet-4-6": "claude-sonnet-4-6",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
}


@dataclass
class _AnthropicClient(ModelClient):
    model_id: str
    max_tokens: int = 8192
    temperature: float = 0.0

    def __post_init__(self) -> None:
        self.client = Anthropic()
        self.system: str = ""
        self.messages: list[dict[str, Any]] = []

    def reset(self, system: str) -> None:
        self.system = system
        self.messages = []

    def add_user_text(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_tool_results(self, results: list[ToolResult]) -> None:
        content: list[dict[str, Any]] = [
            {
                "type": "tool_result",
                "tool_use_id": r.call_id,
                "content": r.content,
                "is_error": r.status == "error",
            }
            for r in results
        ]
        self.messages.append({"role": "user", "content": content})

    def step(
        self,
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
    ) -> AssistantMessage:
        """Issue one round-trip against the API.

        Args:
            tools: Anthropic tool_use schemas (`{name, description, input_schema}`).
                Pass an empty list to disable tool_use entirely.
            tool_choice: optional Anthropic tool_choice. None defaults to
                Anthropic's standard "auto" behavior. Pass `{"type": "any"}`
                to force the model to call SOME tool (no free-form text or
                mimicry possible — used by SchemaEnforcedBackend). Pass
                `{"type": "tool", "name": "<name>"}` to force a specific tool.
        """
        kwargs: dict[str, Any] = dict(
            model=self.model_id,
            max_tokens=self.max_tokens,
            system=[
                {
                    "type": "text",
                    "text": self.system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=self.messages,
        )
        # The Opus 4 family (4.7, 4.8) deprecated `temperature`; skip it there.
        if not self.model_id.startswith("claude-opus-4"):
            kwargs["temperature"] = self.temperature
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        # Stream so we can split latency into TTFT (queue + prefill) and generate
        # (decode). We still assemble the same final Message + usage as create().
        import time

        t0 = time.monotonic()
        t_first: float | None = None
        with self.client.messages.stream(**kwargs) as stream:
            for event in stream:
                if t_first is None and getattr(event, "type", None) in (
                    "content_block_start",
                    "content_block_delta",
                ):
                    t_first = time.monotonic()
            msg = stream.get_final_message()
        t_end = time.monotonic()
        ttft = (t_first if t_first is not None else t_end) - t0
        generate = (t_end - t_first) if t_first is not None else 0.0

        self.messages.append({"role": "assistant", "content": msg.content})
        return _to_assistant_message(msg, ttft_seconds=ttft, generate_seconds=generate)


def _to_assistant_message(
    msg: Message, *, ttft_seconds: float = 0.0, generate_seconds: float = 0.0
) -> AssistantMessage:
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in msg.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(block.text)  # type: ignore[attr-defined]
        elif btype == "tool_use":
            args = block.input if isinstance(block.input, dict) else {}  # type: ignore[attr-defined]
            calls.append(
                ToolCall(name=block.name, arguments=args, call_id=block.id)  # type: ignore[attr-defined]
            )
    usage = TurnUsage(
        input_tokens=msg.usage.input_tokens,
        output_tokens=msg.usage.output_tokens,
        cache_read_tokens=getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(msg.usage, "cache_creation_input_tokens", 0) or 0,
        ttft_seconds=ttft_seconds,
        generate_seconds=generate_seconds,
    )
    return AssistantMessage(
        text="\n".join(text_parts), tool_calls=calls, usage=usage, raw=msg.model_dump()
    )


def make_anthropic_client(model_id: str) -> ModelClient:
    return _AnthropicClient(model_id=model_id)
