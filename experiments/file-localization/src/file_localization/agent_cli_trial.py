"""Subprocess-based localization trials for production agent CLIs.

This module wraps real agent CLIs (Anthropic's `claude` and OpenAI's `codex`)
behind the standard file-localization Trial contract:

    (ModelClient, condition: str, LocalizationTask) -> RunRecord

Unlike the other trials (`llm_trial`, `turn_loop_trial`), these don't drive
the model via an API. They spawn the actual CLI in the repo's working
directory, give it the issue text, capture stdout, and parse `FILE: <path>`
lines from the response. The `client` argument is only used for `client.name`
in the record — the CLI authenticates itself.

Limitations
-----------
- **Cost / token accounting**: these CLIs typically route via a subscription
  rather than a direct API key, so per-call cost is not exposed. We leave
  `cost_usd=0.0` and `usage=TurnUsage()` zeros. Future work could parse
  Claude Code's `--output-format=json` payload (which includes a usage
  block) or codex's `--json` mode — not done here to keep parsing robust
  across CLI versions.
- **Auth**: assumes the user is already logged in to each CLI.
- **CLI flags**: both CLIs are invoked in one-shot / non-interactive mode
  (`claude -p ...`, `codex exec ...`). We set the subprocess `cwd` to the
  repo root rather than relying on a CLI-specific `--cwd` flag, which is
  more portable across CLI versions.

The trial calls `repo_view_for(task)` to resolve a `RepoView`. We require
it to have a `.root` attribute pointing at the on-disk repo (e.g.
`LocalRepoView` from `turn_loop_trial`). For a future SWE-Bench RepoView
that clones a repo, `.root` would point at the clone.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from agent_eval.types import ModelClient, RunRecord, TurnUsage

from file_localization.contract import LocalizationTask, score


# ---------- prompts ----------


USER_TEMPLATE = """\
## Repository
{repo} @ {commit}

## Issue
{issue}

## Task
Identify ALL files that must be edited (source + tests) to fix this issue. \
Explore the repo as needed. When ready, output exactly one block of

  FILE: <path>

lines (one path per line, most important first). Do not add prose after \
that block — the grader parses only `FILE:` lines.\
"""


_FILE_LINE = re.compile(r"^\s*FILE:\s*(\S+)\s*$", re.MULTILINE)


def _parse_files(text: str) -> list[str]:
    """Extract ranked file paths from the CLI's stdout. Dedup, preserve order."""
    paths = _FILE_LINE.findall(text or "")
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


# ---------- detection ----------


def is_available(cli_path: str) -> bool:
    """Return True iff the CLI binary is on PATH (or is an existing file path)."""
    if not cli_path:
        return False
    # If it looks like a path (contains a separator), check the filesystem.
    if "/" in cli_path or "\\" in cli_path:
        p = Path(cli_path)
        return p.exists() and p.is_file()
    # Otherwise resolve against $PATH.
    return shutil.which(cli_path) is not None


# ---------- subprocess driver ----------


def _run_cli(
    argv: list[str],
    cwd: Path,
    timeout: int,
) -> tuple[str, str, str | None]:
    """Invoke the CLI subprocess.

    Returns (stdout, stderr, error). `error` is None on success, a short
    tag on failure (e.g. `"cli_timeout"`, `"cli_not_found"`, `"cli_failed"`).
    """
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        return (e.stdout or "" if isinstance(e.stdout, str) else "",
                e.stderr or "" if isinstance(e.stderr, str) else "",
                "cli_timeout")
    except FileNotFoundError:
        return ("", "", "cli_not_found")
    except OSError as e:
        return ("", str(e), f"cli_oserror: {e}")

    err: str | None = None
    if proc.returncode != 0:
        err = f"cli_failed: exit={proc.returncode}"
    return proc.stdout or "", proc.stderr or "", err


# ---------- factory: shared ----------


def _build_user_text(task: LocalizationTask) -> str:
    return USER_TEMPLATE.format(
        repo=task.repo,
        commit=task.base_commit[:12] if task.base_commit else "unknown",
        issue=task.issue_text,
    )


def _resolve_root(repo_view) -> Path:
    """Pull `.root` off the RepoView. Must be a real on-disk directory."""
    root = getattr(repo_view, "root", None)
    if root is None:
        raise TypeError(
            "agent_cli_trial requires the RepoView to expose a `.root` "
            "Path attribute (e.g. LocalRepoView). Got: %r" % (repo_view,)
        )
    return Path(root)


