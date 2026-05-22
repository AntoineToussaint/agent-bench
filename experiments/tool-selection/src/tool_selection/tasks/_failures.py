"""Reusable FailureTrigger definitions for the multi-turn experiment.

These are deterministic, history-aware predicates that turn a wrong tool call
into a realistic error. Error message text is copied from actual git / gh /
filesystem output so the agent sees production-realistic feedback.

Triggers are designed so the SAME failure mode recurs across multiple tasks —
this is the lever for measuring cross-episode lesson transfer.

Categories (τ²-bench-style taxonomy):
  - schema-invalid: arg structure / type / enum wrong
  - wrong-state:    state forbids the call (no upstream, branch missing, ...)
  - wrong-content:  content references something invalid (line not in diff)
  - transient:      retry might succeed unchanged
"""

from __future__ import annotations

from tool_selection.execution.state import Call, FailureTrigger


# ---------- recurring trigger: git_push without set_upstream on new branch ----------

def _push_without_upstream_when(branch_name: str):
    """Build a predicate: agent calls git_push for the first time without
    set_upstream after having created/checked-out a new branch this episode."""

    def when(call: Call, hist: list[Call]) -> bool:
        if call.tool != "git_push":
            return False
        if call.args.get("set_upstream"):
            return False
        # Episode established this branch (via checkout or branch_create)?
        established = any(
            (hc.tool == "git_checkout" and hc.args.get("ref") == branch_name)
            or (hc.tool == "git_branch_create" and hc.args.get("name") == branch_name)
            for hc in hist
        )
        if not established:
            return False
        # Already pushed once this episode? Then upstream is set; skip.
        if any(hc.tool == "git_push" for hc in hist):
            return False
        return True

    return when


def push_without_upstream(branch_name: str) -> FailureTrigger:
    return FailureTrigger(
        when=_push_without_upstream_when(branch_name),
        error_message=(
            f"fatal: The current branch {branch_name} has no upstream branch.\n"
            f"To push the current branch and set the remote as upstream, use\n"
            f"    git push --set-upstream origin {branch_name}\n"
        ),
        category="wrong-state",
        note="first push of a new branch requires set_upstream=True",
        expected_recovery=("set_upstream=True on git_push",),
    )


# ---------- checkout to a branch that doesn't exist yet (no create flag) ----------

def _checkout_missing_branch_when(branch_name: str):
    def when(call: Call, hist: list[Call]) -> bool:
        if call.tool != "git_checkout":
            return False
        if call.args.get("ref") != branch_name:
            return False
        if call.args.get("create"):
            return False
        # Did we already create this branch this episode?
        if any(
            hc.tool == "git_branch_create" and hc.args.get("name") == branch_name
            for hc in hist
        ):
            return False
        return True

    return when


def checkout_missing_branch(branch_name: str) -> FailureTrigger:
    return FailureTrigger(
        when=_checkout_missing_branch_when(branch_name),
        error_message=f"error: pathspec '{branch_name}' did not match any file(s) known to git",
        category="wrong-state",
        note="checkout to a new branch requires create=True OR a prior git_branch_create",
        expected_recovery=(
            "set create=True on git_checkout",
            "OR call git_branch_create first",
        ),
    )


# ---------- gh_pr_create before the branch has been pushed ----------

def _pr_create_before_push_when(head_branch: str | None = None):
    def when(call: Call, hist: list[Call]) -> bool:
        if call.tool != "gh_pr_create":
            return False
        # If a branch was created this episode (locally) but never pushed yet, fail
        local_branch_created = any(
            hc.tool == "git_branch_create"
            or (hc.tool == "git_checkout" and hc.args.get("create"))
            for hc in hist
        )
        if not local_branch_created:
            return False
        pushed = any(hc.tool == "git_push" for hc in hist)
        return not pushed

    return when


def pr_create_before_push() -> FailureTrigger:
    return FailureTrigger(
        when=_pr_create_before_push_when(),
        error_message=(
            "error: failed to create pull request: GraphQL: "
            "The head ref does not exist (createPullRequest)\n"
            "Hint: the branch was created locally but has not been pushed to the remote."
        ),
        category="wrong-state",
        note="cannot open a PR before pushing the head branch to the remote",
        expected_recovery=("git_push before gh_pr_create",),
    )


# ---------- gh_pr_review_submit with the wrong enum value (APPROVED vs APPROVE) ----------

