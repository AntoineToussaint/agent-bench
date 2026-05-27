"""Run one (approach × catalog × model × task) and produce (CallTrace, ScoreCard)."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_eval.types import ModelHandle

from .approaches.base import Approach
from .phases.base import Phase
from .phases.one_phase import OnePhase
from .scorer import score
from .types import Catalog, CallTrace, ScoreCard, Task


def run_one(
    approach: Approach,
    catalog: Catalog,
    model: str,
    task: Task,
    phase: Phase | None = None,
    handle: ModelHandle | None = None,
) -> tuple[CallTrace, ScoreCard]:
    """Run one (approach × catalog × model × task) and produce (CallTrace, ScoreCard).

    `phase` defaults to OnePhase (the original behavior). Pass PlanFirstPhase,
    OnePhaseConfusabilityAware, or TwoPhase to evaluate other final-shot variants.

    `handle`, when supplied, drives the final-shot through its bundled
    `ToolBackend` (and is needed for OTEL trace nesting under the sweep's
    trial span). When None, phases fall back to `make_client(model)` with
    the default backend — preserves legacy CLI / notebook usage.
    """
    if phase is None:
        phase = OnePhase()

    result = approach.surface(task, catalog)
    surfaced = result.surfaced_tools
    surfaced_names = [t.name for t in surfaced]

    phase_result = phase.execute(task, surfaced, model, handle=handle)

    trace = CallTrace(
        task_id=task.id,
        approach_id=f"{approach.id}|{phase.id}",
        granularity=catalog.granularity,
        final_model=model,
        surfaced_tools=surfaced_names,
        final_calls=phase_result.final_calls,
        final_text=phase_result.final_text,
        pipeline=list(result.pre_steps) + list(phase_result.steps),
        error=phase_result.error,
    )
    sc = score(trace, task, catalog)
    return trace, sc


def write_trace_jsonl(traces_and_scores: list[tuple[CallTrace, ScoreCard]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for tr, sc in traces_and_scores:
            row: dict[str, Any] = {
                "task_id": tr.task_id,
                "approach": tr.approach_id,
                "granularity": tr.granularity,
                "model": tr.final_model,
                "success": sc.task_success,
                "required_total": sc.required_total,
                "required_matched": sc.required_matched,
                "selection_matched": sc.selection_matched,
                "selection_accuracy": sc.selection_accuracy,
                "args_accuracy_given_selection": sc.args_accuracy_given_selection,
                "missing": sc.missing_required,
                "hallucinated": sc.hallucinated_calls,
                "extras": sc.extra_calls,
                "forbidden_called": sc.forbidden_called,
                "schema_invalid": sc.schema_invalid_calls,
                "total_cost_usd": tr.total_cost_usd,
                "total_latency_ms": tr.total_latency_ms,
                "input_tokens": tr.total_input_tokens,
                "output_tokens": tr.total_output_tokens,
                "surfaced_count": len(tr.surfaced_tools),
                "n_calls": len(tr.final_calls),
                "pipeline": [asdict(s) for s in tr.pipeline],
                "final_calls": tr.final_calls,
                "error": tr.error,
            }
            f.write(json.dumps(row) + "\n")
