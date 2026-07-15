"""Streaming helper for Chat-Completions-compatible clients.

OpenRouter uses this Chat Completions path. OpenAI's native client uses the
Responses API and its sibling `_openai_responses_stream` helper.
"""

from __future__ import annotations

import time
from typing import Any

from openai import BadRequestError


# Stream event types that carry the first *generated* token — the boundary
# between TTFT and generate. This matches the Anthropic/Google clients, which
# likewise mark the first content delta rather than the block/role preamble.
_FIRST_TOKEN_EVENTS = (
    "content.delta",
    "refusal.delta",
    "tool_calls.function.arguments.delta",
)


def stream_step_with_latency(
    client: Any, kwargs: dict[str, Any]
) -> tuple[Any, float, float]:
    """Run a Chat Completions call as a stream; return (completion, ttft, generate).

    Streaming lets us timestamp the first generated token. `get_final_completion()`
    reassembles the exact ChatCompletion a non-streamed `create()` would return,
    so the caller parses the result identically either way.

    Some models/orgs cannot stream — OpenAI gates streaming for certain models
    behind org verification, returning a 400 on the `stream` param. When that is
    the reason for failure we transparently fall back to a non-streamed
    `create()`; ttft/generate are then 0.0 (unmeasurable without a stream) and
    the caller's wall-clock latency carries the whole number. Any other error
    (bad tool schema, over-long context, rate limit, ...) propagates unchanged.
    """
    t0 = time.monotonic()
    t_first: float | None = None
    try:
        with client.chat.completions.stream(
            **kwargs, stream_options={"include_usage": True}
        ) as stream:
            for event in stream:
                if (
                    t_first is None
                    and getattr(event, "type", None) in _FIRST_TOKEN_EVENTS
                ):
                    t_first = time.monotonic()
            resp = stream.get_final_completion()
    except BadRequestError as exc:
        if not _is_streaming_unsupported(exc):
            raise
        return client.chat.completions.create(**kwargs), 0.0, 0.0
    t_end = time.monotonic()
    ttft = (t_first if t_first is not None else t_end) - t0
    generate = (t_end - t_first) if t_first is not None else 0.0
    return resp, ttft, generate


def _is_streaming_unsupported(exc: BadRequestError) -> bool:
    """True when a 400 means "this model/org may not stream" (vs a real bad request).

    Matched narrowly so genuine 400s still surface: the error either targets the
    `stream` param, or its message calls out streaming + verification. When we
    guess wrong the fallback `create()` simply re-raises the same 400, so a
    mismatch costs one extra call, never a swallowed error.
    """
    if getattr(exc, "param", None) == "stream":
        return True
    msg = str(getattr(exc, "message", "") or exc).lower()
    return "stream" in msg and "verif" in msg
