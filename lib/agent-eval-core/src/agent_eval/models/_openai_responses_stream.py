"""Streaming helper for OpenAI's Responses API."""

from __future__ import annotations

import time
from typing import Any

from openai import BadRequestError

from agent_eval.models._openai_stream import _is_streaming_unsupported


_FIRST_TOKEN_EVENTS = (
    "response.output_text.delta",
    "response.refusal.delta",
    "response.function_call_arguments.delta",
)


def stream_response_with_latency(
    client: Any, kwargs: dict[str, Any]
) -> tuple[Any, float, float]:
    """Run a Responses request and return (response, TTFT, generate time).

    A narrow non-streaming fallback mirrors the Chat Completions helper used by
    OpenRouter. Other bad requests still propagate unchanged.
    """
    t0 = time.monotonic()
    t_first: float | None = None
    try:
        with client.responses.stream(**kwargs) as stream:
            for event in stream:
                if (
                    t_first is None
                    and getattr(event, "type", None) in _FIRST_TOKEN_EVENTS
                ):
                    t_first = time.monotonic()
            response = stream.get_final_response()
    except BadRequestError as exc:
        if not _is_streaming_unsupported(exc):
            raise
        return client.responses.create(**kwargs), 0.0, 0.0

    t_end = time.monotonic()
    ttft = (t_first if t_first is not None else t_end) - t0
    generate = (t_end - t_first) if t_first is not None else 0.0
    return response, ttft, generate
