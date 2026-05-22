"""Two-phase tool calling: selection then per-tool argument construction.

Phase 1 — selection: model sees (name, description) for every surfaced tool
  plus the task. Returns a JSON list of {name, intent} entries in execution
  order. Intents are free-text hints (one line each) that phase 2 uses to
  disambiguate when the same tool is called multiple times.

Phase 2 — argument construction: for each (name, intent) from phase 1, ONE
  focused LLM call (in parallel via ThreadPoolExecutor) with only that tool's
  full JSON schema in context. Returns the input dict.

The two phases can use different models. Cheap-then-strong (Haiku for select,
Sonnet for args) is the canonical setup motivated by Anthropic's Sonnet 4.6
release notes claiming better-formed function arguments.

Failure modes targeted (from research):
  - Wrong arguments (Anthropic's "appending 2025" canonical example)
  - Schema violations (focused schema in phase 2 reduces drift)
  - Confusable siblings (phase 1 disambiguates without the args distraction)
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import time
from typing import Any

from dotenv import load_dotenv

from tool_selection.pricing import cost_for
from tool_selection.types import PipelineStep, Task, Tool

from .base import Phase, PhaseResult

load_dotenv()


PHASE1_SYSTEM = """\
You are doing TOOL SELECTION (phase 1 of a two-phase tool-calling protocol).
You will be shown a user task and a list of available tools (name +
description only — full argument schemas come in phase 2).

Your job: decide the exact ordered sequence of tool calls needed to complete
the task. Return a JSON array of objects, one per call, each with:
  - "name": the exact tool name from the list
  - "intent": a one-line description of what THIS specific call accomplishes
              (this is critical when the same tool is called multiple times —
              e.g. "stage dark.css" vs "stage index.css" vs "stage test stub")

Output ONLY the JSON array, no commentary, no markdown fence. Example:
[
  {"name": "git_add", "intent": "stage the modified CSS file"},
  {"name": "git_commit", "intent": "record the CSS change with a feat: message"},
  {"name": "git_push", "intent": "publish to origin"}
]

Rules:
- Emit every call needed to fully complete the task. Do not stop early.
- Do not include discovery calls (read_file, git_status, etc.) — the user has
  pre-surfaced all the state you need in the Context section.
- Pick the most specific tool for each step. Watch out for confusable sibling
  tools — pick the one whose description matches what the task explicitly asks.
"""

PHASE2_SYSTEM_TEMPLATE = """\
You are doing TOOL ARGUMENT CONSTRUCTION (phase 2 of a two-phase tool-calling
protocol). You have already committed to calling `{tool_name}` with the
following intent:

    {intent}

This call is part of a larger plan; here is the full ordered plan so you know
the context of where this call fits:

{plan_context}

You will now use the `{tool_name}` tool exactly once. Construct the arguments
strictly per its JSON schema. Reference the task context for concrete values
(file paths, PR numbers, line numbers, line content). Do not add extra args
not in the schema; do supply every required arg.
"""


def _user_message(task: Task) -> str:
    return (
        f"# Task\n{task.prompt}\n\n"
        f"# Context (state the user has already surfaced)\n{task.context}\n"
    )


def _format_tool_menu(tools: list[Tool]) -> str:
    by_box: dict[str, list[Tool]] = {}
    for t in tools:
        by_box.setdefault(t.toolbox, []).append(t)
    lines = []
    for box, ts in by_box.items():
        lines.append(f"\n## {box} toolbox")
        for t in ts:
            short = t.description.split(".")[0]
            lines.append(f"  - `{t.name}`: {short.strip()}")
    return "\n".join(lines)


def _parse_plan(text: str, valid_names: set[str]) -> list[dict[str, str]]:
    """Pull a JSON array of {name, intent} from the model's phase-1 response."""
    text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(parsed, list):
        return []
    out = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        intent = item.get("intent", "")
        if isinstance(name, str) and name in valid_names:
            out.append({"name": name, "intent": str(intent)})
    return out


# ---------- model calls ----------


def _llm_text_call(
    system: str, user: str, model: str, max_tokens: int = 1024
) -> tuple[str, PipelineStep]:
    """Call without tools — just get text back. Used for phase 1."""
    t0 = time.perf_counter()
    if model.startswith("claude"):
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        inp = resp.usage.input_tokens
        out = resp.usage.output_tokens
    elif model.startswith("gpt"):
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        text = resp.choices[0].message.content or ""
        inp = resp.usage.prompt_tokens
        out = resp.usage.completion_tokens
    else:
        raise ValueError(f"unknown model: {model}")

    latency_ms = (time.perf_counter() - t0) * 1000
    step = PipelineStep(
        kind="llm_router",
        model=model,
        input_tokens=inp,
        output_tokens=out,
        cost_usd=cost_for(model, inp, out),
        latency_ms=latency_ms,
        note="2phase:select",
    )
    return text, step


