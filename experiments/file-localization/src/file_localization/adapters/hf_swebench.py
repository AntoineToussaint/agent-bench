"""HuggingFace SWE-Bench adapter.

Pulls task rows from any SWE-Bench dataset variant (or arbitrary HF dataset
ID) and converts each into a LocalizationTask via gold-patch parsing.

  raw    = load_swebench("verified")                   # list[RawTask]
  tasks  = to_localization_tasks(raw)                  # list[LocalizationTask]

Usage from a sweep:

  from file_localization.adapters import load_swebench, to_localization_tasks
  from file_localization.llm_trial import make_llm_trial
  from agent_eval import Sweep

  raw = load_swebench("verified", split="test")[:50]
  tasks = to_localization_tasks(raw)
  Sweep(models=[...], conditions=[...], tasks=tasks,
        trial=make_llm_trial(top_k=10)).run()
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from datasets import load_dataset

from file_localization.contract import LocalizationTask


# Named aliases for the common SWE-bench variants. Any unknown name is passed
# through as a raw HuggingFace dataset id, so users can target arbitrary
# variants (SWE-bench Pro, custom forks) by id without code changes.
DATASETS = {
    "verified": "princeton-nlp/SWE-bench_Verified",
    "lite": "princeton-nlp/SWE-bench_Lite",
    "full": "princeton-nlp/SWE-bench",
    "multimodal": "princeton-nlp/SWE-bench_Multimodal",
    "pro": "ScaleAI/SWE-bench_Pro",
}


@dataclass(frozen=True)
class RawTask:
    """SWE-Bench native row, before conversion to LocalizationTask."""

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    patch: str
    test_patch: str = ""
    repo_path: str = ""  # for ad-hoc local-repo runs


def load_swebench(name: str = "verified", split: str = "test") -> list[RawTask]:
    """Load a SWE-Bench split as RawTask records."""
    spec = DATASETS.get(name, name)
    ds = load_dataset(spec, split=split)
    return [
        RawTask(
            instance_id=row["instance_id"],
            repo=row["repo"],
            base_commit=row["base_commit"],
            problem_statement=row["problem_statement"],
            patch=row["patch"],
            test_patch=row.get("test_patch") or "",
        )
        for row in ds
    ]


# --- patch → gold-file-set parsing ---

_DIFF_PATH = re.compile(r"^diff --git a/(\S+) b/", re.MULTILINE)
_ADDED_FILE = re.compile(r"^\+\+\+ b/(\S+)", re.MULTILINE)


def files_in_patch(patch_text: str) -> frozenset[str]:
    """Extract the set of file paths a unified-diff patch modifies."""
    if not patch_text:
        return frozenset()
    paths: set[str] = set()
    paths.update(_DIFF_PATH.findall(patch_text))
    if not paths:
        # Fall back to +++ lines if no `diff --git` headers (rare but happens)
        paths.update(_ADDED_FILE.findall(patch_text))
    return frozenset(paths)


# --- raw → canonical LocalizationTask conversion ---


def to_localization_task(
    raw: RawTask, repo_file_list: tuple[str, ...] | None = None
) -> LocalizationTask:
    """Adapt one SWE-Bench row to a LocalizationTask."""
    return LocalizationTask(
        instance_id=raw.instance_id,
        issue_text=raw.problem_statement,
        repo=raw.repo,
        base_commit=raw.base_commit,
        gold_edit_files=files_in_patch(raw.patch),
        gold_test_files=files_in_patch(raw.test_patch),
        repo_file_list=repo_file_list,
    )


def to_localization_tasks(
    raws: Iterable[RawTask],
    file_lists: dict[str, tuple[str, ...]] | None = None,
) -> list[LocalizationTask]:
    """Bulk adapt SWE-Bench rows."""
    file_lists = file_lists or {}
    return [
        to_localization_task(r, file_lists.get(r.instance_id))
        for r in raws
    ]
