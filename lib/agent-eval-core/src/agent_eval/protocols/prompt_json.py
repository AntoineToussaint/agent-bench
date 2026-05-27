"""Prompt-based JSON backend (NO native tool API).

The model never sees the provider's tool_use API. Tools are described in
the system prompt; the model is expected to emit one fenced ```json``` block
per turn containing an `actions` list. The harness parses that block,
turns it into ToolCalls, and dispatches.

This is the WORST of the three backends — it relies on prompt instruction
alone to constrain output format. RL-trained models routinely revert to
their training prior (`<function_calls>` mimicry) instead of producing
the requested fenced JSON. We keep this backend for two reasons:

  1. It models what happens when a downstream user CANNOT use a tool_use
     API — a real, common scenario (open-weights models without function
     calling, edge inference, exotic providers).
  2. It surfaces the *cost* of format anchoring by counting mimicry
     attempts. Other backends hide that cost.

The mimicry detector is the load-bearing piece: when the model emits
`<function_calls>` tags instead of fenced JSON, we count them as invalid
attempts and surface a hint that the trial can use to nudge the model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from agent_eval.types import ModelClient, ToolCall, ToolResult

from .types import ActionResponse, ToolSpec


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)

# Provider-specific tool_use mimicry. We only match OPENING tags:
#   <function_calls> ...     — Anthropic's published tool-use format
#                              (model emits the tag outside the API channel,
#                              with hallucinated payload inside)
#   <invoke name="...">      — sub-tag inside the above
#
# Closing tags alone (`</function_calls>`) are NOT mimicry — we frequently
# observed models emitting `</function_calls>` as a vestigial artifact
# AFTER a real fenced ```json block. Counting those as mimicry would
# reject legitimate responses. The real signal of "this model is
# hallucinating tool calls" is the opener.
_MIMICRY_RE = re.compile(r"<function_calls>|<invoke\b", re.IGNORECASE)


def _count_mimicry(text: str) -> int:
    return len(_MIMICRY_RE.findall(text or ""))


def _extract_json_block(text: str) -> dict[str, Any] | str:
    """Return the last parseable JSON object from a fenced block.

    Returns the parsed dict on success, or an error string. We grab the
    LAST block because models that emit a thinking pass + a final answer
    often produce multiple `json blocks; the final one is the answer.
    """
    blocks = _JSON_BLOCK_RE.findall(text or "")
    candidates = list(reversed(blocks)) if blocks else [(text or "").strip()]
    last_err: str | None = None
    for candidate in candidates:
        if not candidate.strip():
            last_err = "empty JSON block"
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError as e:
            last_err = f"{e}"
            continue
        if not isinstance(obj, dict):
            last_err = f"expected JSON object, got {type(obj).__name__}"
            continue
        return obj
    return last_err or "no JSON found in response"


def _render_op_descriptions(tools: list[ToolSpec]) -> str:
    """Render a tool list as a markdown block for the system prompt.

    Mirrors the per-tool format used elsewhere in the repo — name + desc +
    arg list with required flags. The structure must be readable enough
    that the model can call the right tool with the right args from
    prompt alone.
    """
    parts: list[str] = []
    for t in tools:
        props = t.input_schema.get("properties", {})
        required = set(t.input_schema.get("required") or [])
        arg_lines: list[str] = []
        for arg_name, arg_schema in props.items():
            req = " (required)" if arg_name in required else ""
            arg_type = arg_schema.get("type", "")
            arg_desc = arg_schema.get("description", "")
            head = f"    - {arg_name}: {arg_type}{req}"
            arg_lines.append(f"{head} — {arg_desc}" if arg_desc else head)
        args_block = "\n".join(arg_lines) if arg_lines else "    (no args)"
        parts.append(f"### `{t.name}`\n{t.description}\n\n  args:\n{args_block}")
    return "\n\n".join(parts)


_PROTOCOL_PREAMBLE = """\
## Protocol

On every turn you MUST respond with exactly ONE fenced JSON block — \
nothing else outside it. The block takes one of two shapes.

### To explore

```json
{
  "thought": "<one or two sentences of reasoning>",
  "actions": [
    {"op": "<op-name>", "args": {<args>}}
  ]
}
```

You may batch multiple actions in one turn — they are applied in order \
and the results come back together in the next user message.

### To finish

```json
{
  "thought": "<brief reasoning>",
  "done": true,
  "files": ["<ranked path>", "..."]
}
```

After a `done` turn the loop exits — you cannot edit or retract.

DO NOT emit `<function_calls>` or `<invoke>` tags — this protocol uses \
fenced JSON blocks only. If you produce those tags they will be rejected \
and you will lose a turn.\
"""


@dataclass
class PromptJSONBackend:
    name: str = "prompt_json"

    def system_prompt_addendum(self, tools: list[ToolSpec]) -> str:
        ops = _render_op_descriptions(tools)
        return f"{_PROTOCOL_PREAMBLE}\n\n## Ops\n\n{ops}"

    def request(
        self,
        client: ModelClient,
        tools: list[ToolSpec],
    ) -> ActionResponse:
        # No tools passed — this backend communicates structure via prompt.
        msg = client.step([])
        text = msg.text or ""
        mimicry_count = _count_mimicry(text)
        parsed = _extract_json_block(text)

        # Reject the WHOLE response if mimicry is present. A trailing
        # valid JSON block doesn't redeem it — that block's reasoning is
        # built on tool calls the harness never executed.
        if mimicry_count > 0:
            return ActionResponse(
                actions=[],
                raw_text=text,
                invalid_attempts=mimicry_count,
                usage=msg.usage,
                backend_name=self.name,
                error=f"mimicry: {mimicry_count} <function_calls> tag(s) detected",
                hints=[
                    "You used `<function_calls>` / `<invoke>` tags. This "
                    "protocol does NOT use those — emit one fenced JSON "
                    "block per turn with an `actions` array."
                ],
            )

        if isinstance(parsed, str):
            return ActionResponse(
                actions=[],
                raw_text=text,
                invalid_attempts=1,
                usage=msg.usage,
                backend_name=self.name,
                error=f"json parse error: {parsed}",
            )

        # Two accepted shapes:
        #
        #   A) {"actions": [{"op": ..., "args": ...}]}   — exploration shape
        #   B) {"done": true, "files": [...]}             — terminal shape
        #
        # (B) exists because models naturally produce it: "we're done,
        # here's the answer" reads better as a top-level done than as
        # a one-element actions list with op="done". We synthesize the
        # equivalent ToolCall under the hood so the harness has one path.

        calls: list[ToolCall] = []
        invalid = 0

        if parsed.get("done") is True:
            files = parsed.get("files") or []
            if not isinstance(files, list):
                return ActionResponse(
                    actions=[],
                    raw_text=text,
                    invalid_attempts=1,
                    usage=msg.usage,
                    backend_name=self.name,
                    error="`files` must be a list of strings",
                )
            calls.append(
                ToolCall(
                    name="done",
                    arguments={"files": [str(f) for f in files]},
                    call_id="pj_done",
                )
            )
            return ActionResponse(
                actions=calls,
                raw_text=text,
                invalid_attempts=0,
                usage=msg.usage,
                backend_name=self.name,
            )

        actions = parsed.get("actions")
        if actions is None:
            return ActionResponse(
                actions=[],
                raw_text=text,
                invalid_attempts=1,
                usage=msg.usage,
                backend_name=self.name,
                error=(
                    "response must contain either `actions` (list) or "
                    "`done: true` with `files` (list)"
                ),
            )
        if not isinstance(actions, list):
            return ActionResponse(
                actions=[],
                raw_text=text,
                invalid_attempts=1,
                usage=msg.usage,
                backend_name=self.name,
                error=f"`actions` must be a list, got {type(actions).__name__}",
            )
        if not actions:
            return ActionResponse(
                actions=[],
                raw_text=text,
                invalid_attempts=1,
                usage=msg.usage,
                backend_name=self.name,
                error="empty `actions` list — either request data or submit `done`",
            )

        for i, a in enumerate(actions):
            if not isinstance(a, dict):
                invalid += 1
                continue
            op = a.get("op")
            args = a.get("args", {}) or {}
            if not isinstance(op, str) or not isinstance(args, dict):
                invalid += 1
                continue
            calls.append(ToolCall(name=op, arguments=args, call_id=f"pj{i:03d}"))

        return ActionResponse(
            actions=calls,
            raw_text=text,
            invalid_attempts=invalid,
            usage=msg.usage,
            backend_name=self.name,
        )

    def send_results(
        self,
        client: ModelClient,
        calls: list[ToolCall],
        results: list[ToolResult],
    ) -> None:
        client.add_user_text(self.render_results_text(calls, results))

    def send_hint(self, client: ModelClient, hint: str) -> None:
        body = json.dumps({"error": hint, "actions_applied": []}, indent=2)
        client.add_user_text(f"```json\n{body}\n```")

    def render_results_text(
        self,
        calls: list[ToolCall],
        results: list[ToolResult],
    ) -> str:
        body = {
            "results": [
                {
                    "op": c.name,
                    "call_id": r.call_id,
                    "status": r.status,
                    "content": r.content,
                }
                for c, r in zip(calls, results)
            ]
        }
        return "```json\n" + json.dumps(body, indent=2) + "\n```"

    def request_terminal(
        self,
        client: ModelClient,
        tools: list[ToolSpec],
        terminal_tool: str,
    ) -> ActionResponse:
        # PromptJSON has no tool_choice analog. Best we can do is nudge
        # the model textually before asking again. The trial loop sends
        # the nudge via send_hint() before this call.
        return self.request(client, tools)
