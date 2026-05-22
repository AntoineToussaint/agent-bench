"""Backward-compatible shim — canonical loaders live in `code_editing.adapters.filesystem`."""

from code_editing.adapters.filesystem import (  # noqa: F401
    discover_tasks,
    load_task,
    materialize,
)
