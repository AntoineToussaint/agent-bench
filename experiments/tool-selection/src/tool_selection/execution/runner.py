"""Multi-turn episode runner: agent emits tool calls, executor checks failure
triggers, errors fed back to the agent for retry. Bounded by max_retries.

Distinct from the single-shot runner in tool_selection.runner — this one
threads tool_result content back into the model's next turn so the model
can attempt recovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .state import Call, CallResult, FailureTrigger


@dataclass
class EpisodeAttempt:
    """One agent turn within an episode: a batch of tool calls + their results."""

    calls: list[Call]
    results: list[CallResult]
    text: str = ""
    """Any free-text the model produced this attempt."""


@dataclass
class Episode:
    """Full record of a multi-turn task attempt."""

    task_id: str
    attempts: list[EpisodeAttempt] = field(default_factory=list)
    succeeded: bool = False
    n_attempts: int = 0
    error_categories_seen: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    @property
    def flat_calls(self) -> list[Call]:
        """All calls across all attempts, in order. Used by failure-trigger
        predicates that need to know what's been tried this episode."""
        return [c for att in self.attempts for c in att.calls]


# An "agent step" is whatever produces the next batch of calls given the
# current episode state. We keep this abstract so we can wire it to any phase
# (one-phase, two-phase, lesson-augmented variants).
#
# Signature: (task, prior_attempts) -> (calls, free_text, telemetry_dict)
AgentStep = Callable[[Any, list[EpisodeAttempt]], tuple[list[Call], str, dict[str, Any]]]


def run_episode(
    task: Any,                # tool_selection.types.Task
    triggers: tuple[FailureTrigger, ...],
    agent_step: AgentStep,
    max_retries: int = 3,
) -> Episode:
    """Run one task as a multi-turn episode.

    Loop:
      1. Ask agent_step for the next batch of calls.
      2. Execute each call against task triggers; accumulate results.
      3. If any call failed, give the model the error trace and retry.
         If all calls succeeded, end the episode.
      4. Bounded by max_retries.

    The agent_step closure decides which phase architecture / model / lesson
    augmentation is in play; this runner is agnostic.
    """
    ep = Episode(task_id=task.id)

    for attempt_idx in range(max_retries):
        calls, text, telemetry = agent_step(task, ep.attempts)
        ep.total_cost_usd += telemetry.get("cost_usd", 0.0)
        ep.total_latency_ms += telemetry.get("latency_ms", 0.0)
        ep.total_input_tokens += telemetry.get("input_tokens", 0)
        ep.total_output_tokens += telemetry.get("output_tokens", 0)

        results: list[CallResult] = []
        any_failed = False
        for call_idx, call in enumerate(calls):
            from .executor import execute_call  # local import to avoid circular

            # History visible to triggers: all calls from prior attempts +
            # calls earlier in THIS attempt. Mirrors real shell semantics
            # where `git branch x; git checkout x` works because the first
            # command already established the branch.
            history = ep.flat_calls + list(calls[:call_idx])
            res = execute_call(call, history, triggers)
            results.append(res)
            if not res.ok:
                any_failed = True
                if res.category:
                    ep.error_categories_seen.append(res.category)
                # Halt this attempt at the first error
                break

        ep.attempts.append(EpisodeAttempt(calls=calls[: len(results)], results=results, text=text))
        ep.n_attempts = attempt_idx + 1

        if not any_failed and calls:
            # No execution errors. Whether this is a TASK success (required
            # calls satisfied) is computed by the caller via scorer.score()
            # against the flat call history. We just report "no runtime errors."
            ep.succeeded = True
            return ep

    return ep
