"""Unit tests for the context-engineering policies."""

from __future__ import annotations

from agent_eval.context import KeepEverything, SlidingWindow, ToolResultElision


def _anthropic_history(n_tool_use_rounds: int) -> list[dict]:
    """Build a synthetic Anthropic-shape conversation with N tool_use rounds.

    Shape: [initial_user, (assistant_tool_use, user_tool_result) x N].
    Each tool_result is a long string so elision is observable.
    """
    msgs: list[dict] = [{"role": "user", "content": "the task"}]
    for i in range(n_tool_use_rounds):
        tool_use_id = f"u{i}"
        msgs.append(
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": tool_use_id, "name": "grep", "input": {}}],
            }
        )
        msgs.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": "X" * 500,
                    }
                ],
            }
        )
    return msgs


def test_keep_everything_is_noop() -> None:
    msgs = _anthropic_history(3)
    p = KeepEverything()
    out = p.prepare(msgs, provider="anthropic", turn_idx=4)
    assert out == msgs
    assert p.name == "keep_everything"


def test_tool_result_elision_keeps_recent_n() -> None:
    msgs = _anthropic_history(5)
    p = ToolResultElision(keep_recent=2)
    out = p.prepare(msgs, provider="anthropic", turn_idx=6)

    # Should still have the same number of messages — we elide content,
    # not drop messages (Anthropic requires tool_use ↔ tool_result pairs).
    assert len(out) == len(msgs)

    # Walk the tool_result-bearing messages in order; the first 3 should
    # be elided (short placeholder), the last 2 kept verbatim.
    tool_result_msgs = [
        m for m in out
        if isinstance(m["content"], list)
        and m["content"]
        and m["content"][0].get("type") == "tool_result"
    ]
    assert len(tool_result_msgs) == 5

    elided_lengths = [
        len(m["content"][0]["content"]) for m in tool_result_msgs[:3]
    ]
    kept_lengths = [
        len(m["content"][0]["content"]) for m in tool_result_msgs[3:]
    ]
    assert all(n < 100 for n in elided_lengths), f"elided: {elided_lengths}"
    assert all(n == 500 for n in kept_lengths), f"kept: {kept_lengths}"

    # tool_use_id preserved on elided entries (required by Anthropic API).
    assert all(
        m["content"][0].get("tool_use_id") for m in tool_result_msgs
    )


def test_tool_result_elision_under_threshold_is_noop() -> None:
    # 2 tool_results, keep_recent=3 → nothing to elide.
    msgs = _anthropic_history(2)
    p = ToolResultElision(keep_recent=3)
    out = p.prepare(msgs, provider="anthropic", turn_idx=3)
    assert out == msgs


def test_sliding_window_keeps_initial_user_plus_n_turns() -> None:
    msgs = _anthropic_history(5)  # initial_user + 5 (assistant + tool_result) = 11
    p = SlidingWindow(n_turns=2)
    out = p.prepare(msgs, provider="anthropic", turn_idx=6)

    # Expect: initial_user + last 2 (assistant + tool_result) = 5 messages.
    assert len(out) == 5
    assert out[0] == msgs[0]  # initial user preserved
    # Last 4 messages match the input's last 4
    assert out[1:] == msgs[-4:]


def test_sliding_window_below_threshold_is_noop() -> None:
    # 2 rounds, window of 5 → keep everything.
    msgs = _anthropic_history(2)
    p = SlidingWindow(n_turns=5)
    out = p.prepare(msgs, provider="anthropic", turn_idx=3)
    assert out == msgs


def test_non_anthropic_provider_passthrough() -> None:
    # Tier-1 policies are Anthropic-aware only; other providers no-op.
    msgs = _anthropic_history(5)
    for p in (ToolResultElision(keep_recent=1), SlidingWindow(n_turns=1)):
        for provider in ("openai", "google", "unknown"):
            out = p.prepare(msgs, provider=provider, turn_idx=6)  # type: ignore[arg-type]
            assert out == msgs, f"{p.name} on {provider} should be no-op"
