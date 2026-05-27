"""ToolResultElision: keep recent tool_results, elide older ones.

Production agents (Claude Code, Codex CLI) do a version of this — once
the conversation has many tool_results, the older ones are usually
no-longer-needed exploration context, while the assistant text
explaining what was done is preserved.

Specifically: this policy keeps every assistant message intact (text +
tool_use blocks) and keeps the N most recent tool_result messages
verbatim. Older tool_result blocks have their content replaced with a
short placeholder like `[elided: 1247 chars]`. The `tool_use_id` is
preserved so the corresponding tool_use block still has its partner.

Why keep tool_use_ids but elide content
---------------------------------------
Anthropic's API requires every tool_use block to be followed by a
matching tool_result with the same `tool_use_id`. Dropping a tool_result
entirely breaks the contract. Elision keeps the contract but compresses
the payload.

Cache-friendliness
------------------
Elision happens in the *tail* of the conversation, not the head. The
system prompt + initial user message + early tool_results stay
byte-identical, so the Anthropic prompt cache prefix isn't broken —
until enough turns pass that the elision window starts hitting the
prefix. For typical 10-15 turn trials with keep_recent=2-3, the head
stays cached.

Currently only implements the Anthropic message shape. OpenAI and
Google fall through to passthrough (no-op) until we add them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import Provider


_ELIDED_TEMPLATE = "[elided: {n} chars from tool_result]"


@dataclass
class ToolResultElision:
    keep_recent: int = 2
    name: str = "tool_result_elision"

    def __post_init__(self) -> None:
        # Embed N in the policy id so a sweep can compare different
        # keep_recent values without recomputing names.
        self.name = f"tool_result_elision(keep_recent={self.keep_recent})"

    def prepare(
        self,
        messages: list[dict[str, Any]],
        *,
        provider: Provider,
        turn_idx: int,
    ) -> list[dict[str, Any]]:
        if provider != "anthropic":
            # TODO Tier 2: handle openai/google. For now no-op so the
            # policy is safe to bundle on any handle.
            return list(messages)

        # First pass: find indices of tool_result-bearing messages
        # (Anthropic shape: role=user with content[0].type == "tool_result").
        tool_result_indices: list[int] = []
        for i, m in enumerate(messages):
            content = m.get("content")
            if not isinstance(content, list) or not content:
                continue
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "tool_result":
                tool_result_indices.append(i)

        # Keep the last `keep_recent` tool_result messages intact; elide
        # all earlier ones.
        if len(tool_result_indices) <= self.keep_recent:
            return list(messages)
        elide_until = tool_result_indices[-self.keep_recent]  # first index to KEEP

        out: list[dict[str, Any]] = []
        for i, m in enumerate(messages):
            if i in tool_result_indices and i < elide_until:
                out.append(_elide_tool_result_message(m))
            else:
                out.append(m)
        return out


def _elide_tool_result_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Replace every tool_result's content with a short placeholder."""
    new_content: list[dict[str, Any]] = []
    for block in msg.get("content", []):
        if isinstance(block, dict) and block.get("type") == "tool_result":
            original = block.get("content")
            n_chars = len(original) if isinstance(original, str) else 0
            new_content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.get("tool_use_id"),
                    "content": _ELIDED_TEMPLATE.format(n=n_chars),
                    "is_error": block.get("is_error", False),
                }
            )
        else:
            new_content.append(block)
    return {**msg, "content": new_content}
