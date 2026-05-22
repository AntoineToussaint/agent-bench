"""Easy tasks (1-3 required tool calls).

Each task pre-surfaces enough state (file paths, diffs, current branch) in
.context that the model never needs to call a discovery tool. The scoring
target is only the *write-side* calls listed in required_calls.
"""

from __future__ import annotations

from tool_selection.matchers import Contains, Eq, Present, Regex
from tool_selection.types import RequiredCall, Task

EASY: tuple[Task, ...] = (
    Task(
        id="E1-stage-and-commit-typo",
        difficulty="small",
        prompt=(
            "I already edited README.md to fix a typo (recieve → receive). "
            "Please stage that one file and commit the change. Use a short, "
            "conventional commit message."
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "Branch: main (clean otherwise)\n"
            "`git status` (paraphrased):\n"
            "  modified:   README.md\n"
            "`git diff README.md` (paraphrased):\n"
            "  -  ...you will recieve a callback...\n"
            "  +  ...you will receive a callback...\n"
        ),
        required_calls=(
            RequiredCall(op="git.add", args={"paths": Contains("README.md")}),
            RequiredCall(
                op="git.commit",
                args={"message": Regex(r"(typo|receive|spelling)")},
            ),
        ),
        strict_order=True,
        note="Trivial baseline. Tests basic two-step ordering (add before commit).",
    ),
    Task(
        id="E2-draft-pr",
        difficulty="small",
        prompt=(
            "Open a *draft* pull request from my current branch into main. "
            "Title: 'WIP: refactor auth middleware'. Body: 'Pulling the token "
            "validation out of the request handler. Not ready for review yet — "
            "just pushing so CI can run.'"
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "Current branch: refactor/auth-middleware (already pushed)\n"
            "Default branch: main\n"
        ),
        required_calls=(
            RequiredCall(
                op="gh.pr_create",
                args={
                    "title": Contains("refactor auth"),
                    "body": Contains("token validation"),
                    "draft": Eq(True),
                },
            ),
        ),
        note="Tests that the model passes draft=true when the user explicitly says 'draft'.",
    ),
    Task(
        id="E3-read-range",
        difficulty="small",
        prompt=(
            "Show me lines 10 through 30 of pyproject.toml — I want to check "
            "the dependency block."
        ),
        context="Repo: tensorzero/playground\nFile pyproject.toml exists at the repo root.",
        required_calls=(
            RequiredCall(
                op="fs.read",
                args={
                    "path": Contains("pyproject.toml"),
                    "start_line": Eq(10),
                    "end_line": Eq(30),
                },
            ),
        ),
        note="Tests optional-arg usage (start_line/end_line). One call, no ordering.",
    ),
    Task(
        id="E4-pr-conversation-comment",
        difficulty="small",
        prompt=(
            "Leave a comment on PR #142 saying: 'Rebased onto main, all conflicts "
            "resolved. Ready for re-review.' This is a general top-level reply, "
            "not pinned to any specific line in the diff."
        ),
        context="Repo: tensorzero/playground\nPR #142 is open.",
        required_calls=(
            RequiredCall(
                op="gh.pr_comment",
                args={
                    "number": Eq(142),
                    "body": Contains("Ready for re-review"),
                },
            ),
        ),
        forbidden_ops=("gh.pr_review_comment", "gh.pr_review_submit"),
        note=(
            "Confusable test: the model must pick conversation-level comment, "
            "NOT inline review comment or review-submit. The 'not pinned to any "
            "specific line' phrasing is the disambiguator."
        ),
    ),
    Task(
        id="E5-phantom-tool-rebase",
        difficulty="small",
        prompt=(
            "Rebase my current branch onto main with an interactive rebase, "
            "squashing the last 3 commits into a single commit with message "
            "'feat: ship dark mode v1'. Then push the rebased branch."
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "Current branch: feature/dark-mode (3 commits ahead of main)\n"
            "No conflicts expected.\n"
        ),
        required_calls=(),
        forbidden_ops=(),
        note=(
            "Phantom-tool test (Tianpan / Phantom-Tool research): the catalog "
            "deliberately does NOT expose git_rebase or any squash/interactive "
            "primitive. A well-behaved model emits zero tool calls (and/or "
            "explains it cannot fulfill the request). A model that hallucinates "
            "git_rebase, git_squash, git_rebase_interactive, etc. fails this "
            "test via the hallucination-rate check. Success criterion: no "
            "hallucinated calls AND no forbidden calls. Hallucinating any tool "
            "name not in the surfaced set fails the test."
        ),
    ),
)
