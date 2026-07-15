"""Domain-specific types for code-editing.

Shared types (ToolCall, ToolResult, TurnUsage, RunRecord, ModelClient, etc.)
live in `agent_eval`. We re-export the ones used widely here so existing
imports keep working.
"""

from __future__ import annotations

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

from code_editing.contract import EditTask


# Backward-compatible public name; the contract module is the single source
# of truth rather than a second, structurally identical dataclass.
TaskSpec = EditTask
