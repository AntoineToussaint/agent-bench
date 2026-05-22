"""Bridge between the existing single-shot Phase classes and the multi-turn runner.

Wraps a (Approach, Phase, Catalog, Model) into an AgentStep callable that the
runner can invoke per attempt. Prior-attempt errors are formatted into the
task prompt so the model can attempt recovery.

Lesson injection (LessonStore-aware variants) plugs in here too — see
LessonAwareAgentStep.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from tool_selection.approaches.base import Approach
from tool_selection.phases.base import Phase
from tool_selection.types import Catalog, Task

from .runner import EpisodeAttempt
from .state import Call


def _format_prior_attempts(prior: list[EpisodeAttempt]) -> str:
    """Render prior attempts as a compact trace the agent can read."""
    if not prior:
        return ""
    lines = ["# Previous attempts (failed — try again, addressing the error)"]
    for i, attempt in enumerate(prior, start=1):
        lines.append(f"\n## Attempt {i}")
        for call, result in zip(attempt.calls, attempt.results):
            args_repr = ", ".join(
                f"{k}={v!r}" if not isinstance(v, str) or len(v) < 80
                else f"{k}={v[:80]!r}..."
                for k, v in call.args.items() if v is not None
            )
            if result.ok:
                lines.append(f"  {call.tool}({args_repr}) → ok")
            else:
                lines.append(f"  {call.tool}({args_repr}) → ERROR: {result.error}")
                if result.triggered_by:
                    lines.append(f"    (likely cause: {result.triggered_by})")
    lines.append("\n# Now retry. The errors above must be resolved.")
    return "\n".join(lines)


def make_agent_step(
    approach: Approach,
    phase: Phase,
    catalog: Catalog,
    model: str,
):
    """Build an AgentStep that surfaces tools, runs the phase, and converts
    output to the runner's Call type. Surfacing happens once at episode start;
    only the prompt is updated between attempts.
    """
    # Surface tools once at the start of the episode (caller does this by
    # calling make_agent_step once per episode). The closure captures these.
    surface_result = None  # filled on first call

    def step(task: Task, prior: list[EpisodeAttempt]):
        nonlocal surface_result
        if surface_result is None:
            surface_result = approach.surface(task, catalog)

        # Augment the task prompt with prior-attempt trace if any
        if prior:
            augmented_prompt = task.prompt + "\n\n" + _format_prior_attempts(prior)
            this_task = replace(task, prompt=augmented_prompt)
        else:
            this_task = task

        pr = phase.execute(this_task, surface_result.surfaced_tools, model)

        calls = [Call(tool=c["name"], args=c.get("input", {})) for c in pr.final_calls]

        telemetry = {
            "cost_usd": sum(s.cost_usd for s in pr.steps) + sum(
                s.cost_usd for s in surface_result.pre_steps
            ) if not prior else sum(s.cost_usd for s in pr.steps),
            "latency_ms": sum(s.latency_ms for s in pr.steps),
            "input_tokens": sum(s.input_tokens for s in pr.steps),
            "output_tokens": sum(s.output_tokens for s in pr.steps),
            "surfaced_tools": [t.name for t in surface_result.surfaced_tools],
        }
        return calls, pr.final_text, telemetry

    return step