def review_event_enum_mismatch() -> FailureTrigger:
    """Catches the classic mistake of using 'APPROVED' instead of 'APPROVE'."""

    def when(call: Call, hist: list[Call]) -> bool:
        if call.tool != "gh_pr_review_submit":
            return False
        event = call.args.get("event")
        # Reject common past-tense and typo variants
        bad = {"APPROVED", "REJECTED", "CHANGES_REQUESTED", "COMMENTED"}
        return event in bad

    return FailureTrigger(
        when=when,
        error_message=(
            "error: invalid event 'APPROVED' (valid values: 'APPROVE', "
            "'REQUEST_CHANGES', 'COMMENT'). Note: these are imperative, not past-tense."
        ),
        category="schema-invalid",
        note="review event uses imperative verbs (APPROVE), not past tense (APPROVED)",
        expected_recovery=("event=APPROVE (not APPROVED)",),
    )


# ---------- git_commit without prior git_add (nothing staged) ----------

def commit_without_add() -> FailureTrigger:
    def when(call: Call, hist: list[Call]) -> bool:
        if call.tool != "git_commit":
            return False
        return not any(hc.tool == "git_add" for hc in hist)

    return FailureTrigger(
        when=when,
        error_message=(
            "On branch main\nnothing to commit, working tree clean\n"
            "(use 'git add' to stage changes before committing)"
        ),
        category="wrong-state",
        note="git_commit requires git_add first — nothing is staged yet",
        expected_recovery=("call git_add before git_commit",),
    )


# ---------- bash + pytest with wrong path (THE real-world failure) ----------
#
# This is the user's canonical example: agent uses a primitive bash tool to
# invoke pytest, but composes the command with a bare filename (`pytest
# test_auth.py`) instead of a project-root-relative path (`pytest
# tests/test_auth.py`). pytest reports 'collected 0 items'. The lesson
# learned from one such failure should transfer to subsequent pytest tasks.
#
# Unlike the structured run_tests tool — where the schema enforces the rule —
# bash is just a string. The model has to COMPOSE the right invocation from
# training memory. This is where the same mistake actually recurs in
# production agentic systems.

import re as _re

_PYTEST_CMD_RE = _re.compile(r"\bpytest\s+(\S+)")


def _bash_pytest_wrong_path_when(call: Call, hist: list[Call]) -> bool:
    if call.tool != "bash":
        return False
    cmd = call.args.get("command", "")
    if not isinstance(cmd, str):
        return False
    # Find the first argument to pytest
    m = _PYTEST_CMD_RE.search(cmd)
    if not m:
        return False
    arg = m.group(1)
    # Strip pytest-specific flags
    if arg.startswith("-"):
        return False
    # Correct: starts with 'tests/' or '/...tests/...' or absolute path under tests
    if arg.startswith("tests/") or "/tests/" in arg or arg.startswith("./tests/"):
        return False
    # Wrong: bare filename, or src/ path, or anything else
    return True


def bash_pytest_wrong_verify_dir() -> FailureTrigger:
    """Project-specific convention: tests live in `verify/` not `tests/`.
    No model knows this from training. The model's natural attempts (bare
    filename or `tests/<file>`) both fail. Only `verify/<file>` succeeds.

    This is the canonical setup for phase 3 lesson-promotion experiments:
    failure recurs across episodes (model doesn't have the prior), lesson
    accumulates, eventually promotes to a derived `run_verify(test_path)`
    tool that wraps the bash invocation.
    """
    def when(call: Call, hist: list[Call]) -> bool:
        if call.tool != "bash":
            return False
        cmd = call.args.get("command", "")
        if not isinstance(cmd, str):
            return False
        m = _PYTEST_CMD_RE.search(cmd)
        if not m:
            return False
        arg = m.group(1)
        if arg.startswith("-"):
            return False
        # Only OK if the path starts with verify/
        return not (arg.startswith("verify/") or "/verify/" in arg)

    return FailureTrigger(
        when=when,
        error_message=(
            "============================= test session starts ==============================\n"
            "platform linux -- Python 3.12.0, pytest-8.0.0, pluggy-1.4.0\n"
            "rootdir: /repo\n"
            "configfile: pyproject.toml\n"
            "testpaths: verify\n\n"
            "collected 0 items\n\n"
            "============================ no tests ran in 0.02s =============================\n"
            "ERROR: pytest 'rootdir: /repo, testpaths: verify' couldn't find any tests at "
            "the given path. This project uses verify/ as its test directory (not tests/). "
            "Try the path again relative to verify/."
        ),
        category="wrong-state",
        note=(
            "This project uses verify/ as its test directory (not tests/). "
            "All pytest paths must be relative to verify/, e.g. 'verify/test_auth.py'."
        ),
        expected_recovery=(
            "prefix the pytest path with 'verify/' instead of 'tests/' or bare filename",
        ),
    )


# ---------- second failure mode: project-specific ./tools/run runner ----------
#
# This project uses ./tools/run <subcommand> for build / migrate / deploy / lint
# / seed etc. Common natural mistakes: `npm run build`, `make build`, bare
# `build`, `python build.py`. None work — only `./tools/run build` does.

