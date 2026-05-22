"""Backward-compatible shim — canonical converter lives in `file_localization.adapters.hf_swebench`."""

from file_localization.adapters.hf_swebench import (  # noqa: F401
    files_in_patch,
    to_localization_task,
    to_localization_tasks,
)

__all__ = ["files_in_patch", "to_localization_task", "to_localization_tasks"]
