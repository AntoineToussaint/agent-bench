"""Streaming TTFT/generate split for the OpenAI + Google clients (NEXT.md #32).

These fake the SDK stream objects so we can exercise the real assembly loops
(TTFT capture, message reconstruction, usage plumbing) without a network call
or API key. Small real sleeps make the ttft/generate split observable and
ordered without depending on wall-clock values.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError


# --------------------------------------------------------------------------- #
# OpenAI                                                                       #
# --------------------------------------------------------------------------- #
class _FakeOAIStream:
    """Stands in for the ChatCompletionStreamManager context manager."""

    def __init__(self, events, final):
        self._events = events
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for e in self._events:
            if e.type == "content.delta" or e.type.endswith("arguments.delta"):
                time.sleep(0.003)  # simulate prefill before the first token
            yield e
            time.sleep(0.001)  # simulate decode between tokens

    def get_final_completion(self):
        return self._final


def _make_openai(monkeypatch, events, final):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from agent_eval.models.openai_client import _OpenAIClient

    c = _OpenAIClient(model_id="gpt-5.4")
    c.reset("system")
    c.add_user_text("hi")
    c.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(stream=lambda **kw: _FakeOAIStream(events, final))
        )
    )
    return c


def test_openai_stream_splits_latency_text(monkeypatch):
    events = [SimpleNamespace(type="content.delta"), SimpleNamespace(type="content.done")]
    final = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5),
        model_dump=lambda: {"id": "x"},
    )
    c = _make_openai(monkeypatch, events, final)
    msg = c.step(tools=[])
    assert msg.text == "hello"
    assert msg.usage.input_tokens == 12
    assert msg.usage.output_tokens == 5
    assert msg.usage.ttft_seconds > 0.0
    assert msg.usage.generate_seconds > 0.0


def test_openai_stream_splits_latency_tool_call(monkeypatch):
    events = [
        SimpleNamespace(type="tool_calls.function.arguments.delta"),
        SimpleNamespace(type="tool_calls.function.arguments.done"),
    ]
    tc = SimpleNamespace(
        id="call_1", function=SimpleNamespace(name="edit", arguments='{"path": "a.py"}')
    )
    final = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tc]))],
        usage=SimpleNamespace(prompt_tokens=30, completion_tokens=8),
        model_dump=lambda: {"id": "y"},
    )
    c = _make_openai(monkeypatch, events, final)
    msg = c.step(tools=[{"name": "edit", "input_schema": {}}])
    assert [t.name for t in msg.tool_calls] == ["edit"]
    assert msg.tool_calls[0].arguments == {"path": "a.py"}
    assert msg.usage.ttft_seconds > 0.0


def test_openai_no_content_events_zero_generate(monkeypatch):
    # A stream that never emits a content/tool delta (edge case) must not blow
    # up: ttft falls back to total, generate collapses to 0.
    events = [SimpleNamespace(type="chunk")]
    final = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=0),
        model_dump=lambda: {},
    )
    c = _make_openai(monkeypatch, events, final)
    msg = c.step(tools=[])
    assert msg.usage.generate_seconds == 0.0
    assert msg.usage.ttft_seconds >= 0.0


def _bad_request(message, param=None):
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return BadRequestError(
        message, response=httpx.Response(400, request=req), body={"param": param}
    )


def test_openai_falls_back_to_create_when_streaming_unsupported(monkeypatch):
    # OpenAI gates streaming for some models behind org verification: a 400 on
    # `stream`. We should transparently retry non-streamed and report 0 split.
    def _raise(**kw):
        raise _bad_request(
            "Your organization must be verified to stream this model.", param="stream"
        )

    created = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="fallback", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2),
        model_dump=lambda: {"id": "fb"},
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from agent_eval.models.openai_client import _OpenAIClient

    c = _OpenAIClient(model_id="gpt-5.4")
    c.reset("system")
    c.add_user_text("hi")
    c.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(stream=_raise, create=lambda **kw: created)
        )
    )
    msg = c.step(tools=[])
    assert msg.text == "fallback"
    assert msg.usage.input_tokens == 4
    assert msg.usage.ttft_seconds == 0.0
    assert msg.usage.generate_seconds == 0.0


def test_openai_reraises_unrelated_bad_request(monkeypatch):
    # A 400 that isn't about streaming (e.g. a bad tool schema) must surface,
    # not silently retry.
    called = {"create": False}

    def _raise(**kw):
        raise _bad_request("Invalid schema for tool 'edit'", param="tools")

    def _create(**kw):
        called["create"] = True
        return None

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from agent_eval.models.openai_client import _OpenAIClient

    c = _OpenAIClient(model_id="gpt-5.4")
    c.reset("system")
    c.add_user_text("hi")
    c.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(stream=_raise, create=_create))
    )
    with pytest.raises(BadRequestError):
        c.step(tools=[])
    assert called["create"] is False  # no fallback attempted


# --------------------------------------------------------------------------- #
# OpenRouter (OpenAI-API-compatible — same stream helper)                      #
# --------------------------------------------------------------------------- #
def test_openrouter_stream_splits_latency(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    from agent_eval.models.openrouter_client import _OpenRouterClient

    events = [SimpleNamespace(type="content.delta"), SimpleNamespace(type="content.done")]
    final = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=9, completion_tokens=3),
        model_dump=lambda: {"id": "z"},
    )
    c = _OpenRouterClient(model_id="anthropic/claude-opus-4-8")
    c.reset("system")
    c.add_user_text("hi")
    c.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(stream=lambda **kw: _FakeOAIStream(events, final))
        )
    )
    msg = c.step(tools=[])
    assert msg.text == "ok"
    assert msg.usage.input_tokens == 9
    assert msg.usage.ttft_seconds > 0.0
    assert msg.usage.generate_seconds > 0.0


# --------------------------------------------------------------------------- #
# Google                                                                       #
# --------------------------------------------------------------------------- #
def _text_part(text):
    return SimpleNamespace(function_call=None, text=text)


def _fc_part(name, args, call_id=None):
    return SimpleNamespace(
        function_call=SimpleNamespace(name=name, args=args, id=call_id), text=None
    )


def _chunk(parts, usage=None, model_version=None):
    content = SimpleNamespace(parts=parts) if parts is not None else None
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=content)],
        usage_metadata=usage,
        model_version=model_version,
    )


def _make_google(monkeypatch, chunks):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from agent_eval.models.google_client import _GoogleClient

    c = _GoogleClient(model_id="gemini-3.5-flash")
    c.reset("system")
    c.add_user_text("hi")

    def _stream(**kw):
        time.sleep(0.003)  # simulate prefill before the first chunk
        for ch in chunks:
            yield ch
            time.sleep(0.001)

    c.client = SimpleNamespace(
        models=SimpleNamespace(generate_content_stream=_stream)
    )
    return c


def test_google_stream_splits_latency_text(monkeypatch):
    usage = SimpleNamespace(
        prompt_token_count=20, candidates_token_count=6, cached_content_token_count=4
    )
    chunks = [
        _chunk([_text_part("hel")]),
        _chunk([_text_part("lo")], usage=usage, model_version="gemini-3.5-flash-001"),
    ]
    c = _make_google(monkeypatch, chunks)
    msg = c.step(tools=[])
    assert msg.text == "hello"  # fragments concatenated, not "\n"-joined
    assert msg.usage.input_tokens == 20
    assert msg.usage.output_tokens == 6
    assert msg.usage.cache_read_tokens == 4
    assert msg.usage.ttft_seconds > 0.0
    assert msg.usage.generate_seconds > 0.0
    # The assembled model turn is appended to history for the next step.
    assert c.history[-1].role == "model"


def test_google_stream_tool_call_and_history(monkeypatch):
    usage = SimpleNamespace(
        prompt_token_count=40, candidates_token_count=10, cached_content_token_count=0
    )
    chunks = [_chunk([_fc_part("edit", {"path": "b.py"})], usage=usage)]
    c = _make_google(monkeypatch, chunks)
    msg = c.step(tools=[{"name": "edit", "input_schema": {}}])
    assert [t.name for t in msg.tool_calls] == ["edit"]
    assert msg.tool_calls[0].arguments == {"path": "b.py"}
    # Synthesized call id is registered so add_tool_results can pair it.
    cid = msg.tool_calls[0].call_id
    assert c._call_name_by_id[cid] == "edit"
    assert msg.usage.ttft_seconds > 0.0


def test_google_empty_stream_zero_generate(monkeypatch):
    chunks = [_chunk(None)]  # no content parts at all
    c = _make_google(monkeypatch, chunks)
    msg = c.step(tools=[])
    assert msg.text == ""
    assert msg.tool_calls == []
    assert msg.usage.generate_seconds == 0.0
    assert msg.usage.ttft_seconds >= 0.0