_PROJECT_SUBCMDS = ("build", "migrate", "seed", "deploy", "lint", "test-all", "format")
_TOOLS_RUN_RE = _re.compile(r"\./tools/run\b")
_PROJECT_SUBCMD_RE = _re.compile(r"\b(" + "|".join(_PROJECT_SUBCMDS) + r")\b")


def _tools_run_wrong_path_when(call: Call, hist: list[Call]) -> bool:
    if call.tool != "bash":
        return False
    cmd = call.args.get("command", "")
    if not isinstance(cmd, str):
        return False
    if not _PROJECT_SUBCMD_RE.search(cmd):
        return False
    # Already using ./tools/run — fine
    if _TOOLS_RUN_RE.search(cmd):
        return False
    # Tries to use other path conventions — fails
    return True


def bash_tools_run_wrong_path() -> FailureTrigger:
    return FailureTrigger(
        when=_tools_run_wrong_path_when,
        error_message=(
            "Error: This project does NOT use npm, make, or Python entry points for ops "
            "commands. It uses a custom runner at ./tools/run.\n"
            "Try again with: ./tools/run <subcommand>\n"
            "Available subcommands: build, migrate, seed, deploy, lint, test-all, format\n"
            "Example: ./tools/run build"
        ),
        category="wrong-state",
        note=(
            "Project-specific operations runner at ./tools/run. Always invoke ops commands "
            "via ./tools/run <subcommand>, not npm/make/python."
        ),
        expected_recovery=("use ./tools/run <subcommand>",),
    )


def bash_pytest_wrong_path() -> FailureTrigger:
    return FailureTrigger(
        when=_bash_pytest_wrong_path_when,
        error_message=(
            "============================= test session starts ==============================\n"
            "platform linux -- Python 3.12.0, pytest-8.0.0, pluggy-1.4.0\n"
            "rootdir: /repo\n"
            "configfile: pyproject.toml\n"
            "testpaths: tests\n\n"
            "collected 0 items\n\n"
            "============================ no tests ran in 0.02s =============================\n"
            "ERROR: file or directory not found: did you forget the 'tests/' prefix?"
        ),
        category="wrong-state",
        note=(
            "pytest with a bare filename fails because tests are under tests/. "
            "Always invoke pytest with paths relative to the project root, "
            "e.g. 'pytest tests/test_auth.py' not 'pytest test_auth.py'."
        ),
        expected_recovery=("prefix the path with 'tests/' in the bash command",),
    )


# ---------- run_tests with wrong path (the canonical real-world failure) ----------

def _wrong_test_path_when(call: Call, hist: list[Call]) -> bool:
    if call.tool != "run_tests":
        return False
    path = call.args.get("test_path", "")
    if not isinstance(path, str):
        return False
    # Correct: starts with 'tests/' (or absolute path including tests/)
    if path.startswith("tests/") or "/tests/" in path:
        return False
    # Wrong: bare filename, or a non-tests/ prefix
    return True


def wrong_test_path() -> FailureTrigger:
    """The real engineering failure the user has seen repeatedly: agent runs
    pytest with a bare filename or wrong-prefixed path. pytest reports
    'collected 0 items' because it can't find the file.

    This trigger is independent of branch_name — fires on ANY run_tests call
    whose test_path doesn't start with 'tests/'. Lessons learned on one task
    transfer directly to the next.
    """
    return FailureTrigger(
        when=_wrong_test_path_when,
        error_message=(
            "============================= test session starts ==============================\n"
            "platform linux -- Python 3.12.0, pytest-8.0.0, pluggy-1.4.0\n"
            "rootdir: /repo\n"
            "collected 0 items\n\n"
            "============================ no tests ran in 0.02s =============================\n"
            "ERROR: file or directory not found at the given path.\n"
            "Hint: pytest paths are relative to the project root. Did you mean 'tests/<filename>'?"
        ),
        category="wrong-state",
        note=(
            "run_tests test_path must be relative to the project root and start with "
            "'tests/'. Bare filenames like 'test_auth.py' won't be found."
        ),
        expected_recovery=("prefix the test path with 'tests/'",),
    )


# ---------- git_commit_amend on a fresh branch (nothing to amend) ----------

def amend_without_prior_commit() -> FailureTrigger:
    def when(call: Call, hist: list[Call]) -> bool:
        if call.tool != "git_commit_amend":
            return False
        # If we've already made a commit this episode, amend is fine
        return not any(hc.tool == "git_commit" for hc in hist)

    return FailureTrigger(
        when=when,
        error_message=(
            "fatal: You have nothing to amend. There are no commits on this branch to modify."
        ),
        category="wrong-state",
        note="git_commit_amend requires a prior commit; on a fresh branch use git_commit",
        expected_recovery=("use git_commit instead of git_commit_amend on first commit",),
    )
