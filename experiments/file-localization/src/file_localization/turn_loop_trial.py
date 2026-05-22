"""Turn-loop trial for file localization.

The model explores a repo via tools and submits a ranked file list.
Trial signature matches `agent_eval.Sweep`:
    (ModelClient, condition, LocalizationTask) -> RunRecord

Tools the model gets:
  - list_files(path?)           → ranked list of paths under `path`
  - grep(pattern, glob?, limit?) → fast content search, returns hits with
                                    path:line:snippet
  - view_file(path, line_range?) → file contents (optionally a range)
  - done(files=[...])            → final ranked answer; loop exits

The loop honors the same escape valves as code-editing's agent runner
(max_turns, max_consecutive_errors, max_no_progress_turns).
"""

from __future__ import annotations

import fnmatch
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from agent_eval.types import (
    AssistantMessage,
    ModelClient,
    RunRecord,
    ToolCall,
    ToolResult,
    Transcript,
)

from file_localization.contract import LocalizationTask, score


# ============ RepoView abstraction ============


class RepoView(Protocol):
    """Read-only view of a repo at a specific commit/state."""

    def list_files(self, subpath: str = "") -> list[str]: ...
    def grep(self, pattern: str, glob: str = "", limit: int = 50) -> list[tuple[str, int, str]]: ...
    def view_file(self, path: str, line_range: tuple[int, int] | None = None) -> str: ...


@dataclass
class LocalRepoView:
    """A RepoView backed by a local directory."""

    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()

    def _safe(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError(f"path escapes repo: {rel}")
        return p

    def list_files(self, subpath: str = "") -> list[str]:
        base = self._safe(subpath) if subpath else self.root
        if not base.exists() or not base.is_dir():
            return []
        out: list[str] = []
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            parts = p.relative_to(self.root).parts
            if any(seg in {".git", "__pycache__", "node_modules", ".venv"} for seg in parts):
                continue
            out.append(str(p.relative_to(self.root)))
        return sorted(out)

    def grep(self, pattern: str, glob: str = "", limit: int = 50) -> list[tuple[str, int, str]]:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"bad regex {pattern!r}: {e}") from e
        hits: list[tuple[str, int, str]] = []
        for rel in self.list_files():
            if glob and not fnmatch.fnmatch(rel, glob):
                continue
            try:
                text = (self.root / rel).read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if rx.search(line):
                    snippet = line[:200].rstrip()
                    hits.append((rel, i, snippet))
                    if len(hits) >= limit:
                        return hits
        return hits

    def view_file(self, path: str, line_range: tuple[int, int] | None = None) -> str:
        p = self._safe(path)
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        if line_range is None:
            return text
        lines = text.splitlines()
        start, end = line_range
        return "\n".join(lines[max(0, start - 1) : min(len(lines), end)])


# ============ tool schemas ============


TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": (
            "List every file under the given subpath (default: repo root). "
            "Returns one path per line, relative to the repo root. Excludes "
            ".git, __pycache__, node_modules, .venv."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Subdirectory to list. Defaults to root.", "default": ""}
            },
            "required": [],
        },
    },
    {
        "name": "grep",
        "description": (
            "Search file contents for a regex pattern. Returns up to `limit` "
            "matches as `path:line: snippet`. Optionally filter by a glob over "
            "the path (e.g. `*.py`, `src/**/*.ts`)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python regex pattern."},
                "glob": {"type": "string", "description": "Optional path glob filter.", "default": ""},
                "limit": {"type": "integer", "description": "Max matches.", "default": 50},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "view_file",
        "description": (
            "Read a file's contents. Optionally pass `line_range` as [start, end] "
            "(1-indexed, inclusive) to get only that slice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "line_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "[start, end] (1-indexed, inclusive). Optional.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "done",
        "description": (
            "Submit your final answer: the ranked list of files needed to "
            "investigate and fix the issue. Most important first. After this "
            "call, the loop exits — you cannot edit or retract."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ranked file paths, most important first.",
                },
            },
            "required": ["files"],
        },
    },
]


SYSTEM_PROMPT = """\
You investigate a code repository to identify the files that must be edited \
(and the tests that must be added/updated) to fix a given GitHub issue.

You have these tools:
  - list_files(path?)         → list paths
  - grep(pattern, glob?)      → search file contents
  - view_file(path, range?)   → read file (or a slice)
  - done(files=[...])         → submit final ranked list and exit

Work like an engineer: skim the repo structure, grep for relevant symbols, \
read the most promising files, then call `done` with a ranked list (highest \
relevance first). Include both source files (where the bug lives) and test \
files (where regression tests would go).

Be selective — only include files that genuinely matter. Spurious files hurt \
your score.\
"""


USER_TEMPLATE = """\
## Repository
{repo} @ {commit}

## Issue
{issue}

Start by exploring the repo. When you've identified the files, call `done` \
with the ranked list.\
"""


# ============ trial loop ============


@dataclass
class _Limits:
    max_turns: int = 12
    max_consecutive_errors: int = 3
    max_no_progress_turns: int = 4


