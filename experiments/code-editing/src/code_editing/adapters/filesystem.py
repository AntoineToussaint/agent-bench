"""Filesystem adapter: load EditTasks from local task directories.

Each task is a directory with this layout:

    <task_dir>/
        task.yaml             # task_id, language, category, instructions,
                              # files_in_context, oracle_cmd
        fixture/              # starter files (copied verbatim into workdir)
        oracle/               # files merged AFTER fixture (e.g. _overlay/ with
                              # hidden oracle tests) — copied via the runner,
                              # not by this adapter.

The adapter only loads metadata + the fixture path. The runner does the
fixture materialization (copy fixture → workdir, then copy oracle/ → workdir).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from code_editing.contract import EditTask


def load_task(task_dir: Path) -> EditTask:
    """Load one task from a directory containing task.yaml + fixture/."""
    meta_path = task_dir / "task.yaml"
    if not meta_path.exists():
        raise FileNotFoundError(f"missing task.yaml: {meta_path}")
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    fixture = task_dir / "fixture"
    if not fixture.exists():
        raise FileNotFoundError(f"missing fixture dir: {fixture}")
    return EditTask(
        task_id=meta["task_id"],
        language=meta["language"],
        category=meta["category"],
        fixture_dir=fixture,
        instructions=meta["instructions"],
        oracle_cmd=tuple(meta["oracle_cmd"]),
        files_in_context=tuple(meta.get("files_in_context", [])),
    )


def discover_tasks(root: Path) -> list[EditTask]:
    """Find every `task.yaml` under `root` and load it."""
    tasks: list[EditTask] = []
    for task_yaml in sorted(root.rglob("task.yaml")):
        try:
            tasks.append(load_task(task_yaml.parent))
        except Exception as e:  # noqa: BLE001
            print(f"WARN: failed to load {task_yaml}: {e}")
    return tasks


def materialize(task: EditTask, workdir: Path) -> None:
    """Copy fixture + oracle files into workdir. Used by the runner."""
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
