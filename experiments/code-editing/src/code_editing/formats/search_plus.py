"""`search_plus` edit format — text-edit workhorse with a few semantic ops
*specifically* for operations where the model under pure search_replace
under-emits: rename, move, change_value_of.

The system prompt explicitly routes the model: use the higher-level op when
it fits, fall back to `str_replace` otherwise. The hypothesis is that this
hybrid beats both pure-text and pure-semantic formats: text-edit power for
generic edits, semantic compression for the few intent-rich operations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from code_editing.formats.base import (
    DONE_TOOL,
    LIST_FILES_TOOL,
    VIEW_FILE_TOOL,
    EditFormat,
    apply_common,
    register_format,
)
from code_editing.formats.search_replace import (
    _apply_create_file,
    _apply_delete_file,
    _apply_str_replace,
)
from code_editing.formats.semantic import (
    _do_change_value,
    _do_move,
    _do_rename,
)
from code_editing.types import ToolCall, ToolResult


@register_format
class SearchPlusFormat(EditFormat):
    name = "search_plus"
    description = (
        "Text-edit workhorse (str_replace) with rename / move / "
        "change_value_of as semantic shortcuts for operations where "
        "text-edit under-emits. Hybrid format."
    )

    def tools(self) -> list[dict[str, Any]]:
        return [
            VIEW_FILE_TOOL,
            LIST_FILES_TOOL,
            # --- semantic shortcuts (preferred when they fit) ---
            {
                "name": "rename",
                "description": (
                    "PREFERRED for renaming a symbol across one or many "
                    "files. Updates every identifier reference plus textual "
                    "mentions in docstrings/comments. One call covers all "
                    "files — do NOT enumerate sites with str_replace."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "old_name": {"type": "string"},
                        "new_name": {"type": "string"},
                    },
                    "required": ["paths", "old_name", "new_name"],
                },
            },
            {
                "name": "move",
                "description": (
                    "PREFERRED for relocating a top-level definition from "
                    "one file to another. Does not rewrite imports — issue "
                    "follow-up edits if importers must be updated."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "from_path": {"type": "string"},
                        "to_path": {"type": "string"},
                        "name": {"type": "string"},
                    },
                    "required": ["from_path", "to_path", "name"],
                },
            },
            {
                "name": "change_value_of",
                "description": (
                    "PREFERRED for changing the RHS of a named binding "
                    "(constants, top-level assignments). `new_value` is a "
                    "language expression as source — quote string literals."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "target": {"type": "string"},
                        "new_value": {"type": "string"},
                    },
                    "required": ["path", "target", "new_value"],
                },
            },
            # --- text-edit workhorse ---
            {
                "name": "str_replace",
                "description": (
                    "Replace one occurrence of `old_str` with `new_str` in "
                    "the file at `path`. The `old_str` must match exactly "
                    "(including whitespace) and uniquely. Use this for any "
                    "edit that isn't a rename / move / value-change."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_str": {"type": "string"},
                        "new_str": {"type": "string"},
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
            "You have four ways to edit code. ALWAYS use the most specific "
            "tool that fits:\n\n"
            "  - **`rename`** — when the task is renaming a symbol across "
            "files. ONE call handles every site. Do NOT enumerate sites "
            "with str_replace if `rename` fits.\n"
            "  - **`move`** — when relocating a top-level definition to "
            "another file.\n"
            "  - **`change_value_of`** — when changing the value of a "
            "named binding (constant / top-level assignment).\n"
            "  - **`str_replace`** — everything else: arbitrary text edits, "
            "function-body rewrites, multi-line refactors.\n\n"
            "Coordinated multi-step tasks (e.g. add a parameter AND update "
            "its callers) usually need MULTIPLE tool calls in one response. "
            "Pack independent edits into independent calls — do not stuff "
            "them into one giant str_replace unless the regions are "
            "actually contiguous."
        )

    def apply(self, call: ToolCall, workdir: Path) -> ToolResult:
        common = apply_common(call, workdir)
        if common is not None:
            return common
        dispatch = {
            "rename": _do_rename,
            "move": _do_move,
            "change_value_of": _do_change_value,
            "str_replace": _apply_str_replace,
            "create_file": _apply_create_file,
            "delete_file": _apply_delete_file,
        }
        handler = dispatch.get(call.name)
        if handler is None:
            return ToolResult(call.call_id, "error", f"unknown tool: {call.name}")
        return handler(call, workdir)
