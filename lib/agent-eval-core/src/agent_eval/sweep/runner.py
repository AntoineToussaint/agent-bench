"""Domain-agnostic sweep runner.

The runner does not know:
  - what a "condition" means (you supply a list of strings)
  - what a "task" is (you supply any objects with a `.task_id` attribute or string)
  - how to run a single trial (you supply a callable)

The runner DOES know:
  - how to iterate the grid
  - how to call your trial function
  - how to track cumulative cost
  - how to halt on budget overrun
  - how to run in parallel
  - how to collect RunRecord results
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from agent_eval.models import make_client
from agent_eval.pricing import cost_usd
from agent_eval.sweep.budget import Budget, BudgetExceeded
from agent_eval.types import ModelClient, RunRecord


TrialFn = Callable[[ModelClient, str, Any], RunRecord]
SkipFn = Callable[[str, str, Any], bool]
ProgressFn = Callable[[int, int, RunRecord], None]


def _task_id(task: Any) -> str:
    return getattr(task, "task_id", str(task))


@dataclass
class Sweep:
    """A grid of (model x condition x task) to evaluate.

    Args:
        models: model ids understood by `agent_eval.models.make_client`
        conditions: free string labels; passed verbatim to your trial fn
        tasks: any iterable of task objects; passed to your trial fn
        trial: `(model_client, condition, task) -> RunRecord`
        budget: optional USD cap
        skip: optional predicate `(model, condition, task) -> bool`
        parallelism: thread pool size (1 = sequential)
        on_progress: optional `(idx, total, rec)` callback after each trial
    """

    models: list[str]
    conditions: list[str]
    tasks: list[Any]
    trial: TrialFn
    budget: Budget | None = None
    skip: SkipFn | None = None
    parallelism: int = 1
    on_progress: ProgressFn | None = None
    records: list[RunRecord] = field(default_factory=list)

    def grid(self) -> list[tuple[str, str, Any]]:
        out: list[tuple[str, str, Any]] = []
        for task in self.tasks:
            for model in self.models:
                for cond in self.conditions:
                    if self.skip and self.skip(model, cond, task):
                        continue
                    out.append((model, cond, task))
        return out

    def run(self) -> list[RunRecord]:
        cells = self.grid()
        total = len(cells)
        if self.parallelism <= 1:
            for i, (model, cond, task) in enumerate(cells, start=1):
                rec = self._run_one(model, cond, task)
                if rec is None:
                    return self.records
                self.records.append(rec)
                if self.on_progress:
                    self.on_progress(i, total, rec)
        else:
            with ThreadPoolExecutor(max_workers=self.parallelism) as pool:
                futures = {
                    pool.submit(self._run_one, m, c, t): (m, c, t) for m, c, t in cells
                }
                for i, fut in enumerate(as_completed(futures), start=1):
                    rec = fut.result()
                    if rec is None:
                        # budget hit; let already-running futures finish but don't enqueue more
                        continue
                    self.records.append(rec)
                    if self.on_progress:
                        self.on_progress(i, total, rec)
        return self.records

    def _run_one(self, model: str, cond: str, task: Any) -> RunRecord | None:
        try:
            client = make_client(model)
        except KeyError as e:
            return RunRecord(
                task_id=_task_id(task),
                model=model,
                condition=cond,
                passed=False,
                turns=0,
                tool_calls=0,
                invalid_tool_calls=0,
                usage=__import__("agent_eval.types", fromlist=["TurnUsage"]).TurnUsage(),
                latency_seconds=0.0,
                error=f"unknown_model: {e}",
            )
        rec = self.trial(client, cond, task)
        # Bill the run if pricing is available and cost wasn't pre-set.
        if rec.cost_usd == 0.0:
            rec.cost_usd = cost_usd(model, rec.usage)
        if self.budget:
            try:
                self.budget.add(rec.cost_usd)
            except BudgetExceeded as e:
                rec.error = (rec.error + "; " if rec.error else "") + f"budget_exceeded: {e}"
                return rec
        return rec
