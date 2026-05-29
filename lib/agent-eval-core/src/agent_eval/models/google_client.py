"""Google Gemini API client.

Uses the unified `google-genai` SDK (the legacy `google-generativeai` is
deprecated). Auth via the GEMINI_API_KEY env var (AI Studio key); Vertex
AI works through the same client by passing `vertexai=True` to the
Client constructor, but we don't expose that here.

Quirks handled:
  - Anthropic-shape tool schemas are converted to Gemini's
    `FunctionDeclaration` form (rename `input_schema` → `parameters`,
    strip JSON-Schema keywords Gemini rejects).
  - Gemini's `tool_config.function_calling_config.mode` is the analog of
    Anthropic's `tool_choice`: AUTO (default), ANY (force a call),
    NONE (forbid calls). A specific-tool forcing is supported via
    `allowed_function_names`.
  - Tool results in conversation history use `Part(function_response=...)`
    blocks (Gemini's tool_result equivalent).
  - Usage metadata field names: `prompt_token_count` /
    `candidates_token_count` / `cached_content_token_count`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types as gtypes

from agent_eval.types import AssistantMessage, ModelClient, ToolCall, ToolResult, TurnUsage


def _resolve_api_key() -> str | None:
    """Find a Gemini key under any of the common env var names.

    The SDK reads `GEMINI_API_KEY` or `GOOGLE_API_KEY`. Some user
    setups stash it under `GOOGLE_AI_STUDIO_API_KEY`. Accept all.
    Returns None if no key set — let the SDK raise its own error.
    """
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_AI_STUDIO_API_KEY"):
        v = os.environ.get(name)
        if v:
            return v
    return None


# Public model id → API model id. Stable IDs as of 2026-05.
GOOGLE_MODELS: dict[str, str] = {
    # Current 3.x (web-verified 2026-05-29, ai.google.dev pricing).
    "gemini-3.5-flash": "gemini-3.5-flash",
    "gemini-3.1-pro-preview": "gemini-3.1-pro-preview",
    "gemini-3.1-flash-lite": "gemini-3.1-flash-lite",
    # 2.5 line — still listed/supported.
    "gemini-2.5-pro": "gemini-2.5-pro",
    "gemini-2.5-flash": "gemini-2.5-flash",
    "gemini-2.5-flash-lite": "gemini-2.5-flash-lite",
}


# JSON-Schema keywords Gemini's schema subset rejects. Stripped before
# conversion. Empirically: `$schema`, `$ref`, `additionalProperties`,
# `oneOf` cause 400s; tightening the list later is cheaper than chasing
# silent failures.
_GEMINI_REJECTED_KEYS: frozenset[str] = frozenset(
    {"$schema", "$ref", "additionalProperties", "oneOf"}
)


def _clean_schema(node: Any) -> Any:
    """Recursively strip Gemini-incompatible JSON-Schema keywords."""
    if isinstance(node, dict):
        return {
            k: _clean_schema(v) for k, v in node.items() if k not in _GEMINI_REJECTED_KEYS
        }
    if isinstance(node, list):
        return [_clean_schema(x) for x in node]
    return node


def _anthropic_tool_to_gemini(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert one Anthropic-shape tool dict into a Gemini FunctionDeclaration.

    Anthropic uses `input_schema`; Gemini uses `parameters`. The schema
    body is otherwise the same JSON-Schema dialect (with the rejection
    list above).
    """
    params = _clean_schema(tool.get("input_schema") or {})
    # Gemini rejects FunctionDeclaration with completely empty parameters
    # when mode=ANY is requested; ensure at least the empty-object shape.
    if not params:
        params = {"type": "object", "properties": {}}
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": params,
    }


def _to_gemini_tool_config(
    tool_choice: dict[str, Any] | None,
) -> gtypes.ToolConfig | None:
    """Translate provider-agnostic tool_choice to Gemini ToolConfig.

    Mapping:
      None                              → AUTO (default; return None)
      {"type": "any"}                   → ANY (force some tool call)
      {"type": "tool", "name": "X"}     → ANY + allowed_function_names=["X"]
      {"type": "auto"}                  → AUTO
    """
    if tool_choice is None:
        return None
    kind = tool_choice.get("type")
    if kind == "any":
        return gtypes.ToolConfig(
            function_calling_config=gtypes.FunctionCallingConfig(mode="ANY")
        )
    if kind == "tool" and isinstance(tool_choice.get("name"), str):
        return gtypes.ToolConfig(
            function_calling_config=gtypes.FunctionCallingConfig(
                mode="ANY", allowed_function_names=[tool_choice["name"]]
            )
        )
    # AUTO is the default; explicit auto = None
    return None


