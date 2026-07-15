"""OpenAI Responses API client.

Quirks handled:
  - Tool schemas are translated from Anthropic shape ({name, description,
    input_schema}) to the flat Responses function-tool shape.
  - Responses are not stored server-side; encrypted reasoning items are
    replayed with the manually managed history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from agent_eval.models._openai_responses_stream import stream_response_with_latency
from agent_eval.types import (
    AssistantMessage,
    ModelClient,
    ToolCall,
    ToolResult,
    TurnUsage,
)


OPENAI_MODELS: dict[str, str] = {
    # Current families (web-verified 2026-07-15, developers.openai.com).
    "gpt-5.6": "gpt-5.6",
    "gpt-5.6-sol": "gpt-5.6-sol",
    "gpt-5.6-terra": "gpt-5.6-terra",
    "gpt-5.6-luna": "gpt-5.6-luna",
    # Historical baselines remain resolvable so prior results reproduce.
    "gpt-5.5": "gpt-5.5",
    "gpt-5.5-pro": "gpt-5.5-pro",
    "gpt-5.4": "gpt-5.4",
    "gpt-5.4-mini": "gpt-5.4-mini",
    "gpt-5.4-nano": "gpt-5.4-nano",
    # Legacy — no longer on the pricing page; may still route. Kept so older
    # results/configs resolve.
    "gpt-5": "gpt-5",
    "gpt-5-mini": "gpt-5-mini",
}


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-shape schemas to Responses function-tool shape."""
    return [
        {
            "type": "function",
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            # Preserve the permissive behavior of the former Chat Completions
            # integration. Strict schemas can be tested as a protocol arm.
            "strict": False,
        }
        for t in tools
    ]


def _item_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    dump = getattr(item, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True)
    return dict(vars(item))


def _response_text(output: list[Any]) -> str:
    chunks: list[str] = []
    for item in output:
        if getattr(item, "type", None) != "message":
            continue
        for block in getattr(item, "content", []) or []:
            if getattr(block, "type", None) == "output_text":
                chunks.append(getattr(block, "text", "") or "")
    return "".join(chunks)


@dataclass
class _OpenAIClient(ModelClient):
    model_id: str
    max_tokens: int = 8192
    reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        self.client = OpenAI()
        self.system: str = ""
        self.messages: list[dict[str, Any]] = []

    def reset(self, system: str) -> None:
        self.system = system
        self.messages = []

    def add_user_text(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for r in results:
            self.messages.append(
                {
                    "type": "function_call_output",
                    "call_id": r.call_id,
                    "output": r.content if r.status == "ok" else f"ERROR: {r.content}",
                }
            )

    def step(
        self,
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
    ) -> AssistantMessage:
        kwargs: dict[str, Any] = dict(
            model=self.model_id,
            instructions=self.system,
            input=self.messages,
            max_output_tokens=self.max_tokens,
            store=False,
            include=["reasoning.encrypted_content"],
        )
        if self.reasoning_effort is not None:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        if tools:
            kwargs["tools"] = _convert_tools(tools)
        if tool_choice is not None and tools:
            # Translate Anthropic-shape tool_choice to OpenAI's shape.
            # Anthropic: {"type": "any"} / {"type": "tool", "name": "X"}
            # Responses: "required" / {"type": "function", "name": "X"}
            if tool_choice.get("type") == "any":
                kwargs["tool_choice"] = "required"
            elif tool_choice.get("type") == "tool" and tool_choice.get("name"):
                kwargs["tool_choice"] = {
                    "type": "function",
                    "name": tool_choice["name"],
                }

        resp, ttft, generate = stream_response_with_latency(self.client, kwargs)
        output = list(getattr(resp, "output", []) or [])
        # Replay every output item, including reasoning items. With store=False,
        # encrypted reasoning content is what preserves multi-turn reasoning.
        self.messages.extend(_item_dict(item) for item in output)
        text = _response_text(output)

        calls: list[ToolCall] = []
        for item in output:
            if getattr(item, "type", None) != "function_call":
                continue
            arguments = getattr(item, "arguments", "") or "{}"
            try:
                args = json.loads(arguments)
            except json.JSONDecodeError:
                args = {"__parse_error__": arguments}
            calls.append(
                ToolCall(
                    name=getattr(item, "name", ""),
                    arguments=args,
                    call_id=getattr(item, "call_id", ""),
                )
            )

        usage_obj = resp.usage
        input_details = getattr(usage_obj, "input_tokens_details", None)
        cached = getattr(input_details, "cached_tokens", 0) or 0
        total_input = getattr(usage_obj, "input_tokens", 0) or 0
        usage = TurnUsage(
            # Responses input_tokens includes cached tokens; TurnUsage keeps
            # billable uncached and cached input separate.
            input_tokens=max(0, total_input - cached),
            cache_read_tokens=cached,
            output_tokens=getattr(usage_obj, "output_tokens", 0) or 0,
            ttft_seconds=ttft,
            generate_seconds=generate,
        )
        return AssistantMessage(
            text=text, tool_calls=calls, usage=usage, raw=resp.model_dump()
        )


def make_openai_client(model_id: str) -> ModelClient:
    return _OpenAIClient(model_id=model_id)
