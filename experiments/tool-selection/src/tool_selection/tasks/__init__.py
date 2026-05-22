"""Hand-authored tasks for the one-shot tool-selection benchmark."""

from __future__ import annotations

from tool_selection.operations import op as _op
from tool_selection.types import Task

from .easy import EASY
from .hard import HARD
from .medium import MEDIUM
from .bash_tasks import BASH_TASKS
from .pytest_tasks import PYTEST_TASKS
from .runner_tasks import RUNNER_TASKS
from .verify_tasks import VERIFY_TASKS


def _expected_toolboxes(task: Task) -> tuple[str, ...]:
    """Derive ground-truth toolbox set from a task's required_calls."""
    seen: list[str] = []
    for rc in task.required_calls:
        toolbox = rc.op.split(".", 1)[0]
        # 'fs' -> 'filesystem', 'gh' -> 'github', 'git' stays
        toolbox = {"fs": "filesystem", "gh": "github"}.get(toolbox, toolbox)
        if toolbox not in seen:
            seen.append(toolbox)
    return tuple(seen)


def _populate_expected_toolboxes(tasks: tuple[Task, ...]) -> tuple[Task, ...]:
    from dataclasses import replace

    out: list[Task] = []
    for t in tasks:
        if t.expected_toolboxes:
            out.append(t)
        else:
            out.append(replace(t, expected_toolboxes=_expected_toolboxes(t)))
    return tuple(out)


def _validate(tasks: tuple[Task, ...]) -> None:
    """Sanity-check that every op referenced by a task exists."""
    ids = set()
    for t in tasks:
        if t.id in ids:
            raise ValueError(f"Duplicate task id: {t.id}")
        ids.add(t.id)
        for rc in t.required_calls:
            _op(rc.op)  # raises KeyError if unknown
        for forbidden in t.forbidden_ops:
            _op(forbidden)


ALL_TASKS: tuple[Task, ...] = _populate_expected_toolboxes(EASY + MEDIUM + HARD + PYTEST_TASKS + BASH_TASKS + VERIFY_TASKS + RUNNER_TASKS)
_validate(ALL_TASKS)


def by_difficulty(difficulty: str) -> tuple[Task, ...]:
    return tuple(t for t in ALL_TASKS if t.difficulty == difficulty)


def by_id(task_id: str) -> Task:
    for t in ALL_TASKS:
        if t.id == task_id:
            return t
    raise KeyError(f"Unknown task id: {task_id}")


__all__ = ["ALL_TASKS", "EASY", "MEDIUM", "HARD", "by_difficulty", "by_id"]
