"""`unified_diff` edit format — one tool that takes a unified-diff patch.

Uses the `unidiff` library to parse the patch and apply it ourselves, so we
don't need an external `patch` binary and we can give the model precise error
messages (mismatched context, fuzz, hunk failure, etc.).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from unidiff import PatchSet
from unidiff.errors import UnidiffParseError

from code_editing.formats.base import (
    DONE_TOOL,
    LIST_FILES_TOOL,
    VIEW_FILE_TOOL,
    EditFormat,
    apply_common,
    register_format,
)
from code_editing.types import ToolCall, ToolResult


@register_format
class UnifiedDiffFormat(EditFormat):
    name = "unified_diff"
    description = (
        "One tool that accepts a standard unified-diff patch (multiple hunks, "
        "multiple files). Apply is exact — context lines must match."
    )

    def tools(self) -> list[dict[str, Any]]:
        return [
            VIEW_FILE_TOOL,
            LIST_FILES_TOOL,
            {
                "name": "apply_patch",
                "description": (
                    "Apply a unified-diff patch to the working directory. The patch "
                    "may modify, create, or delete multiple files. Use standard "
                    "unified-diff format with `--- a/path`, `+++ b/path`, and "
                    "`@@ -l,n +l,n @@` hunk headers. Context lines must match the "
                    "current file contents exactly."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "patch": {
                            "type": "string",
                            "description": "Unified diff text.",
                        }
                    },
                    "required": ["patch"],
                },
            },
            DONE_TOOL,
        ]

    def system_prompt(self) -> str:
        return (
            "You edit code using unified-diff patches via the `apply_patch` tool. "
            "Always `view_file` first so your context lines match. Use the standard "
            "format:\n"
            "    --- a/path/to/file.py\n"
            "    +++ b/path/to/file.py\n"
            "    @@ -10,3 +10,4 @@\n"
            "     unchanged line\n"
            "    -removed line\n"
            "    +added line\n"
            "     unchanged line\n"
            "When all edits are done, call `done`."
        )

    def apply(self, call: ToolCall, workdir: Path) -> ToolResult:
        common = apply_common(call, workdir)
        if common is not None:
            return common
        if call.name != "apply_patch":
            return ToolResult(call.call_id, "error", f"unknown tool: {call.name}")
        patch_text = call.arguments.get("patch")
        if not patch_text:
            return ToolResult(call.call_id, "error", "missing `patch`")
        return _apply_patch(call.call_id, workdir, patch_text)


def _apply_patch(call_id: str, workdir: Path, patch_text: str) -> ToolResult:
    # Detect the OpenAI Codex "*** Begin Patch" envelope, which is NOT a unified
    # diff. We reject it explicitly so the model gets actionable feedback.
    if "*** Begin Patch" in patch_text or "*** Update File" in patch_text:
        return ToolResult(
            call_id,
            "error",
            (
                "this looks like the OpenAI Codex `*** Begin Patch` envelope, "
                "not a standard unified diff. Re-emit using the standard format "
                "with `--- a/path`, `+++ b/path`, and `@@ -l,n +l,n @@` headers."
            ),
        )
    try:
        patch = PatchSet(patch_text)
    except UnidiffParseError as e:
        return ToolResult(call_id, "error", f"patch parse error: {e}")
    except Exception as e:  # noqa: BLE001 — unidiff raises a grab-bag
        return ToolResult(call_id, "error", f"patch parse error: {e}")

    if len(patch) == 0:
        return ToolResult(
            call_id,
            "error",
            (
                "patch parsed to zero files — your input is probably not in "
                "standard unified-diff format. Expected `--- a/path`, "
                "`+++ b/path`, and `@@` hunk headers."
            ),
        )

    changes: list[str] = []
    for pfile in patch:
        ok, msg = _apply_one_file(workdir, pfile)
        if not ok:
            return ToolResult(call_id, "error", msg)
        changes.append(msg)
    return ToolResult(call_id, "ok", "applied:\n" + "\n".join(changes))


def _apply_one_file(workdir: Path, pfile: Any) -> tuple[bool, str]:
    src = _strip_prefix(pfile.source_file)
    dst = _strip_prefix(pfile.target_file)

    if pfile.is_added_file:
        try:
            target = EditFormat.resolve(workdir, dst)
        except ValueError as e:
            return False, str(e)
        new_lines = [line.value for hunk in pfile for line in hunk if line.is_added]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(new_lines), encoding="utf-8")
        return True, f"created {dst}"

    if pfile.is_removed_file:
        try:
            target = EditFormat.resolve(workdir, src)
        except ValueError as e:
            return False, str(e)
        if target.exists():
            target.unlink()
        return True, f"deleted {src}"

    try:
        target = EditFormat.resolve(workdir, src)
    except ValueError as e:
        return False, str(e)
    if not target.exists():
        return False, f"target file does not exist: {src}"

    original = target.read_text(encoding="utf-8").splitlines(keepends=True)
    result = _apply_hunks(original, pfile)
    if isinstance(result, str):
        return False, f"hunk failed for {src}: {result}"
    target.write_text("".join(result), encoding="utf-8")
    return True, f"patched {src} ({len(list(pfile))} hunk(s))"


def _strip_prefix(p: str) -> str:
    if p.startswith("a/") or p.startswith("b/"):
        return p[2:]
    return p


def _apply_hunks(original: list[str], pfile: Any) -> list[str] | str:
    """Apply unidiff hunks by CONTEXT MATCHING (ignore header line numbers).

    For each hunk, build its `before` block (context + removed lines) and its
    `after` block (context + added lines). Locate `before` as a contiguous
    sublist of the current file content, then replace it with `after`.
    Header line numbers from `@@ -l,n +l,n @@` are used only as a hint for
    disambiguation if `before` appears multiple times.
    """
    lines = list(original)
    cursor = 0  # don't search before this position (preserves hunk order)
    for hunk in pfile:
        before: list[str] = []
        after: list[str] = []
        for line in hunk:
            if line.is_context:
                before.append(line.value)
                after.append(line.value)
            elif line.is_removed:
                before.append(line.value)
            elif line.is_added:
                after.append(line.value)

        if not before:
            # Pure insertion hunk — use the header's line number.
            idx = max(cursor, hunk.source_start - 1)
            lines = lines[:idx] + after + lines[idx:]
            cursor = idx + len(after)
            continue

        # Find `before` in `lines[cursor:]`. Prefer match closest to claimed line.
        claimed = max(cursor, hunk.source_start - 1)
        positions = _all_positions(lines, before, start=cursor)
        if not positions:
            preview = before[0].rstrip("\n") if before else ""
            return (
                f"could not locate hunk near source line {hunk.source_start} "
                f"(context starts with {preview!r})"
            )
        # pick the position closest to `claimed`
        idx = min(positions, key=lambda p: abs(p - claimed))
        lines = lines[:idx] + after + lines[idx + len(before):]
        cursor = idx + len(after)
    return lines


def _all_positions(haystack: list[str], needle: list[str], start: int = 0) -> list[int]:
    """Return every index `i >= start` such that haystack[i:i+len(needle)] == needle."""
    if not needle or len(needle) > len(haystack) - start:
        return [] if needle else []
    out: list[int] = []
    n = len(needle)
    for i in range(start, len(haystack) - n + 1):
        if haystack[i:i + n] == needle:
            out.append(i)
    return out
