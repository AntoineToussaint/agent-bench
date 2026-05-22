"""OpenAI Chat Completions client.

Quirks handled:
  - GPT-5 family rejects `temperature != 1`. We skip the param entirely.
  - Tool schemas are translated from Anthropic shape ({name, description,
    input_schema}) to OpenAI shape ({type: function, function: {...}}).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from agent_eval.types import AssistantMessage, ModelClient, ToolCall, ToolResult, TurnUsage


OPENAI_MODELS: dict[str, str] = {
    "gpt-5": "gpt-5",
    "gpt-5-mini": "gpt-5-mini",
}


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-shape schemas to OpenAI function-tool shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


@dataclass
class _OpenAIClient(ModelClient):
    model_id: str
    max_tokens: int = 8192
    temperature: float = 0.0

    def __post_init__(self) -> None:
        self.client = OpenAI()
        self.system: str = ""
        self.messages: list[dict[str, Any]] = []

    def reset(self, system: str) -> None:
        self.system = system
        self.messages = [{"role": "system", "content": system}]

    def add_user_text(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for r in results:
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": r.call_id,
                    "content": r.content if r.status == "ok" else f"ERROR: {r.content}",
                }
            )

    def step(self, tools: list[dict[str, Any]]) -> AssistantMessage:
        kwargs: dict[str, Any] = dict(
            model=self.model_id,
            messages=self.messages,
            max_completion_tokens=self.max_tokens,
        )
        if tools:
            kwargs["tools"] = _convert_tools(tools)
        # GPT-5 family only accepts the default temperature.
        if not self.model_id.startswith("gpt-5"):
            kwargs["temperature"] = self.temperature
        resp = self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message

        assistant_entry: dict[str, Any] = {
            "role": "assistant",
            "content": choice.content or "",
        }
        if choice.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in choice.tool_calls
            ]
        self.messages.append(assistant_entry)

        calls: list[ToolCall] = []
        for tc in choice.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"__parse_error__": tc.function.arguments}
            calls.append(ToolCall(name=tc.function.name, arguments=args, call_id=tc.id))

        usage_obj = resp.usage
        usage = TurnUsage(
            input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        )
        return AssistantMessage(
            text=choice.content or "", tool_calls=calls, usage=usage, raw=resp.model_dump()
        )


def make_openai_client(model_id: str) -> ModelClient:
    return _OpenAIClient(model_id=model_id)
