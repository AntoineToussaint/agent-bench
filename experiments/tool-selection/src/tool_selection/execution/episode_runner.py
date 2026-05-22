"""High-level driver: run a task as a multi-turn episode, retrying until either
the task scorer says complete, an attempt produces empty output (model gave up),
or max_retries is hit.

Differs from the bare runner.run_episode in that this one is task-aware: it
scores after every attempt and continues if the required calls aren't all
satisfied — even if no execution errors fired. This handles the case where
the model does discovery (e.g. `pwd`) and stops without doing the real work.
"""

from __future__ import annotations

from dataclasses import dataclass

from tool_selection.scorer import score
from tool_selection.types import Catalog, CallTrace, ScoreCard, Task

from .executor import _DERIVED_WRAPPERS, execute_call
from .runner import Episode, EpisodeAttempt
from .state import Call, FailureTrigger


def _effective_call(c: Call) -> dict:
    """When the model calls a derived tool, the 'effective' call for scoring
    is the source-tool call (after wrap_fn). This means a successful
    `pytest_run(test_path='test_auth.py')` scores as the required
    `bash(command~='pytest verify/test_auth.py')`."""
    if c.tool in _DERIVED_WRAPPERS:
        derived = _DERIVED_WRAPPERS[c.tool]
        try:
            return {"name": derived.source_tool_name, "input": derived.wrap_fn(c.args)}
        except Exception:
            return {"name": c.tool, "input": c.args}
    return {"name": c.tool, "input": c.args}


@dataclass
class EpisodeResult:
    episode: Episode
    score: ScoreCard
    task_success: bool


def run_and_score(
    task: Task,
    catalog: Catalog,
    agent_step,
    model: str,
    max_retries: int = 4,
) -> EpisodeResult:
    triggers: tuple[FailureTrigger, ...] = task.failure_triggers
    ep = Episode(task_id=task.id)
    surfaced_names: list[str] = []
    last_score: ScoreCard | None = None

    for attempt_idx in range(max_retries):
        calls_raw, text, telemetry = agent_step(task, ep.attempts)
        ep.total_cost_usd += telemetry.get("cost_usd", 0.0)
        ep.total_latency_ms += telemetry.get("latency_ms", 0.0)
        ep.total_input_tokens += telemetry.get("input_tokens", 0)
        ep.total_output_tokens += telemetry.get("output_tokens", 0)
        surfaced_names = telemetry.get("surfaced_tools", surfaced_names)

        # Execute the attempt's calls
        results = []
        any_failed = False
        for call_idx, call in enumerate(calls_raw):
            history = ep.flat_calls + list(calls_raw[:call_idx])
            res = execute_call(call, history, triggers)
            results.append(res)
            if not res.ok:
                any_failed = True
                if res.category:
                    ep.error_categories_seen.append(res.category)
                break

        ep.attempts.append(
            EpisodeAttempt(calls=calls_raw[: len(results)], results=results, text=text)
        )
        ep.n_attempts = attempt_idx + 1

        # If the model emitted nothing, it gave up — stop retrying
        if not calls_raw:
            break

        # Score against effective (post-derived-translation) calls
        final_calls = [_effective_call(c) for c in ep.flat_calls]
        partial_trace = CallTrace(
            task_id=task.id,
            approach_id="multiturn",
            granularity=catalog.granularity,
            final_model=model,
            surfaced_tools=surfaced_names or [t.name for t in catalog.all_tools],
            final_calls=final_calls,
        )
        last_score = score(partial_trace, task, catalog)

        # Success path: no execution errors AND task scorer says complete
        if not any_failed and last_score.task_success:
            ep.succeeded = True
            return EpisodeResult(episode=ep, score=last_score, task_success=True)
        # Otherwise: keep retrying (either because of execution errors OR
        # because the task isn't done — both are signals to give the model
        # another turn with the prior attempts' trace in its prompt).

    # Out of retries — return whatever we have
    if last_score is None:
        # No attempts produced any calls; produce a degenerate scorecard
        last_score = score(
            CallTrace(
                task_id=task.id,
                approach_id="multiturn",
                granularity=catalog.granularity,
                final_model=model,
                surfaced_tools=surfaced_names or [t.name for t in catalog.all_tools],
                final_calls=[],
            ),
            task,
            catalog,
        )
    return EpisodeResult(episode=ep, score=last_score, task_success=False)
