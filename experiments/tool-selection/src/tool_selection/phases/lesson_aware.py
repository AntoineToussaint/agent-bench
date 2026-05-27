"""Lesson-aware variants of OnePhase and TwoPhase.

These accept a LessonStore at construction time and inject relevant lessons
into the right place per architecture:

  LessonAwareOnePhase:
    appends ALL relevant lessons (task-level + per-tool for surfaced tools)
    to the user message as a "Past lessons" block.

  LessonAwareTwoPhase:
    - phase 1 prompt gets ONLY task-level lessons
    - each phase 2 prompt gets ONLY that one tool's lessons
    This is the architectural advantage: phase-partitioned lesson injection
    means the smart model's context isn't polluted by lessons about tools
    it isn't calling.

Lessons accumulate across episodes in the LessonStore; both wrappers
read from the same store, and the runner script writes new lessons
back after each failed episode.
"""

from __future__ import annotations

import concurrent.futures as cf
from dataclasses import replace
from typing import Any

from agent_eval.types import ModelHandle

from tool_selection.execution.lessons import Lesson, LessonStore, task_signature
from tool_selection.types import PipelineStep, Task, Tool

from .base import Phase, PhaseResult
from .one_phase import BASE_SYSTEM_PROMPT, PLAN_FIRST_ADDENDUM, _call, _user_message
from .two_phase import (
    PHASE1_SYSTEM,
    PHASE2_SYSTEM_TEMPLATE,
    TwoPhase,
    _format_tool_menu,
    _llm_text_call,
    _llm_tool_call,
    _parse_plan,
)


def _render_lessons(lessons: list[Lesson], header: str) -> str:
    """Format a list of lessons as a compact prompt-injectable block."""
    if not lessons:
        return ""
    lines = [f"\n# {header}", "(distilled from past failures; apply to avoid recurring mistakes)"]
    for l in lessons:
        lines.append(f"  - [{l.category}] {l.text}")
    return "\n".join(lines)


class LessonAwareOnePhase(Phase):
    """OnePhase that prepends a Past-Lessons block to the user message.

    Lessons are sourced from a shared LessonStore. Both task-pattern lessons
    and per-tool lessons (for the surfaced tools) are surfaced — they all
    compete for attention in the single prompt, which is exactly the
    architectural disadvantage we want to measure.
    """

    def __init__(self, store: LessonStore, k_per_tool: int = 2, k_per_task: int = 4, plan_first: bool = True):
        self.store = store
        self.k_per_tool = k_per_tool
        self.k_per_task = k_per_task
        self.plan_first = plan_first
        self.id = "1phase-plan-lessons" if plan_first else "1phase-lessons"

    def execute(
        self,
        task: Task,
        surfaced_tools: list[Tool],
        model: str,
        handle: ModelHandle | None = None,
    ) -> PhaseResult:
        # Gather all relevant lessons
        task_lessons = self.store.for_task(task_signature(task), top_k=self.k_per_task)
        tool_lessons = self.store.all_for_tools(
            [t.name for t in surfaced_tools], top_k_per_tool=self.k_per_tool
        )
        all_lessons = task_lessons + tool_lessons

        # Mark fires
        for l in all_lessons:
            l.fires += 1

        # Build augmented user message
        user_msg = _user_message(task)
        if all_lessons:
            user_msg += _render_lessons(all_lessons, "Past lessons")

        # Optionally use plan-first system prompt — recommended because vanilla
        # 1phase + Haiku frequently emits incomplete plans, hiding the runtime
        # errors that lessons should learn from.
        system = BASE_SYSTEM_PROMPT + (PLAN_FIRST_ADDENDUM if self.plan_first else "")

        try:
            calls, text, step = _call(system, user_msg, surfaced_tools, model, handle=handle)
            step.note = (step.note or "") + f" [lessons:{len(all_lessons)} plan_first:{self.plan_first}]"
            return PhaseResult(final_calls=calls, final_text=text, steps=[step])
        except Exception as exc:  # noqa: BLE001
            return PhaseResult(
                final_calls=[], final_text="",
                steps=[PipelineStep(kind="final_shot", model=model, note=f"ERROR: {exc!r}")],
                error=repr(exc),
            )


