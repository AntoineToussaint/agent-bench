"""LLM-based localization trial: the protocol the user described.

> Take this GitHub issue and find all the files that are needed for a proper
> investigation of that bug. Respond by writing FILE: <path> lines.

The model receives the issue + a candidate file list and replies with a
ranked list of FILE: lines, one per file. The trial parses the response
and scores it against the gold patch via `contract.score`.

Plugs into `agent_eval.Sweep` via the standard Trial signature:
    (ModelClient, condition: str, LocalizationTask) -> RunRecord
"""

from __future__ import annotations

import re
import time

from agent_eval.types import ModelClient, RunRecord, TurnUsage

from file_localization.contract import LocalizationTask, score


SYSTEM_PROMPT = """\
You are a precise code-localization assistant. Given a GitHub issue and a \
repository's file listing, you identify the files that must be examined and \
edited to investigate and fix the bug.

Output strictly one path per line, in this format:

  FILE: path/to/source.py
  FILE: tests/test_source.py

Most likely / most important files first. No prose, no explanations, no \
markdown — just FILE: lines.\
"""

USER_TEMPLATE = """\
## Repository
{repo} @ {commit}

## Issue
{issue}

## Files in repository
{file_list}

## Task
List every file needed to investigate and fix this issue, ranked by \
relevance. Include source files (where the bug likely lives) AND test files \
(where regression tests should be added or updated). Be selective — include \
only files that genuinely matter for this issue.
"""

_FILE_LINE = re.compile(r"^\s*FILE:\s*(\S+)\s*$", re.MULTILINE)


def parse_file_list(text: str) -> list[str]:
    """Extract ranked file paths from a model response."""
    paths = _FILE_LINE.findall(text or "")
    # Dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def make_llm_trial(top_k: int | None = None, fp_penalty: float = 0.05):
    """Factory: returns a Trial callable compatible with agent_eval.Sweep.

    Args:
        top_k: if set, only the top-k parsed files are scored
        fp_penalty: false-positive penalty in the composite score
    """

    def trial(client: ModelClient, condition: str, task: LocalizationTask) -> RunRecord:
        file_list = (
            "\n".join(task.repo_file_list) if task.repo_file_list else "(not provided)"
        )
        user_text = USER_TEMPLATE.format(
            repo=task.repo,
            commit=task.base_commit[:12] if task.base_commit else "unknown",
            issue=task.issue_text,
            file_list=file_list,
        )
        client.reset(SYSTEM_PROMPT)
        client.add_user_text(user_text)

        t0 = time.monotonic()
        try:
            msg = client.step(tools=[])
        except Exception as e:  # noqa: BLE001
            return RunRecord(
                task_id=task.task_id,
                model=client.name,
                condition=condition,
                passed=False,
                turns=1,
                tool_calls=0,
                invalid_tool_calls=0,
                usage=TurnUsage(),
                latency_seconds=time.monotonic() - t0,
                error=f"model_error: {type(e).__name__}: {e}",
            )
        latency = time.monotonic() - t0

        predicted = parse_file_list(msg.text)
        s = score(predicted, task.gold_all, k=top_k, fp_penalty=fp_penalty)

        return RunRecord(
            task_id=task.task_id,
            model=client.name,
            condition=condition,
            passed=s.passed,
            turns=1,
            tool_calls=0,
            invalid_tool_calls=0,
            usage=msg.usage,
            latency_seconds=latency,
            extra=s.as_extra(),
        )

    return trial
