"""Trial wrapper: existing approach/phase machinery → `agent_eval.Sweep`-compatible.

The original `tool_selection.runner.run_one()` returns
`(CallTrace, ScoreCard)`. This module wraps it into a Trial function
`(ModelHandle, condition_str, Task) -> RunRecord` so trials plug straight
into `agent_eval.Sweep`.

Trials route the LLM call through the `ModelHandle`'s bundled `ToolBackend`
(by default the YAML-configured one per model). For one-shot tool-selection
the default is "native" tool_use — schema-enforced is a sensible
research override when you want to compare format constraints.

Usage:

    from agent_eval import Sweep
    from tool_selection.approaches.full import Full
    from tool_selection.adapters import all_tasks
    from tool_selection.catalogs.narrow import NARROW_CATALOG
    from tool_selection.phases.one_phase import OnePhase
    from tool_selection.trial import make_trial

    sweep = Sweep(
        models=["claude-haiku-4-5", "claude-sonnet-4-6"],
        conditions=[f"{Full().id}|{OnePhase().id}"],   # for telemetry
        tasks=list(all_tasks()),
        trial=make_trial(Full(), NARROW_CATALOG, OnePhase()),
    )
    records = sweep.run()
"""

from __future__ import annotations

import time
from typing import Callable

from agent_eval.failure_modes import classify_tool_selection
from agent_eval.types import ModelHandle, RunRecord, TurnUsage

from tool_selection.approaches.base import Approach
from tool_selection.phases.base import Phase
from tool_selection.phases.one_phase import OnePhase
from tool_selection.runner import run_one
from tool_selection.types import Catalog, Task


Trial = Callable[[ModelHandle, str, Task], RunRecord]


def make_trial(
    approach: Approach,
    catalog: Catalog,
    phase: Phase | None = None,
) -> Trial:
    """Factory: bind (approach, catalog, phase) and return a Trial.

    Args:
        approach: an Approach instance (Full, ToolboxLLM, Hybrid, ...).
        catalog: the tool catalog the approach surfaces from.
        phase: defaults to OnePhase. Pass PlanFirstPhase, TwoPhase, etc.
    """
    phase = phase or OnePhase()

    def trial(handle: ModelHandle, condition: str, task: Task) -> RunRecord:
        t0 = time.monotonic()
        try:
            trace, sc = run_one(
                approach=approach,
                catalog=catalog,
                model=handle.client.name,
                task=task,
                phase=phase,
                handle=handle,
            )
        except Exception as e:  # noqa: BLE001
            return RunRecord(
                task_id=task.id,
                model=handle.client.name,
                condition=condition,
                passed=False,
                turns=1,
                tool_calls=0,
                invalid_tool_calls=0,
                usage=TurnUsage(),
                latency_seconds=time.monotonic() - t0,
                error=f"trial_error: {type(e).__name__}: {e}",
            )

        latency_s = (trace.total_latency_ms or 0) / 1000.0
        if latency_s == 0:
            latency_s = time.monotonic() - t0

        # `invalid_tool_calls` on RunRecord is an int (count). The three
        # ScoreCard fields are lists of call ids/names — sum their lengths.
        # The full lists are preserved in `extra` below for debugging.
        invalid = (
            len(sc.schema_invalid_calls)
            + len(sc.hallucinated_calls)
            + len(sc.forbidden_called)
        )

        failure_mode = classify_tool_selection(
            hallucinated_calls=list(sc.hallucinated_calls),
            missing_required=list(sc.missing_required),
            forbidden_called=list(sc.forbidden_called),
            schema_invalid_calls=list(sc.schema_invalid_calls),
            selection_matched=bool(sc.selection_matched),
            passed=bool(sc.task_success),
        )

        extra: dict[str, object] = {
            "failure_mode": failure_mode,
            # Selection
            "selection_matched": sc.selection_matched,
            "selection_accuracy": sc.selection_accuracy,
            # Args
            "args_accuracy_given_selection": sc.args_accuracy_given_selection,
            # Required-set breakdown
            "required_total": sc.required_total,
            "required_matched": sc.required_matched,
            "missing_required": list(sc.missing_required),
            "extras_called": list(sc.extra_calls),
            "hallucinated": list(sc.hallucinated_calls),
            "forbidden_called": list(sc.forbidden_called),
            "schema_invalid": list(sc.schema_invalid_calls),
            # Catalog / approach metadata
            "approach_id": trace.approach_id,
            "granularity": trace.granularity,
            "surfaced_count": len(trace.surfaced_tools),
            "n_calls": len(trace.final_calls),
            "trace_error": trace.error,
        }

        return RunRecord(
            task_id=task.id,
            model=handle.client.name,
            condition=condition,
            passed=sc.task_success,
            turns=1,
            tool_calls=len(trace.final_calls),
            invalid_tool_calls=invalid,
            usage=TurnUsage(
                input_tokens=trace.total_input_tokens or 0,
                output_tokens=trace.total_output_tokens or 0,
            ),
            latency_seconds=latency_s,
            cost_usd=trace.total_cost_usd or 0.0,
            error=trace.error,
            extra=extra,
        )

    return trial
