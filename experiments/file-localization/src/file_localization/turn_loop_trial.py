"""Turn-loop trial for file localization (tool_use protocol).

The model explores a repo via tools and submits a ranked file list.
Trial signature matches `agent_eval.Sweep`:
    (ModelClient, condition, LocalizationTask) -> RunRecord

Tools are defined ONCE in `file_localization.tools` (TOOL_SCHEMAS +
apply_tool_call) and shared with the structured-loop variant. The
RepoView abstraction lives in `file_localization.repo_view`.

The loop itself (this module) just owns: escape valves, message
sequencing, scoring, transcript dumping.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent_eval.pricing import cost_usd
from agent_eval.types import (
    AssistantMessage,
    ModelClient,
    RunRecord,
    ToolCall,
    ToolResult,
    Transcript,
)

from file_localization.contract import LocalizationTask, score
from file_localization.repo_view import LocalRepoView, RepoView  # re-exported for compat
from file_localization.tools import TOOL_SCHEMAS, apply_tool_call

# Re-exports so existing `from turn_loop_trial import LocalRepoView, ...`
# imports continue to work after the extraction.
__all__ = [
    "LocalRepoView",
    "RepoView",
    "TOOL_SCHEMAS",
    "apply_tool_call",
    "make_turn_loop_trial",
    "_Limits",
]

# Legacy aliases — referenced by the structured-loop module and tests.
TOOLS = TOOL_SCHEMAS
_apply = apply_tool_call


# ============ loop-local prompts ============


SYSTEM_PROMPT = """\
Your job is LOCALIZATION ONLY: identify which files need editing for a given \
issue. You are NOT writing the fix or analyzing root causes in detail.

Tools:
  - list_files(path?)         → list paths
  - grep(pattern, glob?)      → search file contents
  - view_file(path, range?)   → read file (or a slice)
  - done(files=[...])         → submit final ranked list and exit

Workflow:
  1. Skim the repo top-level structure (one `list_files`).
  2. Grep for symbols / phrases mentioned in the issue.
  3. View the most-likely candidate file(s) to confirm.
  4. Call `done` with a SHORT ranked list (most relevant first).

Budget: target 3-6 tool calls TOTAL before calling `done`. Each extra \
exploration call costs you tokens with diminishing return — once you have \
3-5 plausible files, SUBMIT. You can be wrong; you cannot retract.

Include source files (where the fix would go) AND test files (where a \
regression test would land). Be selective: spurious files hurt your score \
via the false-positive penalty.\
"""


USER_TEMPLATE = """\
## Repository
{repo} @ {commit}

## Issue
{issue}

Start by exploring the repo. When you've identified the files, call `done` \
with the ranked list.\
"""


# ============ trial loop ============


@dataclass
class _Limits:
    max_turns: int = 15
    max_consecutive_errors: int = 3
    max_no_progress_turns: int = 4


def _snapshot(submitted: list[str]) -> tuple[str, ...]:
    """Legacy snapshot — kept for structured-loop reuse. Returns the
    current submitted file list as a hashable tuple."""
    return tuple(submitted)


def _signature(call: ToolCall) -> tuple[str, str]:
    """Stable hashable key for one tool call: (name, json-args).

    Used to detect "no progress" — a turn that emits only signatures the
    model has already used is wasted. In a turn-loop, exploration IS the
    work, so we measure progress by "did the model try anything new",
    not by "did the submitted answer change."
    """
    import json as _json

    try:
        args = _json.dumps(call.arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        args = str(call.arguments)
    return (call.name, args)


def make_turn_loop_trial(
    repo_view_for: Callable[[LocalizationTask], RepoView],
    *,
    limits: _Limits | None = None,
    fp_penalty: float = 0.05,
    top_k: int | None = None,
    transcripts_dir: "Path | None" = None,
):
    """Factory: returns a Trial that uses an agent loop against `repo_view_for(task)`.

    Args:
        repo_view_for: callable that resolves a LocalizationTask to a RepoView.
            For SWE-Bench tasks this clones the repo at base_commit; for tests
            it can return a LocalRepoView over a tmp_path.
        limits: turn / error / no-progress caps. Defaults are conservative.
        fp_penalty: scorer's false-positive penalty.
        top_k: if set, only the top-k files in the final `done(files=...)` are scored.
        transcripts_dir: optional directory to dump per-trial JSON transcripts.
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
        seen_signatures: set[tuple[str, str]] = set()
        turns = 0
        tool_calls = 0
        invalid = 0
        consecutive_errors = 0
        no_progress_turns = 0
        error: str | None = None
        done_flag = False

        t0 = time.monotonic()
        in_tok = out_tok = cache_r = cache_w = 0

        while turns < limits.max_turns and not done_flag:
            turns += 1
            try:
                msg: AssistantMessage = client.step(TOOLS)
            except Exception as e:  # noqa: BLE001
                error = f"model_error: {type(e).__name__}: {e}"
                break
            transcript.add_assistant(msg)
            in_tok += msg.usage.input_tokens
            out_tok += msg.usage.output_tokens
            cache_r += msg.usage.cache_read_tokens
            cache_w += msg.usage.cache_creation_tokens

            if not msg.tool_calls:
                client.add_user_text(
                    "You did not call any tools. Use `list_files`, `grep`, or "
                    "`view_file` to explore, then call `done(files=[...])` when ready."
                )
                transcript.add_user_text("(nudge: no tool calls)")
                continue

            results: list[ToolResult] = []
            turn_all_errors = True
            turn_added_signature = False
            for tc in msg.tool_calls:
                tool_calls += 1
                # Track exploration "progress" by unique (name, args) signature.
                sig = _signature(tc)
                if sig not in seen_signatures:
                    seen_signatures.add(sig)
                    turn_added_signature = True
                res = _apply(tc, repo)
                if res.status == "ok":
                    turn_all_errors = False
                else:
                    invalid += 1
                results.append(res)
                if tc.name == "done":
                    files = tc.arguments.get("files") or []
                    if isinstance(files, list):
                        submitted = [str(f) for f in files]
                    done_flag = True
            client.add_tool_results(results)
            transcript.add_tool_results(results)

            # escape valves
            if turn_all_errors:
                consecutive_errors += 1
            else:
                consecutive_errors = 0
            if consecutive_errors >= limits.max_consecutive_errors:
                error = f"aborted: {consecutive_errors} consecutive error turns"
                break

            # No-progress: a turn that emitted ONLY signatures already seen
            # (i.e. nothing the model hasn't tried before).
            if not done_flag and not turn_added_signature:
                no_progress_turns += 1
            else:
                no_progress_turns = 0
            if not done_flag and no_progress_turns >= limits.max_no_progress_turns:
                error = (
                    f"aborted: {no_progress_turns} turns without trying a new "
                    f"(tool, args) signature"
                )
                break

        latency = time.monotonic() - t0
        s = score(submitted, task.gold_all, k=top_k, fp_penalty=fp_penalty)

        from agent_eval.types import TurnUsage as _TU

        usage = _TU(
            input_tokens=in_tok,
            output_tokens=out_tok,
            cache_read_tokens=cache_r,
            cache_creation_tokens=cache_w,
        )
        rec = RunRecord(
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
                "unique_signatures": len(seen_signatures),
            },
        )
        if transcripts_dir:
            from agent_eval import dump_transcript as _dump

            rec.transcript_path = str(_dump(transcripts_dir, rec, transcript))
        return rec

    return trial
