"""Backward-compatible shim — canonical loaders live in `file_localization.adapters.local`."""

from file_localization.adapters.hf_swebench import RawTask as Task  # noqa: F401
from file_localization.adapters.local import (  # noqa: F401
    load_local_tasks,
    make_single_task,
)

__all__ = ["Task", "load_local_tasks", "make_single_task"]
