from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tqdm import tqdm

from .data import Task
from .metrics import ndcg_at_k, recall_at_k
from .patches import files_in_patch, split_edit_test
from .repos import prepare
from .retrievers.base import Retriever

KS = (1, 5, 10, 20)


@dataclass
class TaskResult:
    instance_id: str
    repo: str
    method: str
    gold_edit_files: list[str]
    gold_test_files: list[str]
    predicted: list[str]
    recall_all: dict[int, float] = field(default_factory=dict)
    recall_edit: dict[int, float] = field(default_factory=dict)
    ndcg_all: dict[int, float] = field(default_factory=dict)
    ndcg_edit: dict[int, float] = field(default_factory=dict)
    index_ms: float = 0.0
    query_ms: float = 0.0
    error: str | None = None


def _score(predicted: list[str], gold: list[str]) -> tuple[dict[int, float], dict[int, float]]:
    gset = set(gold)
    return (
        {k: recall_at_k(predicted, gset, k) for k in KS},
        {k: ndcg_at_k(predicted, gset, k) for k in KS},
    )


def run(retriever: Retriever, tasks: list[Task], k_max: int = 20) -> list[TaskResult]:
    results: list[TaskResult] = []
    for task in tqdm(tasks, desc=retriever.name):
        edit_files, test_files = split_edit_test(files_in_patch(task.patch))
        result = TaskResult(
            instance_id=task.instance_id,
            repo=task.repo,
            method=retriever.name,
            gold_edit_files=edit_files,
            gold_test_files=test_files,
            predicted=[],
        )
        try:
            repo_path = prepare(task.repo, task.base_commit, task.repo_path)
        except Exception as exc:  # noqa: BLE001 — record any failure and continue
            result.error = f"prepare: {exc}"
            results.append(result)
            continue

        try:
            t0 = time.perf_counter()
            idx = retriever.index(repo_path)
            result.index_ms = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            result.predicted = retriever.query(idx, task.problem_statement, k_max)
            result.query_ms = (time.perf_counter() - t0) * 1000
        except Exception as exc:  # noqa: BLE001
            result.error = f"retrieve: {exc}"
            results.append(result)
            continue

        all_gold = edit_files + test_files
        result.recall_all, result.ndcg_all = _score(result.predicted, all_gold)
        result.recall_edit, result.ndcg_edit = _score(result.predicted, edit_files)
        results.append(result)
    return results


def summarize(results: list[TaskResult]) -> dict:
    scored = [r for r in results if r.error is None and r.gold_edit_files]
    n = len(scored)
    if n == 0:
        return {"n": 0, "errors": sum(1 for r in results if r.error)}

    def avg(values: list[float]) -> float:
        return round(sum(values) / n, 4)

    def median(values: list[float]) -> float:
        return round(sorted(values)[len(values) // 2], 2)

    return {
        "method": scored[0].method,
        "n": n,
        "errors": sum(1 for r in results if r.error),
        "recall_all": {k: avg([r.recall_all[k] for r in scored]) for k in KS},
        "recall_edit": {k: avg([r.recall_edit[k] for r in scored]) for k in KS},
        "ndcg_all": {k: avg([r.ndcg_all[k] for r in scored]) for k in KS},
        "ndcg_edit": {k: avg([r.ndcg_edit[k] for r in scored]) for k in KS},
        "median_index_ms": median([r.index_ms for r in scored]),
        "median_query_ms": median([r.query_ms for r in scored]),
    }


def save_results(results: list[TaskResult], summary: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": summary,
        "per_task": [asdict(r) for r in results],
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
