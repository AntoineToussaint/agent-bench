"""Offline tests for the agent-eval-core Trial wrapper.

Doesn't hit any LLM. Uses a stub Approach + Phase that return canned results,
verifies make_trial() converts (CallTrace, ScoreCard) -> RunRecord correctly.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_eval.protocols import NativeToolUseBackend
from agent_eval.types import ModelClient, ModelHandle, ToolResult
from tool_selection.adapters import all_tasks
from tool_selection.approaches.base import Approach, ApproachResult
from tool_selection.catalogs import get_catalog
from tool_selection.phases.base import Phase, PhaseResult
from tool_selection.trial import make_trial
from tool_selection.types import Task, Tool


# --- stubs ---


class _StubClient(ModelClient):
    """A ModelClient that the trial only reads `.name` from."""

    def __init__(self, name: str) -> None:
        self.name = name

    def reset(self, system: str) -> None: ...
    def add_user_text(self, text: str) -> None: ...
    def add_tool_results(self, results: list[ToolResult]) -> None: ...
    def step(self, tools, tool_choice=None): ...  # noqa: ANN001


def _handle(name: str) -> ModelHandle:
    """Wrap a stub in a ModelHandle. The phase stub here ignores the
    handle entirely, so any backend works."""
    return ModelHandle(client=_StubClient(name), backend=NativeToolUseBackend())


@dataclass
class _StubApproach(Approach):
    id: str = "stub-approach"

    def surface(self, task: Task, catalog) -> ApproachResult:  # noqa: ANN001
        return ApproachResult(surfaced_tools=[], pre_steps=[])


@dataclass
class _StubPhase(Phase):
    id: str = "stub-phase"
    canned_calls: list[dict] | None = None
    success_text: str = ""
    error: str | None = None

    def execute(
        self,
        task: Task,
        surfaced_tools: list[Tool],
        model: str,
        handle: ModelHandle | None = None,
    ) -> PhaseResult:
        return PhaseResult(
            final_calls=self.canned_calls or [],
            final_text=self.success_text,
            steps=[],
            error=self.error,
        )


# --- tests ---


def test_trial_returns_runrecord_with_metrics() -> None:
    task = all_tasks()[0]
    catalog = get_catalog("narrow")
    trial = make_trial(_StubApproach(), catalog, _StubPhase())
    rec = trial(_handle("claude-haiku-4-5"), "test-condition", task)
    # Basic shape
    assert rec.task_id == task.id
    assert rec.model == "claude-haiku-4-5"
    assert rec.condition == "test-condition"
    assert rec.turns == 1
    # Scoring metrics live in extra
    assert "selection_matched" in rec.extra
    assert "required_total" in rec.extra
    assert "approach_id" in rec.extra
    assert rec.extra["surfaced_count"] == 0
    assert rec.extra["n_calls"] == 0


def test_trial_catches_internal_error() -> None:
    task = all_tasks()[0]

    class _Boom(Phase):
        id = "boom"
        def execute(self, *args, **kwargs):
            raise RuntimeError("phase blew up")

    trial = make_trial(_StubApproach(), get_catalog("narrow"), _Boom())
    rec = trial(_handle("claude-haiku-4-5"), "boom-condition", task)
    assert not rec.passed
    assert rec.error is not None
    assert "RuntimeError" in rec.error or "phase blew up" in rec.error


def test_trial_propagates_tool_call_counts() -> None:
    task = all_tasks()[0]
    canned = [
        {"name": "fs.read", "input": {"path": "foo"}},
        {"name": "git.status", "input": {}},
        {"name": "phantom_tool", "input": {}},  # not in catalog
    ]
    trial = make_trial(_StubApproach(), get_catalog("narrow"), _StubPhase(canned_calls=canned))
    rec = trial(_handle("claude-sonnet-4-6"), "cond", task)
    assert rec.tool_calls == 3
    assert rec.extra["n_calls"] == 3
