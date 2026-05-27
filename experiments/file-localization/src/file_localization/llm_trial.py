"""LLM-based localization trial: the protocol the user described.

> Take this GitHub issue and find all the files that are needed for a proper
> investigation of that bug. Respond by writing FILE: <path> lines.

The model receives the issue + a candidate file list and replies with a
ranked list of FILE: lines, one per file. The trial parses the response
and scores it against the gold patch via `contract.score`.

Plugs into `agent_eval.Sweep` via the standard Trial signature:
    (ModelHandle, condition: str, LocalizationTask) -> RunRecord
"""

from __future__ import annotations

import re
import time

from agent_eval.failure_modes import classify_output
from agent_eval.pricing import cost_usd
from agent_eval.types import ModelHandle, RunRecord, TurnUsage

from file_localization.contract import LocalizationTask, score
from file_localization.prompts import system_prompt_for, user_message


_OUTPUT_FORMAT_BLOCK = """\
## Output format
Output strictly one path per line, in this format:

  FILE: path/to/source.py
  FILE: tests/test_source.py

Most likely / most important files first. No prose, no explanations, no \
markdown — just `FILE:` lines.\
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

    def trial(handle: ModelHandle, condition: str, task: LocalizationTask) -> RunRecord:
        # One-shot doesn't use a backend — no tools are involved. We
        # accept a ModelHandle for signature uniformity and reach for
        # `handle.client` directly.
        client = handle.client
        file_list = (
            "\n".join(task.repo_file_list) if task.repo_file_list else "(not provided)"
        )
        system_prompt = system_prompt_for(
            task.task_class, extra_tools_block=_OUTPUT_FORMAT_BLOCK
        )
        user_text = (
            user_message(task.repo, task.base_commit, task.issue_text)
            + f"\n\n## Files in repository\n{file_list}"
        )
        client.reset(system_prompt)
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
        # One-shot has no tool channel → classify will return
        # `harness_blocked_exploration` for any failure, which is the
        # accurate diagnosis (no exploration is possible).
        failure_mode = classify_output(
            predicted_files=predicted,
            gold_files=task.gold_all,
            issue_text=task.issue_text,
            raw_response_text=msg.text or "",
            turn_count=1,
            tool_call_count=0,
            has_tool_channel=False,
        )

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
            extra={
                **s.as_extra(),
                "submitted": predicted,
                "failure_mode": failure_mode,
            },
        )

    return trial
