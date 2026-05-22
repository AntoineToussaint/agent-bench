"""`search_replace` edit format — mirrors Aider's diff format and Anthropic's
`str_replace_based_edit_tool`. One precise text replacement per call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from coding_tool.formats.base import (
    DONE_TOOL,
    LIST_FILES_TOOL,
    VIEW_FILE_TOOL,
    EditFormat,
    apply_common,
    register_format,
)
from coding_tool.types import ToolCall, ToolResult


@register_format
class SearchReplaceFormat(EditFormat):
    name = "search_replace"
    description = (
        "Single-string find/replace with `str_replace`. Requires the `old_str` to "
        "appear exactly once in the file. Models must disambiguate by including "
        "surrounding context."
    )

    def tools(self) -> list[dict[str, Any]]:
        return [
            VIEW_FILE_TOOL,
            LIST_FILES_TOOL,
            {
                "name": "str_replace",
                "description": (
                    "Replace one occurrence of `old_str` with `new_str` inside the "
                    "file at `path`. The `old_str` must match exactly (including "
                    "indentation/whitespace) and must occur exactly once in the "
                    "file — if it occurs multiple times, include more surrounding "
                    "context to disambiguate."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path relative to the working directory.",
                        },
                        "old_str": {
                            "type": "string",
                            "description": "Exact text to find (must be unique in the file).",
                        },
                        "new_str": {
                            "type": "string",
                            "description": "Replacement text.",
                        },
                    },
                    "required": ["path", "old_str", "new_str"],
                },
            },
            {
                "name": "create_file",
                "description": "Create a new file with the given content.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "delete_file",
                "description": "Delete a file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            DONE_TOOL,
        ]

    def system_prompt(self) -> str:
        return (
            "You edit code using `str_replace`. Read files with `view_file` first. "
            "Each `str_replace` call must locate its target uniquely — include "
            "enough surrounding lines (typically 3+) that `old_str` matches exactly "
            "one location. When all edits are done, call `done`."
        )

    def apply(self, call: ToolCall, workdir: Path) -> ToolResult:
        common = apply_common(call, workdir)
        if common is not None:
            return common

        if call.name == "str_replace":
            return _apply_str_replace(call, workdir)
        if call.name == "create_file":
            return _apply_create_file(call, workdir)
        if call.name == "delete_file":
            return _apply_delete_file(call, workdir)

        return ToolResult(call.call_id, "error", f"unknown tool: {call.name}")


def _apply_str_replace(call: ToolCall, workdir: Path) -> ToolResult:
    path = call.arguments.get("path")
    old = call.arguments.get("old_str")
    new = call.arguments.get("new_str")
    if not path or old is None or new is None:
        return ToolResult(call.call_id, "error", "missing path/old_str/new_str")
    try:
        target = EditFormat.resolve(workdir, path)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    if not target.exists() or target.is_dir():
        return ToolResult(call.call_id, "error", f"not a file: {path}")

    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return ToolResult(
            call.call_id,
            "error",
            f"`old_str` not found in {path}. View the file to check exact whitespace.",
        )
    if count > 1:
        return ToolResult(
            call.call_id,
            "error",
            f"`old_str` matches {count} locations in {path}. Add more surrounding "
            f"context so it matches exactly once.",
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return ToolResult(call.call_id, "ok", f"replaced 1 occurrence in {path}")


def _apply_create_file(call: ToolCall, workdir: Path) -> ToolResult:
    path = call.arguments.get("path")
    content = call.arguments.get("content")
    if not path or content is None:
        return ToolResult(call.call_id, "error", "missing path/content")
    try:
        target = EditFormat.resolve(workdir, path)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    if target.exists():
        return ToolResult(call.call_id, "error", f"already exists: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return ToolResult(call.call_id, "ok", f"created {path} ({len(content)} bytes)")


def _apply_delete_file(call: ToolCall, workdir: Path) -> ToolResult:
    path = call.arguments.get("path")
    if not path:
        return ToolResult(call.call_id, "error", "missing path")
    try:
        target = EditFormat.resolve(workdir, path)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    if not target.exists() or target.is_dir():
        return ToolResult(call.call_id, "error", f"not a file: {path}")
    target.unlink()
    return ToolResult(call.call_id, "ok", f"deleted {path}")