def _make_trial(
    *,
    build_argv: Callable[[str], list[str]],
    repo_view_for: Callable[[LocalizationTask], object],
    timeout: int,
    fp_penalty: float,
    top_k: int | None,
):
    """Internal: returns a Trial that invokes `build_argv(prompt)` as a subprocess."""

    def trial(client: ModelClient, condition: str, task: LocalizationTask) -> RunRecord:
        repo_view = repo_view_for(task)
        cwd = _resolve_root(repo_view)

        prompt = _build_user_text(task)
        argv = build_argv(prompt)

        t0 = time.monotonic()
        stdout, stderr, err = _run_cli(argv, cwd=cwd, timeout=timeout)
        latency = time.monotonic() - t0

        predicted = _parse_files(stdout)
        s = score(predicted, task.gold_all, k=top_k, fp_penalty=fp_penalty)

        # If we errored, force passed=False regardless of what we parsed.
        passed = s.passed and err is None

        return RunRecord(
            task_id=task.task_id,
            model=client.name if client is not None else "unknown",
            condition=condition,
            passed=passed,
            turns=1,
            tool_calls=0,
            invalid_tool_calls=0,
            usage=TurnUsage(),
            latency_seconds=latency,
            cost_usd=0.0,
            stdout=stdout,
            stderr=stderr,
            error=err,
            extra={
                **s.as_extra(),
                "submitted": predicted,
                "cli_argv": argv,
            },
        )

    return trial


# ---------- Claude Code ----------


def make_claude_code_trial(
    repo_view_for: Callable[[LocalizationTask], object],
    *,
    cli_path: str = "claude",
    timeout: int = 120,
    fp_penalty: float = 0.05,
    top_k: int | None = None,
    allowed_tools: list[str] | None = None,
    disallowed_tools: list[str] | None = None,
):
    """Factory: returns a Trial that drives Anthropic's `claude` CLI.

    The CLI is spawned in non-interactive mode (`claude -p "<prompt>"`)
    with `cwd` set to the repo root. Cost/token usage is NOT captured.

    Args:
        repo_view_for: callable mapping a task to a RepoView whose `.root`
            is the on-disk repo path.
        cli_path: path or PATH-resolvable name of the claude binary.
        timeout: subprocess timeout in seconds.
        fp_penalty: scorer's false-positive penalty.
        top_k: if set, only the top-k parsed files are scored.
        allowed_tools: when set, restrict Claude Code to this tool set via
            `--allowed-tools "Tool1 Tool2 ..."`. Useful for apples-to-apples
            comparisons with the DIY turn-loop. To match the DIY surface
            (list_files / grep / view_file) pass `["Read", "Grep", "Glob"]`.
        disallowed_tools: counterpart to allowed_tools. Pass to block
            specific tools like `["Bash", "Edit", "Write"]`.
    """

    extra_flags: list[str] = []
    if allowed_tools:
        extra_flags += ["--allowed-tools", " ".join(allowed_tools)]
    if disallowed_tools:
        extra_flags += ["--disallowed-tools", " ".join(disallowed_tools)]

    def build_argv(prompt: str) -> list[str]:
        # `-p / --print`: one-shot non-interactive print mode.
        # `--permission-mode bypassPermissions`: don't prompt during a
        # benchmark run.
        return [
            cli_path,
            "-p",
            prompt,
            "--permission-mode",
            "bypassPermissions",
            *extra_flags,
        ]

    return _make_trial(
        build_argv=build_argv,
        repo_view_for=repo_view_for,
        timeout=timeout,
        fp_penalty=fp_penalty,
        top_k=top_k,
    )


# Pre-set "match the DIY turn-loop surface" — Read=view_file, Grep=grep,
# Glob=list_files-equivalent. No Bash, no edits, no web.
CLAUDE_CODE_READONLY_TOOLS: list[str] = ["Read", "Grep", "Glob"]


# ---------- OpenAI Codex ----------


def make_codex_trial(
    repo_view_for: Callable[[LocalizationTask], object],
    *,
    cli_path: str = "codex",
    timeout: int = 120,
    fp_penalty: float = 0.05,
    top_k: int | None = None,
):
    """Factory: returns a Trial that drives OpenAI's `codex` CLI.

    The CLI is spawned in non-interactive mode (`codex exec "<prompt>"`)
    with `cwd` set to the repo root. Cost/token usage is NOT captured;
    Codex routes via the user's ChatGPT account and doesn't surface
    a per-call cost in stdout reliably. Recorded `usage` and `cost_usd`
    are zeros.

    Args:
        repo_view_for: callable mapping a task to a RepoView whose `.root`
            is the on-disk repo path.
        cli_path: path or PATH-resolvable name of the codex binary.
        timeout: subprocess timeout in seconds.
        fp_penalty: scorer's false-positive penalty.
        top_k: if set, only the top-k parsed files are scored.
    """

    def build_argv(prompt: str) -> list[str]:
        # `exec`: non-interactive, single-shot completion. The prompt is
        # the last positional arg.
        return [cli_path, "exec", prompt]

    return _make_trial(
        build_argv=build_argv,
        repo_view_for=repo_view_for,
        timeout=timeout,
        fp_penalty=fp_penalty,
        top_k=top_k,
    )
