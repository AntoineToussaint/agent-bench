"""Single-API-call phases.

OnePhase                       — the original behavior; model gets surfaced
                                 tools, emits all tool_use blocks in one shot.
PlanFirstPhase                 — same single call, but the prompt requires a
                                 <plan> block listing every tool call before
                                 emitting them.
OnePhaseConfusabilityAware     — OnePhase + an auto-generated disambiguation
                                 section in the system prompt when the
                                 surfaced set contains sibling tools.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from dotenv import load_dotenv

from tool_selection.pricing import cost_for
from tool_selection.types import PipelineStep, Task, Tool

from .base import Phase, PhaseResult

load_dotenv()

BASE_SYSTEM_PROMPT = """\
You are an automation assistant operating in a strict ONE-SHOT execution mode:

- This is your only response. There will be no follow-up turns. You will not
  receive any tool results back. You must emit every tool call needed to
  fully complete the task in THIS response, all at once.

- The user has pre-surfaced every piece of state you need in the "Context"
  section of their message. Treat it as authoritative ground truth — file
  contents, branch state, PR numbers, line numbers, current directory, etc.

- DO NOT emit discovery / inspection calls (read_file, git_status, git_diff,
  list_directory, gh_pr_view, glob/grep, etc.) when the user has already given
  you the relevant state. Emit only the write-side / action-side calls that
  the task requires.

- Pick the most specific tool for each step. When several tools look similar,
  the disambiguating detail is in the description — for example, a comment
  pinned to a line in a PR diff is NOT the same tool as a top-level PR
  conversation comment.

- Pass all required arguments per each tool's JSON schema, and use the
  optional arguments when the task explicitly calls for them (draft PR,
  upstream tracking, etc.).

- Emit the calls in execution order (e.g. git_add before git_commit).
"""

PLAN_FIRST_ADDENDUM = """

# Plan-first protocol (required)

Before emitting any tool_use block, write a numbered execution plan inside
<plan>...</plan> tags. The plan lists EVERY tool you will call, in order,
with a one-line justification each. Example shape:

<plan>
1. git_add(paths=[...])    — stage the modified file
2. git_commit(message=...) — record the change
3. git_push(...)           — publish to remote
</plan>

