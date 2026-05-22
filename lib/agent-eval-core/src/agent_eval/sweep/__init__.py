"""Sweep runner: iterate (model x condition x task), aggregate, persist.

A Sweep doesn't know what your conditions/tasks mean. You provide a `trial`
function — `Callable[[ModelClient, str, Any], RunRecord]` — and the sweep
loops it over your (model, condition, task) grid.

Optional features:
  - Budget cap: halt when accumulated cost crosses a USD limit
  - Parallel execution: thread pool with configurable concurrency
  - Skip filter: callable returning True for combinations to skip
"""

from agent_eval.sweep.budget import Budget
from agent_eval.sweep.runner import Sweep, TrialFn

__all__ = ["Budget", "Sweep", "TrialFn"]
