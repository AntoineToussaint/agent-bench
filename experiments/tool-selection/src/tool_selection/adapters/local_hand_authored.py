"""Adapter for the 16 hand-authored tasks shipped in `tool_selection/tasks/`.

Wraps the existing collections (EASY, MEDIUM, HARD, BASH_TASKS, PYTEST_TASKS,
RUNNER_TASKS, VERIFY_TASKS) under standard accessor functions that match the
adapter pattern used across `agent-bench`. The underlying lists are not moved
— this module is a thin adapter shim.
"""

from __future__ import annotations

from tool_selection.tasks import (
    BASH_TASKS,
    EASY,
    HARD,
    MEDIUM,
    PYTEST_TASKS,
    RUNNER_TASKS,
    VERIFY_TASKS,
)
from tool_selection.types import Task


def tasks_by_difficulty() -> dict[str, tuple[Task, ...]]:
    """Return the canonical difficulty bands."""
    return {"easy": EASY, "medium": MEDIUM, "hard": HARD}


def tasks_by_failure_mode() -> dict[str, tuple[Task, ...]]:
    """Return the failure-mode-tagged bundles."""
    return {
        "bash": BASH_TASKS,
        "pytest": PYTEST_TASKS,
        "runner": RUNNER_TASKS,
        "verify": VERIFY_TASKS,
    }


def all_tasks() -> tuple[Task, ...]:
    """Every hand-authored task in this experiment, deduped by task_id."""
    seen: set[str] = set()
    out: list[Task] = []
    for band in (EASY, MEDIUM, HARD):
        for t in band:
            if t.id not in seen:
                seen.add(t.id)
                out.append(t)
    return tuple(out)
