"""ContextPolicy Protocol — the interface every policy implements.

The policy is called by the trial loop *before* each `client.step()`.
It receives the client's current message history and returns a new
history (the policy decides what to keep, drop, elide, or replace).

Provider awareness
------------------
Anthropic / OpenAI / Google use slightly different message shapes
internally. The Protocol is provider-agnostic by passing a `provider`
hint; individual policies dispatch on it. For Tier 1 we only fully
support the Anthropic shape (the only provider exercised by the
turn-loop trials today). OpenAI and Google fall through to a passthrough
no-op so the policy is safe to use everywhere, just not yet effective
on those providers.

Why not a fully abstract Message type?
- Translating provider-native ↔ generic on every turn doubles the
  serialization surface and bugs.
- The differences matter (tool_result formatting) and the policies need
  to know them anyway. Provider-aware policies are honest about that.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol


Provider = Literal["anthropic", "openai", "google", "unknown"]


class ContextPolicy(Protocol):
    """How to shape the conversation history before each model call.

    Implementations return a new message list — they do NOT mutate the
    client's history in place. The trial loop replaces the client's
    history with the returned value.
    """

    name: str

    def prepare(
        self,
        messages: list[dict[str, Any]],
        *,
        provider: Provider,
        turn_idx: int,
    ) -> list[dict[str, Any]]:
        """Return the message list to send on this turn.

        Args:
            messages: the client's current history (provider-native shape).
            provider: which provider's shape to assume.
            turn_idx: 1-based turn counter — lets policies activate after
                a warm-up (e.g. only start eliding after turn 5).
        """
        ...