@dataclass
class _GoogleClient(ModelClient):
    model_id: str
    max_tokens: int = 8192
    temperature: float = 0.0

    def __post_init__(self) -> None:
        api_key = _resolve_api_key()
        self.client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self.system: str = ""
        # Gemini's chat history shape: list of `Content` objects, each
        # with role ("user" | "model") and parts. We keep dicts and
        # let the SDK accept them or wrap to types.Content if needed.
        self.history: list[gtypes.Content] = []
        # Track tool_use ids → function names so a later
        # add_tool_results call can match them up. Anthropic's tool_result
        # is keyed by call_id; Gemini's function_response is keyed by
        # function name + optional id-as-id.
        self._call_name_by_id: dict[str, str] = {}

    def reset(self, system: str) -> None:
        self.system = system
        self.history = []
        self._call_name_by_id = {}

    def add_user_text(self, text: str) -> None:
        self.history.append(
            gtypes.Content(role="user", parts=[gtypes.Part(text=text)])
        )

    def add_tool_results(self, results: list[ToolResult]) -> None:
        # Gemini groups function_response parts as a single user-role turn.
        parts: list[gtypes.Part] = []
        for r in results:
            name = self._call_name_by_id.get(r.call_id, "")
            payload: dict[str, Any] = {"content": r.content}
            if r.status == "error":
                payload["error"] = r.content
            parts.append(
                gtypes.Part(
                    function_response=gtypes.FunctionResponse(
                        id=r.call_id,
                        name=name,
                        response=payload,
                    )
                )
            )
        self.history.append(gtypes.Content(role="user", parts=parts))

    def step(
        self,
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
    ) -> AssistantMessage:
        gemini_tools: list[gtypes.Tool] | None = None
        if tools:
            decls = [_anthropic_tool_to_gemini(t) for t in tools]
            gemini_tools = [gtypes.Tool(function_declarations=decls)]

        config_kwargs: dict[str, Any] = dict(
            system_instruction=self.system or None,
            # Gemini accepts temperature for every current model; we still
            # set it to keep determinism in line with other clients.
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
        )
        if gemini_tools:
            config_kwargs["tools"] = gemini_tools
            tc = _to_gemini_tool_config(tool_choice)
            if tc is not None:
                config_kwargs["tool_config"] = tc

        resp = self.client.models.generate_content(
            model=self.model_id,
            contents=self.history,
            config=gtypes.GenerateContentConfig(**config_kwargs),
        )

        # Append the model's response to history so the next turn sees it.
        if resp.candidates and resp.candidates[0].content:
            self.history.append(resp.candidates[0].content)

        return _to_assistant_message(resp, self._call_name_by_id)


def _to_assistant_message(
    resp: Any,
    call_name_by_id: dict[str, str],
) -> AssistantMessage:
    """Convert a Gemini GenerateContentResponse to our AssistantMessage."""
    text_parts: list[str] = []
    calls: list[ToolCall] = []

    candidates = getattr(resp, "candidates", None) or []
    if candidates and candidates[0].content and candidates[0].content.parts:
        for i, part in enumerate(candidates[0].content.parts):
            fc = getattr(part, "function_call", None)
            if fc is not None and getattr(fc, "name", None):
                # Gemini sometimes returns an explicit call id; if absent,
                # synthesize one so the harness can pair the response.
                call_id = getattr(fc, "id", None) or f"gem_{i:03d}"
                args = dict(fc.args) if fc.args else {}
                calls.append(ToolCall(name=fc.name, arguments=args, call_id=call_id))
                call_name_by_id[call_id] = fc.name
                continue
            text = getattr(part, "text", None)
            if text:
                text_parts.append(text)

    usage_meta = getattr(resp, "usage_metadata", None)
    usage = TurnUsage(
        input_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
        output_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
        cache_read_tokens=getattr(usage_meta, "cached_content_token_count", 0) or 0,
        cache_creation_tokens=0,  # Gemini doesn't separately bill cache writes
    )

    return AssistantMessage(
        text="\n".join(text_parts),
        tool_calls=calls,
        usage=usage,
        raw={"model": getattr(resp, "model_version", None)},
    )


def make_google_client(model_id: str) -> ModelClient:
    return _GoogleClient(model_id=model_id)
