"""Local-file adapters for file-localization tasks.

Three input shapes are supported:

1. JSONL file -- one task per line, fields match SWE-bench column names plus
   the optional `repo_path` for local-repo runs.
2. JSON file  -- single task dict, or a list of task dicts.
3. Directory  -- one subdirectory per task, each containing `meta.json`
   (task fields except `patch`/`test_patch`) plus `gold.patch` and an
   optional `test.patch`.

The `make_single_task` helper constructs an ad-hoc RawTask from CLI arguments.
"""

from __future__ import annotations

import json
from pathlib import Path

from file_localization.adapters.hf_swebench import RawTask


def _task_from_dict(d: dict, default_id: str | None = None) -> RawTask:
    if "problem_statement" not in d:
        raise ValueError(
            f"task missing 'problem_statement': "
            f"{d.get('instance_id', default_id)!r}"
        )
    if not (d.get("repo") or d.get("repo_path")):
        raise ValueError(
            f"task missing both 'repo' and 'repo_path': "
            f"{d.get('instance_id', default_id)!r}"
        )
    return RawTask(
        instance_id=d.get("instance_id") or default_id or "",
        repo=d.get("repo", ""),
        base_commit=d.get("base_commit", ""),
        problem_statement=d["problem_statement"],
        patch=d.get("patch", ""),
        test_patch=d.get("test_patch") or "",
        repo_path=d.get("repo_path", ""),
    )


def _load_jsonl(path: Path) -> list[RawTask]:
    tasks: list[RawTask] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        tasks.append(_task_from_dict(json.loads(line), default_id=f"{path.stem}#{i}"))
    return tasks


def _load_json(path: Path) -> list[RawTask]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else [data]
    return [_task_from_dict(d, default_id=f"{path.stem}#{i}") for i, d in enumerate(items)]


def _load_dir(root: Path) -> list[RawTask]:
    tasks: list[RawTask] = []
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        meta_path = sub / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.setdefault("instance_id", sub.name)
        gold = sub / "gold.patch"
        if gold.exists() and "patch" not in meta:
            meta["patch"] = gold.read_text(encoding="utf-8")
        test = sub / "test.patch"
        if test.exists() and "test_patch" not in meta:
            meta["test_patch"] = test.read_text(encoding="utf-8")
        tasks.append(_task_from_dict(meta))
    return tasks


def load_local_tasks(path: Path) -> list[RawTask]:
    """Load tasks from a .jsonl, .json, or directory-of-tasks path."""
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_dir():
        return _load_dir(path)
    if path.suffix == ".jsonl":
        return _load_jsonl(path)
    if path.suffix == ".json":
        return _load_json(path)
    raise ValueError(
        f"unsupported task source: {path} (expected .jsonl, .json, or directory)"
    )


def make_single_task(
    *,
    patch: str,
    problem_statement: str,
    repo: str = "",
    base_commit: str = "",
    repo_path: str = "",
    test_patch: str = "",
    instance_id: str = "adhoc",
) -> RawTask:
    """Construct one RawTask from ad-hoc arguments (for CLI single-task runs)."""
    return _task_from_dict(
        {
            "instance_id": instance_id,
            "repo": repo,
            "base_commit": base_commit,
            "problem_statement": problem_statement,
            "patch": patch,
            "test_patch": test_patch,
            "repo_path": repo_path,
        }
    )
