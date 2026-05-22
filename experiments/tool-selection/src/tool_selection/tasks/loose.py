"""Less-prescriptive task variants for the lesson-transfer experiment.

These are *natural-language-shaped* versions of the trigger-prone tasks
(M2/M3/H1/H2/H3). The user's intent is the same; the model has to infer
the specifics (set_upstream=True, event="APPROVE", push-before-PR, etc.)
that the original prompts spell out.

Goal: let the model err on the first attempt so the failure triggers fire,
generating real lessons that can transfer across episodes.

required_calls and failure_triggers are inherited from the originals — only
the prompt + (where helpful) the context is loosened.
"""

from __future__ import annotations

from dataclasses import replace

from tool_selection.tasks.easy import EASY
from tool_selection.tasks.hard import HARD
from tool_selection.tasks.medium import MEDIUM


def _find(task_id: str):
    for t in (*EASY, *MEDIUM, *HARD):
        if t.id == task_id:
            return t
    raise KeyError(task_id)


# ---------- M2 (branch + fix + PR) ----------

_M2 = _find("M2-branch-fix-pr")

M2_LOOSE = replace(
    _M2,
    id="M2L-branch-fix-pr-loose",
    prompt=(
        "There's a null-config crash in src/config.py — when the YAML file is missing, "
        "`config_dict['env']` throws KeyError instead of a clean error. "
        "Please fix it on a feature branch called 'fix/null-config-handling' and open a PR "
        "titled 'fix: handle missing config gracefully'."
    ),
    note=(
        "Loose variant of M2. Drops 'switch to it', 'push with upstream tracking', "
        "and the exact code-change instruction. Model must infer create=True (or "
        "use git_branch_create + checkout), set_upstream=True on first push, and "
        "the order push-before-PR — all of which fail loudly via failure_triggers "
        "if forgotten."
    ),
)


# ---------- M3 (inline review comment) ----------

_M3 = _find("M3-inline-review-comment")

M3_LOOSE = replace(
    _M3,
    id="M3L-inline-review-comment-loose",
    prompt=(
        "I reviewed PR #321 and want to leave two things:\n"
        "1. A comment on line 45 of src/parser.py — the new function does `return tokens[0]` "
        "with no length check, so an empty `tokens` will IndexError. Flag that on the diff.\n"
        "2. Then submit my overall verdict: the PR has a few issues with edge cases, so it "
        "should be marked as requesting changes. Body: 'A few issues with edge cases — see inline. "
        "Otherwise looks great.'"
    ),
    note=(
        "Loose variant of M3. Says 'requesting changes' in natural language — the model has "
        "to translate to the API enum (APPROVE / REQUEST_CHANGES / COMMENT). Natural-sounding "
        "alternatives like 'APPROVED' or 'REQUEST_CHANGES' need to be filtered by the API; "
        "the event-enum-mismatch trigger catches the past-tense forms."
    ),
)


# ---------- H1 (feature branch full flow) ----------

_H1 = _find("H1-feature-branch-full-flow")

H1_LOOSE = replace(
    _H1,
    id="H1L-feature-branch-full-flow-loose",
    prompt=(
        "Build out the dark-mode feature on a new branch called 'feature/dark-mode':\n"
        "1. Create src/themes/dark.css with the CSS in the context block.\n"
        "2. Wire it into src/themes/index.css with the @import line in the context.\n"
        "3. Add tests/test_dark_mode.py with the stub in the context.\n"
        "4. Commit the CSS file, then the index.css update, then the test stub — three commits, "
        "use 'feat(themes):' / 'feat(themes):' / 'test(themes):' message prefixes respectively.\n"
        "5. Get the branch to GitHub and open a non-draft PR titled 'Add dark mode theme' "
        "with a body summarizing the three commits."
    ),
    note=(
        "Loose variant of H1. 'Get the branch to GitHub' is natural-language for 'push it' — "
        "the model has to decide whether set_upstream is needed. Also doesn't say to push "
        "BEFORE creating the PR (the natural order). Both triggers in this task fire on the "
        "natural under-specified completion path."
    ),
)


# ---------- H2 (PR multi inline review) ----------

_H2 = _find("H2-pr-multi-inline-review")

H2_LOOSE = replace(
    _H2,
    id="H2L-pr-multi-inline-review-loose",
    prompt=(
        "Do a careful review of PR #145. Three inline issues to flag:\n"
        "1. src/auth.py line 12 — breaks when `token` is None, needs an early return.\n"
        "2. src/auth.py line 50 — should use the TOKEN_TTL_SECONDS constant from config.py "
        "instead of the hard-coded 3600.\n"
        "3. tests/test_auth.py line 8 — missing a test for the expired-token branch.\n\n"
        "Then submit my verdict: I'm asking for changes given the issues. Body: "
        "'Three issues — see inline. Otherwise the structure is good.'\n\n"
        "Then leave a top-level comment on the PR: 'Heads up — the auth module also needs "
        "unit tests for the new code path. Happy to pair on it if useful.'"
    ),
    note=(
        "Loose variant of H2. 'Asking for changes' in plain English — model has to translate "
        "to event=REQUEST_CHANGES (not APPROVED, not CHANGES_REQUESTED). The event-enum "
        "mismatch trigger catches the past-tense forms."
    ),
)


# ---------- H3 (hotfix with cross-step coupling) ----------

_H3 = _find("H3-hotfix-with-cross-step-coupling")

H3_LOOSE = replace(
    _H3,
    id="H3L-hotfix-loose",
    prompt=(
        "Issue #87 reports a race in our DB connection pool — cursors interleave under load. "
        "Hotfix it: pull main, branch as 'hotfix/db-cursor-race', apply the patch from the "
        "context (wraps cursor.execute in `with self._lock`), commit it referencing #87, "
        "get it to origin, and open a non-draft PR titled 'Hotfix: DB cursor race condition' "
        "whose body explains the fix and references both the issue (#87) and the file changed "
        "(src/db.py)."
    ),
    note=(
        "Loose variant of H3. 'Get it to origin' is the natural-language way of saying push — "
        "doesn't specify set_upstream. Failure triggers fire on push-without-upstream and "
        "PR-before-push, both of which are easy to forget."
    ),
)


LOOSE_TASKS = (M2_LOOSE, M3_LOOSE, H1_LOOSE, H2_LOOSE, H3_LOOSE)