def _apply(call: ToolCall, repo: RepoView) -> ToolResult:
    """Apply one tool call against the repo view."""
    args = call.arguments
    try:
        if call.name == "list_files":
            paths = repo.list_files(args.get("path", "") or "")
            content = "\n".join(paths) if paths else "(empty)"
            return ToolResult(call.call_id, "ok", content[:8000])
        if call.name == "grep":
            pattern = args.get("pattern")
            if not pattern:
                return ToolResult(call.call_id, "error", "missing `pattern`")
            hits = repo.grep(
                pattern, glob=args.get("glob", "") or "", limit=int(args.get("limit", 50))
            )
            if not hits:
                return ToolResult(call.call_id, "ok", "(no matches)")
            content = "\n".join(f"{p}:{ln}: {snip}" for p, ln, snip in hits)
            return ToolResult(call.call_id, "ok", content[:8000])
        if call.name == "view_file":
            path = args.get("path")
            if not path:
                return ToolResult(call.call_id, "error", "missing `path`")
            line_range = args.get("line_range")
            rng = tuple(line_range) if line_range else None
            try:
                text = repo.view_file(path, rng)
            except FileNotFoundError:
                return ToolResult(call.call_id, "error", f"file not found: {path}")
            numbered = "\n".join(
                f"{i + 1:>5}: {line}" for i, line in enumerate(text.splitlines())
            )
            return ToolResult(call.call_id, "ok", numbered[:8000])
        if call.name == "done":
            files = args.get("files") or []
            if not isinstance(files, list):
                return ToolResult(call.call_id, "error", "`files` must be a list")
            return ToolResult(call.call_id, "ok", f"accepted {len(files)} file(s)")
        return ToolResult(call.call_id, "error", f"unknown tool: {call.name}")
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))


def _snapshot(submitted: list[str]) -> tuple[str, ...]:
    """Detect "no-progress" turns by tracking the submitted file list."""
    return tuple(submitted)


def make_turn_loop_trial(
    repo_view_for: Callable[[LocalizationTask], RepoView],
    *,
    limits: _Limits | None = None,
    fp_penalty: float = 0.05,
    top_k: int | None = None,
):
    """Factory: returns a Trial that uses an agent loop against `repo_view_for(task)`.

    Args:
        repo_view_for: callable that resolves a LocalizationTask to a RepoView.
            For SWE-Bench tasks this clones the repo at base_commit; for tests
            it can return a LocalRepoView over a tmp_path.
        limits: turn / error / no-progress caps. Defaults are conservative.
        fp_penalty: scorer's false-positive penalty.
        top_k: if set, only the top-k files in the final `done(files=...)` are scored.
    """
    limits = limits or _Limits()

    def trial(client: ModelClient, condition: str, task: LocalizationTask) -> RunRecord:
        repo = repo_view_for(task)
        transcript = Transcript(system=SYSTEM_PROMPT)
        client.reset(SYSTEM_PROMPT)
        user_text = USER_TEMPLATE.format(
            repo=task.repo,
            commit=task.base_commit[:12] if task.base_commit else "unknown",
            issue=task.issue_text,
        )
        client.add_user_text(user_text)
        transcript.add_user_text(user_text)

        submitted: list[str] = []
        turns = 0
        tool_calls = 0
        invalid = 0
        consecutive_errors = 0
        no_progress_turns = 0
        last_snapshot: tuple[str, ...] | None = None
        error: str | None = None
        done_flag = False

        t0 = time.monotonic()
        in_tok = out_tok = cache_r = cache_w = 0

        while turns < limits.max_turns and not done_flag:
            turns += 1
            try:
                msg: AssistantMessage = client.step(TOOLS)
            except Exception as e:  # noqa: BLE001
                error = f"model_error: {type(e).__name__}: {e}"
                break
            transcript.add_assistant(msg)
            in_tok += msg.usage.input_tokens
            out_tok += msg.usage.output_tokens
            cache_r += msg.usage.cache_read_tokens
            cache_w += msg.usage.cache_creation_tokens

            if not msg.tool_calls:
                client.add_user_text(
                    "You did not call any tools. Use `list_files`, `grep`, or "
                    "`view_file` to explore, then call `done(files=[...])` when ready."
                )
                transcript.add_user_text("(nudge: no tool calls)")
                continue

            results: list[ToolResult] = []
            turn_all_errors = True
            for tc in msg.tool_calls:
                tool_calls += 1
                res = _apply(tc, repo)
                if res.status == "ok":
                    turn_all_errors = False
                else:
                    invalid += 1
                results.append(res)
                if tc.name == "done":
                    files = tc.arguments.get("files") or []
                    if isinstance(files, list):
                        submitted = [str(f) for f in files]
                    done_flag = True
            client.add_tool_results(results)
            transcript.add_tool_results(results)

            # escape valves
            if turn_all_errors:
                consecutive_errors += 1
            else:
                consecutive_errors = 0
            if consecutive_errors >= limits.max_consecutive_errors:
                error = f"aborted: {consecutive_errors} consecutive error turns"
                break

            snap = _snapshot(submitted)
            if snap == last_snapshot:
                no_progress_turns += 1
            else:
                no_progress_turns = 0
            last_snapshot = snap
            if not done_flag and no_progress_turns >= limits.max_no_progress_turns:
                error = f"aborted: {no_progress_turns} no-progress turns"
                break

        latency = time.monotonic() - t0
        s = score(submitted, task.gold_all, k=top_k, fp_penalty=fp_penalty)

        from agent_eval.types import TurnUsage as _TU

        return RunRecord(
            task_id=task.task_id,
            model=client.name,
            condition=condition,
            passed=s.passed,
            turns=turns,
            tool_calls=tool_calls,
            invalid_tool_calls=invalid,
            usage=_TU(
                input_tokens=in_tok,
                output_tokens=out_tok,
                cache_read_tokens=cache_r,
                cache_creation_tokens=cache_w,
            ),
            latency_seconds=latency,
            error=error,
            extra={
                **s.as_extra(),
                "submitted": submitted,
                "done_called": done_flag,
            },
        )

    return trial
