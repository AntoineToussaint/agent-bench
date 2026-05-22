from __future__ import annotations

from dataclasses import dataclass

from datasets import load_dataset

# Named aliases for the common SWE-bench variants. Any unknown name is passed
# through as a raw HuggingFace dataset id, so users can target SWE-bench Pro
# (or any other variant) by id without code changes.
DATASETS = {
    "verified": "princeton-nlp/SWE-bench_Verified",
    "lite": "princeton-nlp/SWE-bench_Lite",
    "full": "princeton-nlp/SWE-bench",
    "multimodal": "princeton-nlp/SWE-bench_Multimodal",
    "pro": "ScaleAI/SWE-bench_Pro",
}


@dataclass(frozen=True)
class Task:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    patch: str
    test_patch: str = ""
    # When set, the retriever runs against this local path and the GitHub
    # clone-and-worktree dance is skipped. Useful for ad-hoc benchmarking
    # against working trees that may not have a public remote.
    repo_path: str = ""


def load_tasks(name: str = "verified", split: str = "test") -> list[Task]:
    spec = DATASETS.get(name, name)
    ds = load_dataset(spec, split=split)
    return [
        Task(
            instance_id=row["instance_id"],
            repo=row["repo"],
            base_commit=row["base_commit"],
            problem_statement=row["problem_statement"],
            patch=row["patch"],
            test_patch=row.get("test_patch") or "",
        )
        for row in ds
    ]
