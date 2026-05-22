"""Turn-loop trial for file localization — STRUCTURED protocol.

Same multi-turn shape as `turn_loop_trial.py`, but the protocol is pure
text-in / text-out structured by a JSON contract. The model never sees
or emits provider-native `tool_use` blocks.

Each turn:
  - The model receives the conversation so far + the most recent results
    rendered as a JSON block.
  - The model responds with a single fenced ```json``` block of the form

      {
        "thought": "...",
        "actions": [
          {"op": "list_files", "args": {"path": "src/"}},
          {"op": "grep",       "args": {"pattern": "compute_total"}},
          {"op": "view_file",  "args": {"path": "src/foo.py"}}
        ]
      }

    …or, to finish:

      {
        "thought": "...",
        "done": true,
        "files": ["src/foo.py", "tests/test_foo.py"]
      }

  - The harness parses, applies each action via `_apply` (reused from
    the tool_use variant), and replies with a JSON results block.

If the model returns text we can't parse, we surface a structured error
in the next user turn so it can self-correct.

Trial signature matches `agent_eval.Sweep`:
    (ModelClient, condition, LocalizationTask) -> RunRecord
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from agent_eval.pricing import cost_usd
from agent_eval.types import (
    AssistantMessage,
    ModelClient,
    RunRecord,
    ToolCall,
    ToolResult,
    Transcript,
    TurnUsage,
)

from file_localization.contract import LocalizationTask, score
from file_localization.turn_loop_trial import (
    LocalRepoView,  # re-exported for convenience
    RepoView,
    _Limits,
    _apply,
    _snapshot,
)


__all__ = [
    "LocalRepoView",
    "RepoView",
    "_Limits",
    "SYSTEM_PROMPT",
    "USER_TEMPLATE",
    "make_structured_turn_loop_trial",
]


# ============ prompts ============


SYSTEM_PROMPT = """\
You investigate a code repository to identify the files that must be edited \
(and the tests that must be added or updated) to fix a given GitHub issue.

## Protocol

You and the harness communicate via JSON. On every turn you MUST respond \
with exactly ONE fenced JSON block — nothing else outside it. The block \
takes one of two shapes.

### To explore the repo

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

## Ops

  - `list_files` — args: `{"path": "<subpath>"}` (optional; defaults to repo root)
      Returns every file under `path`, one per line. Excludes `.git`, \
`__pycache__`, `node_modules`, `.venv`.

  - `grep` — args: `{"pattern": "<regex>", "glob": "<optional path glob>", "limit": <int>}`
      Searches file contents with a Python regex. Returns `path:line: snippet` \
for each hit (up to `limit`, default 50).

  - `view_file` — args: `{"path": "<file>", "line_range": [start, end]}`
      Reads a file. `line_range` (1-indexed, inclusive) is optional.

  - `done` — handled via the `done`/`files` form above. Do NOT put a \
`{"op": "done"}` action in the `actions` list — use the dedicated `done` \
shape with `"done": true` and `"files": [...]`.

## Results

The user reply on the next turn is a JSON block with one entry per action \
you submitted, in the same order:

```json
{
  "results": [
    {"op": "list_files", "status": "ok",    "content": "..."},
    {"op": "grep",       "status": "error", "content": "bad regex ..."}
  ]
}
```

If you emit malformed JSON, the harness replies with \
`{"error": "...", "actions_applied": []}` and you should self-correct on \
the next turn.

## Strategy

Work like an engineer: skim the repo structure, grep for relevant symbols, \
read the most promising files, then submit `done` with a ranked list \
(highest relevance first). Include both source files (where the bug lives) \
and test files (where regression tests would go).

Be selective — only include files that genuinely matter. Spurious files \
hurt your score.\
"""


USER_TEMPLATE = """\
## Repository
{repo} @ {commit}

## Issue
{issue}

Start by exploring the repo. When you've identified the files, respond with \
the `done` form to submit the ranked list.\
"""


# ============ parsing ============


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)


