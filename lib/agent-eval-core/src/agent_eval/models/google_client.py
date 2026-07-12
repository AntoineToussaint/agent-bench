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

        # Stream so we can split latency into TTFT (queue + prefill) and generate
        # (decode). Gemini's SDK has no final-response accumulator, so we assemble
        # the text + function-call parts and usage ourselves as chunks arrive.
        import time

        t0 = time.monotonic()
        t_first: float | None = None
        text_parts: list[str] = []
        fc_parts: list[gtypes.Part] = []
        usage_meta: Any = None
        model_version: str | None = None
        for chunk in self.client.models.generate_content_stream(
            model=self.model_id,
            contents=self.history,
            config=gtypes.GenerateContentConfig(**config_kwargs),
        ):
            cand = (getattr(chunk, "candidates", None) or [None])[0]
            content = getattr(cand, "content", None) if cand is not None else None
            for part in getattr(content, "parts", None) or []:
                # Mark TTFT at the first part carrying real output (a call or
                # non-empty text) — consistent with the Anthropic/OpenAI clients,
                # which mark the first content delta. Empty preamble parts don't
                # count.
                if getattr(part, "function_call", None) is not None:
                    fc_parts.append(part)
                    if t_first is None:
                        t_first = time.monotonic()
                elif getattr(part, "text", None):
                    text_parts.append(part.text)
                    if t_first is None:
                        t_first = time.monotonic()
            um = getattr(chunk, "usage_metadata", None)
            if um is not None:
                usage_meta = um
            model_version = getattr(chunk, "model_version", None) or model_version
        t_end = time.monotonic()
        ttft = (t_first if t_first is not None else t_end) - t0
        generate = (t_end - t_first) if t_first is not None else 0.0

        # Reassemble the model turn for history: merged text (streamed as
        # fragments, so concatenate) followed by the complete call parts.
        full_text = "".join(text_parts)
        assembled: list[gtypes.Part] = []
        if full_text:
            assembled.append(gtypes.Part(text=full_text))
        assembled.extend(fc_parts)
        if assembled:
            self.history.append(gtypes.Content(role="model", parts=assembled))

        return _build_assistant_message(
            full_text, fc_parts, usage_meta, model_version, self._call_name_by_id,
            ttft_seconds=ttft, generate_seconds=generate,
        )


def _build_assistant_message(
    text: str,
    fc_parts: list[Any],
    usage_meta: Any,
    model_version: str | None,
    call_name_by_id: dict[str, str],
    *,
    ttft_seconds: float = 0.0,
    generate_seconds: float = 0.0,
) -> AssistantMessage:
    """Assemble our AssistantMessage from streamed Gemini parts + usage."""
    calls: list[ToolCall] = []
    for i, part in enumerate(fc_parts):
        fc = getattr(part, "function_call", None)
        if fc is None or not getattr(fc, "name", None):
            continue
        # Gemini sometimes returns an explicit call id; if absent, synthesize
        # one so the harness can pair the eventual function_response.
        call_id = getattr(fc, "id", None) or f"gem_{i:03d}"
        args = dict(fc.args) if fc.args else {}
        calls.append(ToolCall(name=fc.name, arguments=args, call_id=call_id))
        call_name_by_id[call_id] = fc.name

    usage = TurnUsage(
        input_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
        output_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
        cache_read_tokens=getattr(usage_meta, "cached_content_token_count", 0) or 0,
        cache_creation_tokens=0,  # Gemini doesn't separately bill cache writes
        ttft_seconds=ttft_seconds,
        generate_seconds=generate_seconds,
    )

    return AssistantMessage(
        text=text,
        tool_calls=calls,
        usage=usage,
        raw={"model": model_version},
    )


def make_google_client(model_id: str) -> ModelClient:
    return _GoogleClient(model_id=model_id)
