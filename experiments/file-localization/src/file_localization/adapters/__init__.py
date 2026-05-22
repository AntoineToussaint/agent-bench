"""Data adapters for file-localization tasks.

Each adapter pulls task definitions from a different source and returns
LocalizationTask instances (the canonical contract type).

Available adapters:
  - `hf_swebench`: HuggingFace SWE-Bench datasets (verified, lite, full,
    multimodal, pro). Includes the patch → gold-file-set parser.
  - `local`: JSONL, JSON, or directory-of-tasks layouts on disk.

The raw intermediate `RawTask` type carries SWE-Bench's native fields
(patch text, test_patch text); converting to LocalizationTask happens via
`to_localization_task` / `to_localization_tasks`.
"""

from file_localization.adapters.hf_swebench import (  # noqa: F401
    DATASETS,
    RawTask,
    files_in_patch,
    load_swebench,
    to_localization_task,
    to_localization_tasks,
)
from file_localization.adapters.local import (  # noqa: F401
    load_local_tasks,
    make_single_task,
)

__all__ = [
    "DATASETS",
    "RawTask",
    "files_in_patch",
    "load_local_tasks",
    "load_swebench",
    "make_single_task",
    "to_localization_task",
    "to_localization_tasks",
]