def _extract_json_block(text: str) -> dict[str, Any] | str:
    """Extract the last parseable JSON object from a model response.

    Returns the parsed dict on success, or an error string describing why
    parsing failed. Modeled after code-editing's `_extract_json_changeset`:
    on multiple ```json blocks (self-correction), the LAST one wins.
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
    if last_err is None:
        return "no JSON found in response"
    return last_err


# ============ helpers ============


def _next_call_id(counter: list[int]) -> str:
    counter[0] += 1
    return f"sc{counter[0]:04d}"


def _action_to_tool_call(action: Any, counter: list[int]) -> ToolCall | str:
    """Convert one parsed action dict into a ToolCall, or return an error string."""
    if not isinstance(action, dict):
        return f"action must be an object, got {type(action).__name__}"
    op = action.get("op")
    if not isinstance(op, str) or not op:
        return "action missing string `op`"
    args = action.get("args", {}) or {}
    if not isinstance(args, dict):
        return f"action `args` must be an object, got {type(args).__name__}"
    return ToolCall(name=op, arguments=args, call_id=_next_call_id(counter))


def _render_results_block(pairs: list[tuple[str, ToolResult]]) -> str:
    """Render a list of (op_name, ToolResult) into a JSON results block."""
    obj = {
        "results": [
            {"op": op, "status": r.status, "content": r.content}
            for op, r in pairs
        ]
    }
    return "```json\n" + json.dumps(obj, indent=2) + "\n```"


def _render_error_block(message: str) -> str:
    obj = {"error": message, "actions_applied": []}
    return "```json\n" + json.dumps(obj, indent=2) + "\n```"


# ============ trial ============


def make_structured_turn_loop_trial(
    repo_view_for: Callable[[LocalizationTask], RepoView],
    *,
    limits: _Limits | None = None,
    fp_penalty: float = 0.05,
    top_k: int | None = None,
):
    """Factory: returns a Trial that uses a structured-JSON agent loop.

    Same shape as `make_turn_loop_trial`, but the protocol is text-only —
    no provider `tool_use` API is used. The model emits JSON; the harness
    parses it and replies with a JSON results block.

    Args:
        repo_view_for: resolves a LocalizationTask to a RepoView.
        limits: turn / error / no-progress caps. Defaults are conservative.
        fp_penalty: scorer's false-positive penalty.
        top_k: if set, only the top-k files in the final answer are scored.
    """
    limits = limits or _Limits()

    def trial(client: ModelClient, condition: str, task: LocalizationTask) -> RunRecord:
        repo = repo_view_for(task)
        transcript = Transcript(system=SYSTEM_PROMPT)
        client.reset(SYSTEM_PROMPT)
        user_text = USER_TEMPLATE.format(
            repo=task.repo,
            commit=task.base_commit[:12] if task.base_commit else "unknown",
            issue=task.issue_text,
        )
        client.add_user_text(user_text)
        transcript.add_user_text(user_text)

        submitted: list[str] = []
        turns = 0
        tool_calls = 0
        invalid = 0
        consecutive_errors = 0
        no_progress_turns = 0
        last_snapshot: tuple[str, ...] | None = None
        error: str | None = None
        done_flag = False
        call_id_counter = [0]

        t0 = time.monotonic()
        in_tok = out_tok = cache_r = cache_w = 0

        while turns < limits.max_turns and not done_flag:
            turns += 1
            try:
                msg: AssistantMessage = client.step(tools=[])
            except Exception as e:  # noqa: BLE001
                error = f"model_error: {type(e).__name__}: {e}"
                break
            transcript.add_assistant(msg)
            in_tok += msg.usage.input_tokens
            out_tok += msg.usage.output_tokens
            cache_r += msg.usage.cache_read_tokens
            cache_w += msg.usage.cache_creation_tokens

            parsed = _extract_json_block(msg.text)
            if isinstance(parsed, str):
                # JSON parse failure: count as an invalid call and surface
                # a structured error so the model can recover.
                tool_calls += 1
                invalid += 1
                err_text = _render_error_block(f"json parse error: {parsed}")
                client.add_user_text(err_text)
                transcript.add_user_text(err_text)
                consecutive_errors += 1
                if consecutive_errors >= limits.max_consecutive_errors:
                    error = f"aborted: {consecutive_errors} consecutive error turns"
                    break
                # parse error → no progress towards an answer either
                snap = _snapshot(submitted)
                if snap == last_snapshot:
                    no_progress_turns += 1
                else:
                    no_progress_turns = 0
                last_snapshot = snap
                if not done_flag and no_progress_turns >= limits.max_no_progress_turns:
                    error = f"aborted: {no_progress_turns} no-progress turns"
                    break
                continue

            # Handle the `done` shape.
            if parsed.get("done") is True:
                tool_calls += 1
                files = parsed.get("files") or []
                if not isinstance(files, list):
                    invalid += 1
                    err_text = _render_error_block(
                        "`files` must be a list of strings"
                    )
                    client.add_user_text(err_text)
                    transcript.add_user_text(err_text)
                    consecutive_errors += 1
                    if consecutive_errors >= limits.max_consecutive_errors:
                        error = (
                            f"aborted: {consecutive_errors} consecutive error turns"
                        )
                        break
                    continue
                submitted = [str(f) for f in files]
                done_flag = True
                # Mirror the tool_use variant: don't bother sending a result
                # back since the loop exits.
                ack = ToolResult(
                    call_id=_next_call_id(call_id_counter),
                    status="ok",
                    content=f"accepted {len(submitted)} file(s)",
                )
                transcript.add_tool_results([ack])
                break

            # Otherwise: extract the actions list.
            actions = parsed.get("actions")
            if actions is None:
                # Nudge: neither `actions` nor `done`.
                tool_calls += 1
                invalid += 1
                err_text = _render_error_block(
                    "response must contain either `actions` (list) or "
                    "`done: true` with `files` (list)"
                )
                client.add_user_text(err_text)
                transcript.add_user_text(err_text)
                consecutive_errors += 1
                if consecutive_errors >= limits.max_consecutive_errors:
                    error = (
                        f"aborted: {consecutive_errors} consecutive error turns"
                    )
                    break
                continue

            if not isinstance(actions, list):
                tool_calls += 1
                invalid += 1
                err_text = _render_error_block(
                    f"`actions` must be a list, got {type(actions).__name__}"
                )
                client.add_user_text(err_text)
                transcript.add_user_text(err_text)
                consecutive_errors += 1
                if consecutive_errors >= limits.max_consecutive_errors:
                    error = (
                        f"aborted: {consecutive_errors} consecutive error turns"
                    )
                    break
                continue

            if not actions:
                # Empty actions list: treat as a nudge, not a hard error.
                tool_calls += 1
                invalid += 1
                err_text = _render_error_block(
                    "empty `actions` list — either request data or submit `done`"
                )
                client.add_user_text(err_text)
                transcript.add_user_text(err_text)
                consecutive_errors += 1
                if consecutive_errors >= limits.max_consecutive_errors:
                    error = (
                        f"aborted: {consecutive_errors} consecutive error turns"
                    )
                    break
                snap = _snapshot(submitted)
                if snap == last_snapshot:
                    no_progress_turns += 1
                else:
                    no_progress_turns = 0
                last_snapshot = snap
                if not done_flag and no_progress_turns >= limits.max_no_progress_turns:
                    error = f"aborted: {no_progress_turns} no-progress turns"
                    break
                continue

            # Apply every action in the list and collect results.
            results: list[ToolResult] = []
            result_pairs: list[tuple[str, ToolResult]] = []
            turn_all_errors = True
            inline_done = False

            for action in actions:
                tool_calls += 1
                tc_or_err = _action_to_tool_call(action, call_id_counter)
                if isinstance(tc_or_err, str):
                    invalid += 1
                    op_label = (
                        action.get("op")
                        if isinstance(action, dict) and isinstance(action.get("op"), str)
                        else "<invalid>"
                    )
                    res = ToolResult(
                        call_id=_next_call_id(call_id_counter),
                        status="error",
                        content=tc_or_err,
                    )
                    results.append(res)
                    result_pairs.append((op_label, res))
                    continue

                # Defensive: an action with op="done" inside the actions
                # list isn't the documented shape, but if the model does
                # it anyway, treat it like the top-level done.
                if tc_or_err.name == "done":
                    files = tc_or_err.arguments.get("files") or []
                    if isinstance(files, list):
                        submitted = [str(f) for f in files]
                    inline_done = True
                    ok = ToolResult(
                        call_id=tc_or_err.call_id,
                        status="ok",
                        content=f"accepted {len(submitted)} file(s)",
                    )
                    results.append(ok)
                    result_pairs.append((tc_or_err.name, ok))
                    turn_all_errors = False
                    break  # ignore any further actions after done

                res = _apply(tc_or_err, repo)
                if res.status == "ok":
                    turn_all_errors = False
                else:
                    invalid += 1
                results.append(res)
                result_pairs.append((tc_or_err.name, res))

            transcript.add_tool_results(results)

            if inline_done:
                done_flag = True
                break

            # Send results back as a structured JSON user message.
            results_text = _render_results_block(result_pairs)
            client.add_user_text(results_text)
            transcript.add_user_text(results_text)

            # escape valves
            if turn_all_errors:
                consecutive_errors += 1
            else:
                consecutive_errors = 0
            if consecutive_errors >= limits.max_consecutive_errors:
                error = f"aborted: {consecutive_errors} consecutive error turns"
                break

            snap = _snapshot(submitted)
            if snap == last_snapshot:
                no_progress_turns += 1
            else:
                no_progress_turns = 0
            last_snapshot = snap
            if not done_flag and no_progress_turns >= limits.max_no_progress_turns:
                error = f"aborted: {no_progress_turns} no-progress turns"
                break

        latency = time.monotonic() - t0
        s = score(submitted, task.gold_all, k=top_k, fp_penalty=fp_penalty)

        usage = TurnUsage(
            input_tokens=in_tok,
            output_tokens=out_tok,
            cache_read_tokens=cache_r,
            cache_creation_tokens=cache_w,
        )
        return RunRecord(
            task_id=task.task_id,
            model=client.name,
            condition=condition,
            passed=s.passed,
            turns=turns,
            tool_calls=tool_calls,
            invalid_tool_calls=invalid,
            usage=usage,
            latency_seconds=latency,
            cost_usd=cost_usd(client.name, usage),
            error=error,
            extra={
                **s.as_extra(),
                "submitted": submitted,
                "done_called": done_flag,
            },
        )

    return trial
