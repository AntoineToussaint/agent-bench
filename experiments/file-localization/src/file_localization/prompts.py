"""Localization prompt templates, keyed by task class.

Each task class gets a class-specific intro + workflow hint that frames
WHAT KIND of files the model should look for:

  bug_fix     — code that has the bug + tests that should regress
  feature     — code where the new feature lives + tests to add
  refactor    — code being refactored + tests covering its behavior
  performance — hot paths + benchmark/test files
  unknown     — generic fallback

The intro is concatenated with the base instruction (LOCALIZATION ONLY,
budget hint, output format) so every prompt has the same scoring posture
but the content focus differs.

This is shared between turn_loop_trial.py, turn_loop_structured_trial.py,
and llm_trial.py — define once, render thrice.
"""

from __future__ import annotations

from file_localization.contract import TaskClass


# --- per-task-class focus blurbs ----------------------------------------


_TASK_CLASS_FOCUS: dict[TaskClass, str] = {
    "bug_fix": (
        "This issue describes a BUG. Look for:\n"
        "  - The function/class the issue names — that's almost always the "
        "edit target.\n"
        "  - Files mentioned by name or path in the issue / traceback.\n"
        "  - Don't go reading every dependency. Surface code first."
    ),
    "feature": (
        "This issue describes a FEATURE REQUEST. Look for:\n"
        "  - Existing similar features — they show you the right module / "
        "pattern to copy.\n"
        "  - The dispatch/route/registry/config file where the new feature "
        "would be wired in.\n"
        "  - If the feature spans layers (API + storage), name files at each "
        "layer."
    ),
    "refactor": (
        "This issue describes a REFACTOR. Look for:\n"
        "  - The named symbol(s) being refactored.\n"
        "  - Every CALL SITE — refactors are graph-traversal problems, the "
        "edit set is usually larger than 1 file."
    ),
    "performance": (
        "This issue describes a PERFORMANCE problem. Look for:\n"
        "  - The hot path code (algorithm, loop, allocation site) the issue "
        "names.\n"
        "  - Configuration / cache code if the issue suggests a flag/setting."
    ),
    "unknown": (
        "Classify the issue yourself before exploring: is it a bug, a "
        "feature, a refactor, or a perf issue? Then look for the kind of "
        "files that class typically touches."
    ),
}


# --- base instruction (same scoring posture across classes) -------------


_BASE_INSTRUCTION = """\
Your job is LOCALIZATION ONLY: identify which SOURCE files need editing \
to fix the given issue. You are NOT writing the fix, NOT analyzing root \
causes in detail, and NOT predicting which test files would be updated.

Budget: target 3-6 tool calls TOTAL before submitting. Each extra \
exploration call costs you tokens with diminishing return — once you \
have 1-3 plausible source files, SUBMIT. You can be wrong; you cannot \
retract.

Score is based on SOURCE files only — files under `tests/` or named \
`test_*.py` are tolerated but neither rewarded nor penalized. Don't \
spend budget hunting for them.\
"""


# --- public API ---------------------------------------------------------


def system_prompt_for(
    task_class: TaskClass,
    *,
    extra_tools_block: str = "",
) -> str:
    """Compose a system prompt for the given task class.

    `extra_tools_block` is appended verbatim (e.g. for the tool_use loop
    we slot in the workflow/tools cheatsheet; for the structured loop
    we slot in the JSON-op cheatsheet)."""
    focus = _TASK_CLASS_FOCUS.get(task_class, _TASK_CLASS_FOCUS["unknown"])
    parts = [_BASE_INSTRUCTION, "", "## Task class", focus]
    if extra_tools_block:
        parts += ["", extra_tools_block]
    return "\n".join(parts)


def user_message(repo: str, commit: str, issue_text: str) -> str:
    """Standard user-message template across all localization trials."""
    return (
        f"## Repository\n{repo} @ {commit[:12] if commit else 'unknown'}\n\n"
        f"## Issue\n{issue_text}"
    )
