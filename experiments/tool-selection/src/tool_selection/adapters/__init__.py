"""Task / catalog adapters for the tool-selection experiment.

An adapter pulls task definitions (or tool catalogs) from a source and returns
the canonical types (`Task`, `Catalog`) defined in `tool_selection.contract`.

Available adapters:
  - `local_hand_authored`: the 16 hand-authored tasks shipped with this
    repo, split by difficulty (easy / medium / hard) and by failure mode
    (bash / pytest / runner / verify).

Planned (not implemented):
  - `mcp_server`: pull a live tool inventory from a running MCP server.
  - `bfcl`: import tasks from the Berkeley Function-Calling Leaderboard.
  - `composio`: import from Composio's tool-use eval set.
  - `traject_bench`: import "confusable sibling" coverage from TRAJECT-Bench.
"""

from tool_selection.adapters.local_hand_authored import (  # noqa: F401
    all_tasks,
    tasks_by_difficulty,
    tasks_by_failure_mode,
)

__all__ = ["all_tasks", "tasks_by_difficulty", "tasks_by_failure_mode"]
