"""Adapter: SWE-Bench dataset row → LocalizationTask.

The existing `data.Task` dataclass in this experiment carries the raw
SWE-Bench fields (patch text, test_patch text). LocalizationTask wants
the *parsed* gold file sets, ready for scoring. This module bridges them.

Usage:
    from file_localization.data import load_tasks
    from file_localization.swebench_adapter import to_localization_tasks

    raw = load_tasks("verified", split="test")
    tasks = to_localization_tasks(raw)
    # now `tasks: list[LocalizationTask]` is ready for an agent_eval.Sweep
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from file_localization.contract import LocalizationTask
from file_localization.data import Task as RawTask


_DIFF_PATH = re.compile(r"^diff --git a/(\S+) b/", re.MULTILINE)
_ADDED_FILE = re.compile(r"^\+\+\+ b/(\S+)", re.MULTILINE)


def files_in_patch(patch_text: str) -> frozenset[str]:
    """Extract the set of file paths a unified-diff patch modifies."""
    if not patch_text:
        return frozenset()
    paths: set[str] = set()
    paths.update(_DIFF_PATH.findall(patch_text))
    # Fall back to +++ lines if no diff --git headers (rare but happens)
    if not paths:
        paths.update(_ADDED_FILE.findall(patch_text))
    return frozenset(paths)


def to_localization_task(
    raw: RawTask, repo_file_list: tuple[str, ...] | None = None
) -> LocalizationTask:
    """Adapt one SWE-Bench row to a LocalizationTask."""
    return LocalizationTask(
        instance_id=raw.instance_id,
        issue_text=raw.problem_statement,
        repo=raw.repo,
        base_commit=raw.base_commit,
        gold_edit_files=files_in_patch(raw.patch),
        gold_test_files=files_in_patch(raw.test_patch),
        repo_file_list=repo_file_list,
    )


def to_localization_tasks(
    raws: Iterable[RawTask],
    file_lists: dict[str, tuple[str, ...]] | None = None,
) -> list[LocalizationTask]:
    """Bulk adapt SWE-Bench rows.

    Args:
        raws: SWE-Bench Task objects (from `data.load_tasks`)
        file_lists: optional map instance_id -> repo file listing. If
            absent for a given task, that task's `repo_file_list` is None
            and the LLM trial will fall back to whatever defaults the
            prompt has (typically "(not provided)").
    """
    file_lists = file_lists or {}
    return [
        to_localization_task(r, file_lists.get(r.instance_id))
        for r in raws
    ]
