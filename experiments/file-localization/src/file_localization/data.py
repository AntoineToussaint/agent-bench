"""Backward-compatible shim — canonical loaders live in `file_localization.adapters.hf_swebench`."""

from file_localization.adapters.hf_swebench import (  # noqa: F401
    DATASETS,
    RawTask as Task,
    load_swebench as load_tasks,
)

__all__ = ["DATASETS", "Task", "load_tasks"]
