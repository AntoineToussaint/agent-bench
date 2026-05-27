"""SlidingWindow: drop turns older than N past the initial user message.

A turn here = one assistant message + the user message that follows it
(typically tool_results, sometimes free-text nudges). We always keep:

  - the initial user message (the task prompt)
  - the most recent N (assistant + following-user) turns

Everything in between is dropped wholesale.

This is the crudest pruning policy — strictly less faithful than
ToolResultElision, since we lose assistant reasoning text too. But it
caps context growth at a constant.

Cache impact
------------
Sliding window BREAKS the Anthropic prompt cache after enough turns:
the prefix changes when older turns drop off. That's the trade-off
between strict bounding and cache-friendliness. `StablePrefixDynamicTail`
in Tier 2 will be the cache-aware version.

Currently only implements the Anthropic message shape. OpenAI and Google
fall through to passthrough until we add them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import Provider


@dataclass
class SlidingWindow:
    n_turns: int = 5
    name: str = "sliding_window"

    def __post_init__(self) -> None:
        self.name = f"sliding_window(n_turns={self.n_turns})"

    def prepare(
        self,
        messages: list[dict[str, Any]],
        *,
        provider: Provider,
        turn_idx: int,
    ) -> list[dict[str, Any]]:
        if provider != "anthropic":
            return list(messages)
        if len(messages) <= 1:
            return list(messages)

        # First message is always the initial user message. Preserve it.
        initial = messages[0]
        tail = messages[1:]

        # A "turn" is an assistant message + the user message that follows
        # (if any). Walk backwards counting assistant messages.
        # Keep the most recent `n_turns` assistants and everything after
        # each one (tool_results or nudges).
        if not tail:
            return [initial]

        # Index of the n_turns-th assistant from the end.
        asst_count = 0
        keep_from = 0
        for i in range(len(tail) - 1, -1, -1):
            if tail[i].get("role") == "assistant":
                asst_count += 1
                if asst_count >= self.n_turns:
                    keep_from = i
                    break
        else:
            # Fewer than n_turns assistants — keep everything.
            keep_from = 0

        return [initial, *tail[keep_from:]]
