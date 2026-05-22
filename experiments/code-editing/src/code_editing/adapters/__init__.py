"""Data adapters for code-editing tasks.

Each adapter pulls task definitions from a different source and returns
an iterable of `EditTask` (the contract type).

Available adapters:
  - `filesystem`: a local directory of task subdirs, each with `task.yaml`
    + `fixture/` + `oracle/`. The canonical format the experiment ships
    its own 42 tasks in.
  - `aider_polyglot`: clones Aider's polyglot benchmark and converts
    each exercise into a Python EditTask.

Planned (not implemented):
  - `hf_swebench`: load SWE-Bench rows + materialize each as an EditTask
    that operates on a real repo checkout.
  - `github_pr`: extract a fixture+oracle pair from a real GitHub PR
    (file state before the fix, tests added/modified by the fix).
"""

from code_editing.adapters.filesystem import discover_tasks, load_task

__all__ = ["discover_tasks", "load_task"]
