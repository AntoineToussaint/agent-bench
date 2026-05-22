"""Task discovery and loading.

A task is a directory with this layout:

    tasks/<category>/<task_id>/
        task.yaml          # metadata
        fixture/           # starter files copied into the workdir
        oracle/            # files merged into workdir before oracle runs
                           # (e.g. pytest tests). May be empty if oracle_cmd
                           # uses something already in fixture.

`task.yaml` example:

    task_id: rename-helper-001
    language: python
    category: rename
    instructions: |
      Rename the function `helper` to `compute_total` everywhere it is used.
    files_in_context:
      - main.py
      - utils.py
    oracle_cmd: ["python", "-m", "pytest", "-q", "tests/"]
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-not-found]

from code_editing.types import TaskSpec


def load_task(task_dir: Path) -> TaskSpec:
    meta_path = task_dir / "task.yaml"
    if not meta_path.exists():
        raise FileNotFoundError(f"missing task.yaml: {meta_path}")
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    fixture = task_dir / "fixture"
    if not fixture.exists():
        raise FileNotFoundError(f"missing fixture dir: {fixture}")
    return TaskSpec(
        task_id=meta["task_id"],
        language=meta["language"],
        category=meta["category"],
        fixture_dir=fixture,
        instructions=meta["instructions"],
        oracle_cmd=meta["oracle_cmd"],
        files_in_context=meta.get("files_in_context", []),
    )


def discover_tasks(root: Path) -> list[TaskSpec]:
    tasks = []
    for task_yaml in sorted(root.rglob("task.yaml")):
        try:
            tasks.append(load_task(task_yaml.parent))
        except Exception as e:
            print(f"WARN: failed to load {task_yaml}: {e}")
    return tasks


def materialize(task: TaskSpec, workdir: Path) -> None:
    """Copy fixture + oracle files into workdir."""
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    _copytree(task.fixture_dir, workdir)
    oracle_dir = task.fixture_dir.parent / "oracle"
    if oracle_dir.exists():
        _copytree(oracle_dir, workdir)


def _copytree(src: Path, dst: Path) -> None:
    for entry in src.rglob("*"):
        rel = entry.relative_to(src)
        target = dst / rel
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, target)
