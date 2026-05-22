"""Generic file-localization tool surface.

Both the tool_use turn-loop and the structured turn-loop (and any future
trial — one-shot tool_use, agent with shell, etc.) share this single set
of operations on a `RepoView`.

  - TOOL_SCHEMAS: list[dict] in Anthropic tool-use shape
    (`{name, description, input_schema}`). Pass to `ModelClient.step(tools=...)`.

  - OP_DESCRIPTIONS: a markdown block describing the same ops for use in
    a system prompt where there's no tool_use API (the structured loop).
    The shape stays in sync with TOOL_SCHEMAS — define once, render twice.

  - apply_tool_call(call, repo) -> ToolResult: the executor. Takes a
    provider-agnostic ToolCall and a RepoView, runs the op, returns a
    ToolResult. Same code path whether the call came from a tool_use
    block or from a parsed structured-output action.

  - TOOL_NAMES, READ_ONLY_TOOLS: sets for harness-side checks
    (e.g. "this turn made a write-attempt").

The `done` tool is included here because it's part of the same interface
contract; the harness recognizes it specifically and exits the loop.
"""

from __future__ import annotations

from typing import Any

from agent_eval.types import ToolCall, ToolResult

from file_localization.repo_view import RepoView


# --- schemas (for tool_use API) -------------------------------------------


TOOL_SCHEMAS: list[dict[str, Any]] = [
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
                "path": {
                    "type": "string",
                    "description": "Subdirectory to list. Defaults to root.",
                    "default": "",
                }
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
                "glob": {
                    "type": "string",
                    "description": "Optional path glob filter.",
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max matches.",
                    "default": 50,
                },
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


TOOL_NAMES: frozenset[str] = frozenset(t["name"] for t in TOOL_SCHEMAS)
READ_ONLY_TOOLS: frozenset[str] = frozenset({"list_files", "grep", "view_file"})
TERMINAL_TOOL: str = "done"


# --- markdown for structured-prompt mode ----------------------------------


def render_op_descriptions() -> str:
    """Render TOOL_SCHEMAS as a markdown block for embedding in a structured
    system prompt where the model emits JSON actions instead of tool_use blocks."""
    lines: list[str] = []
    for t in TOOL_SCHEMAS:
        name = t["name"]
        desc = t["description"]
        props = t["input_schema"].get("properties", {})
        required = set(t["input_schema"].get("required") or [])
        arg_lines: list[str] = []
        for arg_name, arg_schema in props.items():
            req = " (required)" if arg_name in required else ""
            arg_type = arg_schema.get("type", "")
            arg_desc = arg_schema.get("description", "")
            arg_lines.append(f"    - {arg_name}: {arg_type}{req} — {arg_desc}")
        args_block = "\n".join(arg_lines) if arg_lines else "    (no args)"
        lines.append(f"### `{name}`\n{desc}\n\n  args:\n{args_block}")
    return "\n\n".join(lines)


OP_DESCRIPTIONS: str = render_op_descriptions()


# --- executor -------------------------------------------------------------


def apply_tool_call(call: ToolCall, repo: RepoView) -> ToolResult:
    """Apply one tool call against the repo view. Provider-agnostic.

    Both the tool_use loop and the structured loop dispatch through here:
    same code path regardless of how the call was packaged on the wire.
    """
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
                pattern,
                glob=args.get("glob", "") or "",
                limit=int(args.get("limit", 50)),
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