class LessonAwareTwoPhase(Phase):
    """TwoPhase that routes lessons to their natural home:
    phase 1 sees task-level lessons; each phase 2 call sees ONLY that
    tool's per-tool lessons.
    """

    def __init__(
        self,
        store: LessonStore,
        selection_model: str | None = None,
        args_model: str | None = None,
        max_workers: int = 4,
        k_per_tool: int = 2,
        k_per_task: int = 4,
    ):
        self.store = store
        self.selection_model = selection_model
        self.args_model = args_model
        self.max_workers = max_workers
        self.k_per_tool = k_per_tool
        self.k_per_task = k_per_task
        sel_tag = (selection_model or "$").split("-")[1] if selection_model else "$"
        args_tag = (args_model or "$").split("-")[1] if args_model else "$"
        self.id = f"2phase-lessons:{sel_tag}+{args_tag}"

    def execute(
        self,
        task: Task,
        surfaced_tools: list[Tool],
        model: str,
        handle: ModelHandle | None = None,
    ) -> PhaseResult:
        sel_model = self.selection_model or model
        args_model = self.args_model or model
        # Same as TwoPhase: phase 1 can use the handle (single call);
        # phase 2 spawns parallel make_client calls.
        sel_handle = handle if (handle is not None and self.selection_model is None) else None

        # --- Phase 1: selection, augmented with task-level lessons only ---
        task_lessons = self.store.for_task(task_signature(task), top_k=self.k_per_task)
        for l in task_lessons:
            l.fires += 1

        menu = _format_tool_menu(surfaced_tools)
        lessons_block = _render_lessons(task_lessons, "Past lessons for this kind of task")
        phase1_user = (
            _user_message(task)
            + "\n# Available tools\n"
            + menu
            + "\n"
            + lessons_block
            + "\n\nReturn the JSON array of {name, intent} calls now."
        )

        try:
            text, sel_step = _llm_text_call(
                PHASE1_SYSTEM, phase1_user, sel_model, handle=sel_handle
            )
            sel_step.note = (sel_step.note or "") + f" [task_lessons:{len(task_lessons)}]"
            plan = _parse_plan(text, {t.name for t in surfaced_tools})
        except Exception as exc:  # noqa: BLE001
            return PhaseResult(
                final_calls=[], final_text="",
                steps=[PipelineStep(kind="llm_router", model=sel_model, note=f"PHASE1 ERROR: {exc!r}")],
                error=f"phase1: {exc!r}",
            )

        if not plan:
            return PhaseResult(
                final_calls=[], final_text=text,
                steps=[sel_step], error="phase1 produced no parsable plan",
            )

        # --- Phase 2: parallel arg calls, each augmented with ONLY that tool's lessons ---
        tools_by_name = {t.name: t for t in surfaced_tools}
        plan_summary = "\n".join(f"{i + 1}. {p['name']}: {p['intent']}" for i, p in enumerate(plan))

        def fill_one(idx: int, item: dict[str, str]):
            tool = tools_by_name[item["name"]]
            per_tool = self.store.for_tool(item["name"], top_k=self.k_per_tool)
            for l in per_tool:
                l.fires += 1
            tool_lessons_block = _render_lessons(per_tool, f"Past lessons for {item['name']}")

            sys_prompt = PHASE2_SYSTEM_TEMPLATE.format(
                tool_name=item["name"], intent=item["intent"], plan_context=plan_summary,
            ) + tool_lessons_block

            args, step = _llm_tool_call(sys_prompt, _user_message(task), tool, args_model)
            step.note = (step.note or "") + f" [tool_lessons:{len(per_tool)}]"
            return idx, args, step

        results = []
        with cf.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futs = [ex.submit(fill_one, i, item) for i, item in enumerate(plan)]
            for f in cf.as_completed(futs):
                results.append(f.result())
        results.sort(key=lambda r: r[0])

        steps: list[PipelineStep] = [sel_step]
        final_calls: list[dict[str, Any]] = []
        for idx, args, step in results:
            step.parallel_group = 1
            steps.append(step)
            if args is not None:
                final_calls.append({"name": plan[idx]["name"], "input": args})

        return PhaseResult(final_calls=final_calls, final_text=text, steps=steps)