After closing </plan>, emit each listed tool_use block in the same order.
Do not stop after the plan; the plan MUST be followed by the tool_use blocks.
Do not emit fewer tool_use blocks than your plan lists.
"""


def _user_message(task: Task) -> str:
    return (
        f"# Task\n{task.prompt}\n\n"
        f"# Context (state the user has already surfaced — you do not need to discover it)\n"
        f"{task.context}\n"
    )


def _detect_confusable_groups(surfaced: list[Tool]) -> list[list[Tool]]:
    """Group surfaced tools by shared prefix (snake_case) so we can build
    a disambiguation section. A group is only flagged if it has 2+ tools."""
    by_prefix: dict[str, list[Tool]] = {}
    for t in surfaced:
        # Group by first two underscore-separated tokens, e.g. 'gh_pr' for
        # gh_pr_comment / gh_pr_review_comment. Falls back to first token.
        parts = t.name.split("_")
        prefix = "_".join(parts[:2]) if len(parts) >= 2 else parts[0]
        by_prefix.setdefault(prefix, []).append(t)
    return [g for g in by_prefix.values() if len(g) >= 2]


def _build_confusability_section(surfaced: list[Tool]) -> str:
    groups = _detect_confusable_groups(surfaced)
    if not groups:
        return ""
    lines = [
        "\n# Sibling-tool disambiguation",
        "Some surfaced tools share a prefix and look similar. Pick the most",
        "specific one — the distinguishing word and the description matter.\n",
    ]
    for g in groups:
        if len(g) < 2:
            continue
        lines.append(f"## {g[0].name.split('_')[0]}_ family:")
        for t in g:
            short = t.description.split(".")[0]
            lines.append(f"  - `{t.name}`: {short.strip()}")
        lines.append("")
    return "\n".join(lines)


def _anthropic_call(
    system: str, user: str, tools: list[Tool], model: str, max_tokens: int = 4096
) -> tuple[list[dict[str, Any]], str, PipelineStep]:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    t0 = time.perf_counter()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[t.to_anthropic() for t in tools],
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    calls: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for block in resp.content:
        if block.type == "tool_use":
            calls.append({"name": block.name, "input": dict(block.input)})
        elif block.type == "text":
            text_parts.append(block.text)
    usage = resp.usage
    step = PipelineStep(
        kind="final_shot",
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=cost_for(model, usage.input_tokens, usage.output_tokens),
        latency_ms=latency_ms,
        note=f"stop_reason={resp.stop_reason}",
    )
    return calls, "\n".join(text_parts), step


def _openai_call(
    system: str, user: str, tools: list[Tool], model: str, max_tokens: int = 4096
) -> tuple[list[dict[str, Any]], str, PipelineStep]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model,
        max_completion_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        tools=[t.to_openai() for t in tools],
        parallel_tool_calls=True,
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    choice = resp.choices[0]
    calls: list[dict[str, Any]] = []
    for tc in choice.message.tool_calls or []:
        try:
            args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            args = {"__raw__": tc.function.arguments}
        calls.append({"name": tc.function.name, "input": args})
    text = choice.message.content or ""
    usage = resp.usage
    step = PipelineStep(
        kind="final_shot",
        model=model,
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        cost_usd=cost_for(model, usage.prompt_tokens, usage.completion_tokens),
        latency_ms=latency_ms,
        note=f"finish_reason={choice.finish_reason}",
    )
    return calls, text, step


def _call(system: str, user: str, tools: list[Tool], model: str) -> tuple[list[dict[str, Any]], str, PipelineStep]:
    if model.startswith("claude"):
        return _anthropic_call(system, user, tools, model)
    if model.startswith("gpt"):
        return _openai_call(system, user, tools, model)
    raise ValueError(f"unknown model: {model}")


class OnePhase(Phase):
    id = "1phase"

    def execute(self, task: Task, surfaced_tools: list[Tool], model: str) -> PhaseResult:
        try:
            calls, text, step = _call(BASE_SYSTEM_PROMPT, _user_message(task), surfaced_tools, model)
            return PhaseResult(final_calls=calls, final_text=text, steps=[step])
        except Exception as exc:  # noqa: BLE001
            return PhaseResult(
                final_calls=[],
                final_text="",
                steps=[PipelineStep(kind="final_shot", model=model, note=f"ERROR: {exc!r}")],
                error=repr(exc),
            )


class PlanFirstPhase(Phase):
    """OnePhase + plan-first protocol in the system prompt.

    Hypothesis (from KAMI + Lost-in-Multi-Turn evidence): forcing the model
    to enumerate the full call sequence in plain text before emitting tool_use
    blocks reduces 'stopped mid-plan' truncation. The plan acts as a
    commitment device the model has to honor in the same turn.
    """

    id = "1phase-plan"

    def execute(self, task: Task, surfaced_tools: list[Tool], model: str) -> PhaseResult:
        system = BASE_SYSTEM_PROMPT + PLAN_FIRST_ADDENDUM
        try:
            calls, text, step = _call(system, _user_message(task), surfaced_tools, model)
            step.note = (step.note or "") + " [plan-first]"
            return PhaseResult(final_calls=calls, final_text=text, steps=[step])
        except Exception as exc:  # noqa: BLE001
            return PhaseResult(
                final_calls=[],
                final_text="",
                steps=[PipelineStep(kind="final_shot", model=model, note=f"ERROR: {exc!r}")],
                error=repr(exc),
            )


class OnePhaseConfusabilityAware(Phase):
    """OnePhase + auto-generated disambiguation for sibling tools in the surfaced set.

    Hypothesis (from TRAJECT-Bench): the dominant 'wrong sibling' failure
    mode shrinks when the system prompt explicitly highlights what
    distinguishes each member of a confusable group. Cost: one extra
    paragraph of input tokens.
    """

    id = "1phase-confuse"

    def execute(self, task: Task, surfaced_tools: list[Tool], model: str) -> PhaseResult:
        addendum = _build_confusability_section(surfaced_tools)
        system = BASE_SYSTEM_PROMPT + addendum
        try:
            calls, text, step = _call(system, _user_message(task), surfaced_tools, model)
            step.note = (step.note or "") + (
                f" [confuse:{len(_detect_confusable_groups(surfaced_tools))}groups]"
            )
            return PhaseResult(final_calls=calls, final_text=text, steps=[step])
        except Exception as exc:  # noqa: BLE001
            return PhaseResult(
                final_calls=[],
                final_text="",
                steps=[PipelineStep(kind="final_shot", model=model, note=f"ERROR: {exc!r}")],
                error=repr(exc),
            )
