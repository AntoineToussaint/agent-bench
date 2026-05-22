"""For every v2 task, apply its canonical solution and verify the oracle passes.

This guards against (a) fixture drift, (b) broken canonical solutions, and
(c) oracle tests that don't actually verify what they claim.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from coding_tool.bench.oracle import run_oracle
from coding_tool.bench.task import load_task, materialize


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V2_ROOT = PROJECT_ROOT / "tasks" / "v2"


def _discover() -> list[tuple[str, Path]]:
    tasks = []
    for yaml_path in sorted(V2_ROOT.rglob("task.yaml")):
        task_dir = yaml_path.parent
        cs = task_dir / "canonical_solution.py"
        if not cs.exists():
            continue
        # Use the relative path from V2_ROOT as the test id
        rel = task_dir.relative_to(V2_ROOT)
        tasks.append((str(rel), task_dir))
    return tasks


def _load_canonical(task_dir: Path):
    spec = importlib.util.spec_from_file_location(
        f"_cs_{task_dir.name}", task_dir / "canonical_solution.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_TASKS = _discover()


@pytest.mark.parametrize("rel,task_dir", _TASKS, ids=[t[0] for t in _TASKS] or ["none"])
def test_canonical_solution_passes_oracle(rel: str, task_dir: Path, tmp_path: Path) -> None:
    if rel == "none":
        pytest.skip("no v2 tasks discovered yet")
    task = load_task(task_dir)
    materialize(task, tmp_path)
    workdir = tmp_path.resolve()
    cs = _load_canonical(task_dir)
    cs.apply(workdir)
    res = run_oracle(task.oracle_cmd, workdir, timeout=60)
    assert res.passed, (
        f"oracle failed for {rel}.\n"
        f"--- stdout ---\n{res.stdout[-1500:]}\n"
        f"--- stderr ---\n{res.stderr[-1500:]}"
    )
