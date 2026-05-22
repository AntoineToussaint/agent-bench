"""Core data types for multi-turn execution.

Deliberately no WorldState simulator: tasks own their failure logic via
deterministic `FailureTrigger` predicates over the in-flight call and the
agent's history within this episode. This keeps tasks self-contained and
avoids building a fake git / github runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Call:
    """A single tool_use block emitted by the agent."""

    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class FailureTrigger:
    """Deterministic per-task failure-injection predicate.

    Carried by Task. When the executor runs a Call, it checks each trigger:
    if `when(call, prior_calls_this_episode)` returns True, the call returns
    `error_message` instead of the success placeholder.

    Categories follow the τ²-bench-style taxonomy:
      - schema-invalid: arg structure / type / enum wrong
      - wrong-state:    call would succeed except current state forbids it
                        (e.g. branch doesn't exist, no upstream configured)
      - wrong-content:  call's content references something invalid
                        (e.g. line outside diff, label not in repo)
      - transient:      retry might succeed unchanged (rate limits, network)

    `note` is for human reading — what the model should learn.
    """

    when: Callable[[Call, list[Call]], bool]
    """Predicate. Signature: (this_call, prior_calls_this_episode) -> should_fail."""

    error_message: str
    """Error string returned to the agent as tool_result. Should be realistic
    (copied from real tool error text where possible)."""

    category: str
    """One of: schema-invalid, wrong-state, wrong-content, transient."""

    note: str = ""
    """Human-readable hint about what the agent should learn from this failure."""

    expected_recovery: tuple[str, ...] = ()
    """Optional: the pattern of args/calls that would resolve the failure on
    retry, used by analysis (not by execution). Free-text description, e.g.
    'add set_upstream=True' or 'call git_branch_create first'."""


@dataclass
class CallResult:
    """Result of executing one Call against task failure triggers."""

    ok: bool
    output: str = ""
    error: str = ""
    triggered_by: str = ""
    """If failed, the `note` of the FailureTrigger that fired."""
    category: str = ""
    """If failed, the category of the FailureTrigger that fired."""
