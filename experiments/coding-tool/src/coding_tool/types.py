"""Domain-specific types for coding-tool.

Shared types (ToolCall, ToolResult, TurnUsage, RunRecord, ModelClient, etc.)
live in `agent_eval`. We re-export the ones used widely here so existing
imports keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Re-exports from agent-eval-core so existing imports continue to work.
from agent_eval import (  # noqa: F401
    AssistantMessage,
    ModelClient,
    RunRecord,
    ToolCall,
    ToolResult,
    Transcript,
    TurnUsage,
)


@dataclass
class TaskSpec:
    """A benchmark task fixture — coding-tool-specific."""

    task_id: str
    language: Literal["python", "typescript"]
    category: str  # e.g. "rename", "move", "extract_method", "polyglot"
    fixture_dir: Path  # directory containing the starter files
    instructions: str
    oracle_cmd: list[str]  # command to run inside the workdir to verify
    files_in_context: list[str] = field(default_factory=list)