def _llm_tool_call(
    system: str, user: str, tool: Tool, model: str, max_tokens: int = 1024
) -> tuple[dict[str, Any] | None, PipelineStep]:
    """Call with exactly one tool available. Used for phase 2."""
    t0 = time.perf_counter()
    if model.startswith("claude"):
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool.to_anthropic()],
            tool_choice={"type": "tool", "name": tool.name},
        )
        result: dict[str, Any] | None = None
        for block in resp.content:
            if block.type == "tool_use" and block.name == tool.name:
                result = dict(block.input)
                break
        inp = resp.usage.input_tokens
        out = resp.usage.output_tokens
    elif model.startswith("gpt"):
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=[tool.to_openai()],
            tool_choice={"type": "function", "function": {"name": tool.name}},
        )
        choice = resp.choices[0]
        result = None
        for tc in choice.message.tool_calls or []:
            if tc.function.name == tool.name:
                try:
                    result = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    result = {"__raw__": tc.function.arguments}
                break
        inp = resp.usage.prompt_tokens
        out = resp.usage.completion_tokens
    else:
        raise ValueError(f"unknown model: {model}")

    latency_ms = (time.perf_counter() - t0) * 1000
    step = PipelineStep(
        kind="final_shot",
        model=model,
        input_tokens=inp,
        output_tokens=out,
        cost_usd=cost_for(model, inp, out),
        latency_ms=latency_ms,
        note=f"2phase:args:{tool.name}",
    )
    return result, step


class TwoPhase(Phase):
    """Phase 1 selects (name, intent) sequence. Phase 2 fills args per call in parallel.

    Construction:
      - selection_model: overrides runner-provided model for phase 1. If None,
        phase 1 uses the runner-provided model.
      - args_model: overrides runner-provided model for phase 2. If None,
        phase 2 uses the runner-provided model.
      - max_workers: parallelism for phase 2 calls (default 4).
    """

    def __init__(
        self,
        selection_model: str | None = None,
        args_model: str | None = None,
        max_workers: int = 4,
    ):
        self.selection_model = selection_model
        self.args_model = args_model
        self.max_workers = max_workers
        sel_tag = (selection_model or "$").split("-")[1] if selection_model else "$"
        args_tag = (args_model or "$").split("-")[1] if args_model else "$"
        self.id = f"2phase:{sel_tag}+{args_tag}"

    def execute(self, task: Task, surfaced_tools: list[Tool], model: str) -> PhaseResult:
        sel_model = self.selection_model or model
        args_model = self.args_model or model

        # Phase 1 — selection
        try:
            menu = _format_tool_menu(surfaced_tools)
            phase1_user = (
                _user_message(task)
                + "\n# Available tools\n"
                + menu
                + "\n\n"
                + "Return the JSON array of {name, intent} calls now."
            )
            text, sel_step = _llm_text_call(PHASE1_SYSTEM, phase1_user, sel_model)
            plan = _parse_plan(text, {t.name for t in surfaced_tools})
        except Exception as exc:  # noqa: BLE001
            return PhaseResult(
                final_calls=[],
                final_text="",
                steps=[PipelineStep(kind="llm_router", model=sel_model, note=f"PHASE1 ERROR: {exc!r}")],
                error=f"phase1: {exc!r}",
            )

        if not plan:
            return PhaseResult(
                final_calls=[],
                final_text=text,
                steps=[sel_step],
                error="phase1 produced no parsable plan",
            )

        # Phase 2 — args per call, in parallel
        tools_by_name = {t.name: t for t in surfaced_tools}
        plan_summary = "\n".join(f"{i + 1}. {p['name']}: {p['intent']}" for i, p in enumerate(plan))

        def fill_one(idx: int, item: dict[str, str]) -> tuple[int, dict[str, Any] | None, PipelineStep]:
            tool = tools_by_name[item["name"]]
            sys_prompt = PHASE2_SYSTEM_TEMPLATE.format(
                tool_name=item["name"],
                intent=item["intent"],
                plan_context=plan_summary,
            )
            args, step = _llm_tool_call(sys_prompt, _user_message(task), tool, args_model)
            return idx, args, step

        results: list[tuple[int, dict[str, Any] | None, PipelineStep]] = []
        with cf.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futs = [ex.submit(fill_one, i, item) for i, item in enumerate(plan)]
            for f in cf.as_completed(futs):
                results.append(f.result())

        results.sort(key=lambda r: r[0])
        steps: list[PipelineStep] = [sel_step]
        final_calls: list[dict[str, Any]] = []
        # All phase-2 arg calls ran in parallel — mark them as a single group
        # so total_latency_ms aggregates them as max(), not sum().
        for idx, args, step in results:
            step.parallel_group = 1
            steps.append(step)
            if args is not None:
                final_calls.append({"name": plan[idx]["name"], "input": args})

        return PhaseResult(
            final_calls=final_calls,
            final_text=text,
            steps=steps,
        )
