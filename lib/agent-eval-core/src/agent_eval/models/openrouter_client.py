"""OpenRouter client — uses an OpenAI-compatible API to access Gemini, Grok,
DeepSeek, Llama, Qwen, and many other models through a single key.

OPENROUTER_API_KEY is required at runtime. Tool support varies by underlying
model; check https://openrouter.ai/docs#tool-calling for the current list of
models that route tool_use cleanly.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from agent_eval.types import AssistantMessage, ModelClient, ToolCall, ToolResult, TurnUsage


# Curated short names → OpenRouter model IDs. Extend as needed.
# Pricing for these lives in pricing.py.
OPENROUTER_MODELS: dict[str, str] = {
    # Google
    "gemini-2.5-pro": "google/gemini-2.5-pro",
    "gemini-2.5-flash": "google/gemini-2.5-flash",
    # xAI
    "grok-4": "x-ai/grok-4",
    "grok-4-fast": "x-ai/grok-4-fast",
    # DeepSeek
    "deepseek-v3.1": "deepseek/deepseek-chat-v3.1",
    "deepseek-r1": "deepseek/deepseek-r1",
    # Meta
    "llama-4-scout": "meta-llama/llama-4-scout",
    "llama-4-maverick": "meta-llama/llama-4-maverick",
    # Alibaba
    "qwen-3-coder": "qwen/qwen3-coder",
}


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
class _OpenRouterClient(ModelClient):
    model_id: str
    max_tokens: int = 8192
    temperature: float = 0.0

    def __post_init__(self) -> None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY not set. Sign up at https://openrouter.ai "
                "and put the key in your .env to use OpenRouter-routed models."
            )
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
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
            temperature=self.temperature,
        )
        if tools:
            kwargs["tools"] = _convert_tools(tools)
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


def make_openrouter_client(model_id: str) -> ModelClient:
    return _OpenRouterClient(model_id=model_id)
