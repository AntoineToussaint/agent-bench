"""EditFormat abstraction.

Each format exposes:
  - the tool *schemas* given to the model (JSON-schema dicts, provider-agnostic)
  - an *apply* function that interprets a tool call against a working directory
  - a snippet of *system-prompt guidance* that explains the format to the model

The tool schema dicts follow Anthropic's tool-use shape (`name`, `description`,
`input_schema`) because it is the simpler of the two main provider shapes; the
OpenAI client converts on the fly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from code_editing.types import ToolCall, ToolResult


class EditFormat(ABC):
    """Base class for an edit format under test."""

    name: str  # short identifier, e.g. "search_replace"
    description: str  # one-line description

    @abstractmethod
    def tools(self) -> list[dict[str, Any]]:
        """Tool schemas exposed to the model (Anthropic shape)."""

    @abstractmethod
    def system_prompt(self) -> str:
        """Format-specific guidance injected into the system prompt."""

    @abstractmethod
    def apply(self, call: ToolCall, workdir: Path) -> ToolResult:
        """Interpret one tool call against `workdir`."""

    # --- helpers shared by all formats ----------------------------------

    @staticmethod
    def resolve(workdir: Path, rel: str) -> Path:
        """Resolve a model-supplied relative path safely inside workdir.

        Refuses paths under `_overlay/` — that directory holds oracle test
        files that must remain hidden from the model so it can't read or
        edit them to game the benchmark.
        """
        p = (workdir / rel).resolve()
        wd = str(workdir.resolve())
        if not str(p).startswith(wd):
            raise ValueError(f"path escapes workdir: {rel}")
        # Block any path that lives inside _overlay/.
        relparts = p.relative_to(workdir.resolve()).parts
        if relparts and relparts[0] == "_overlay":
            raise ValueError(f"path is reserved: {rel}")
        return p


FORMAT_REGISTRY: dict[str, type[EditFormat]] = {}


def register_format(cls: type[EditFormat]) -> type[EditFormat]:
    if not getattr(cls, "name", None):
        raise ValueError(f"{cls.__name__} missing class attribute `name`")
    FORMAT_REGISTRY[cls.name] = cls
    return cls


# ---------- common tools every format gets ----------

VIEW_FILE_TOOL: dict[str, Any] = {
    "name": "view_file",
    "description": (
        "Read the contents of a file in the working directory. "
        "Returns the file with 1-indexed line numbers."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to the working directory.",
            },
        },
        "required": ["path"],
    },
}

LIST_FILES_TOOL: dict[str, Any] = {
    "name": "list_files",
    "description": "List files in the working directory (recursive).",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Subdirectory to list. Defaults to root.",
                "default": ".",
            },
        },
        "required": [],
    },
}

DONE_TOOL: dict[str, Any] = {
    "name": "done",
    "description": (
        "Signal that all required edits have been made. "
        "Call this after you have finished editing and want the tests to run."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Brief summary of the edits made.",
            },
        },
        "required": [],
    },
}


def apply_common(call: ToolCall, workdir: Path) -> ToolResult | None:
    """Apply view_file / list_files / done. Returns None if not a common tool."""
    if call.name == "view_file":
        rel = call.arguments.get("path")
        if not rel:
            return ToolResult(call.call_id, "error", "missing `path`")
        try:
            target = EditFormat.resolve(workdir, rel)
        except ValueError as e:
            return ToolResult(call.call_id, "error", str(e))
        if not target.exists():
            return ToolResult(call.call_id, "error", f"file not found: {rel}")
        if target.is_dir():
            return ToolResult(call.call_id, "error", f"is a directory: {rel}")
        text = target.read_text(encoding="utf-8", errors="replace")
        numbered = "\n".join(
            f"{i + 1:>5}: {line}" for i, line in enumerate(text.splitlines())
        )
        return ToolResult(call.call_id, "ok", numbered)

    if call.name == "list_files":
        rel = call.arguments.get("path", ".")
        try:
            root = EditFormat.resolve(workdir, rel)
        except ValueError as e:
            return ToolResult(call.call_id, "error", str(e))
        if not root.exists() or not root.is_dir():
            return ToolResult(call.call_id, "error", f"not a directory: {rel}")
        entries = sorted(
            str(p.relative_to(workdir))
            for p in root.rglob("*")
            if p.is_file()
            and "/.git/" not in str(p)
            and "/__pycache__/" not in str(p)
            and "/_overlay/" not in str(p)
            and not str(p.relative_to(workdir)).startswith("_overlay/")
        )
        return ToolResult(call.call_id, "ok", "\n".join(entries) or "(empty)")

    if call.name == "done":
        summary = call.arguments.get("summary", "")
        return ToolResult(call.call_id, "ok", f"acknowledged: {summary}")

    return None
