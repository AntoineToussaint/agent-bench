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
  - how to run each cell N times (replicates) for distribution estimates
  - how to collect RunRecord results
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from agent_eval.models import make_model
from agent_eval.pricing import cost_usd
from agent_eval.protocols import ToolBackend
from agent_eval.sweep.budget import Budget, BudgetExceeded
from agent_eval.tracing import span_sweep, span_trial
from agent_eval.types import ModelHandle, RunRecord, TurnUsage


TrialFn = Callable[[ModelHandle, str, Any], RunRecord]
BackendForConditionFn = Callable[[str], ToolBackend | None]
SkipFn = Callable[[str, str, Any], bool]
ProgressFn = Callable[[int, int, RunRecord], None]


def _task_id(task: Any) -> str:
    return getattr(task, "task_id", str(task))


@dataclass
class Sweep:
    """A grid of (model x condition x task) to evaluate, optionally repeated.

    Args:
        models: model ids understood by `agent_eval.models.make_client`
        conditions: free string labels; passed verbatim to your trial fn
        tasks: any iterable of task objects; passed to your trial fn
        trial: `(model_client, condition, task) -> RunRecord`
        repetitions: how many times to run each (model, condition, task) cell.
            Default 1 (no replication). Set N > 1 for distribution estimates
            of pass rate / turns / cost / latency. Each replicate gets the
            same task input but a fresh ModelClient (so message history /
            cache doesn't bleed across runs).
        budget: optional USD cap
        skip: optional predicate `(model, condition, task) -> bool`
        parallelism: thread pool size (1 = sequential)
        on_progress: optional `(idx, total, rec)` callback after each trial
    """

    models: list[str]
    conditions: list[str]
    tasks: list[Any]
    trial: TrialFn
    repetitions: int = 1
    budget: Budget | None = None
    skip: SkipFn | None = None
    parallelism: int = 1
    on_progress: ProgressFn | None = None
    records: list[RunRecord] = field(default_factory=list)
    # Optional: map a condition string → a ToolBackend override. Used by
    # research sweeps that vary backend per condition (e.g. "turn-loop"
    # = native, "turn-loop-schema" = schema). When None, each model gets
    # its YAML-configured default backend regardless of condition.
    backend_for_condition: BackendForConditionFn | None = None

    def grid(self) -> list[tuple[str, str, Any, int]]:
        """Return every (model, condition, task, replicate_index) tuple."""
        out: list[tuple[str, str, Any, int]] = []
        for task in self.tasks:
            for model in self.models:
                for cond in self.conditions:
                    if self.skip and self.skip(model, cond, task):
                        continue
                    for rep in range(max(1, self.repetitions)):
                        out.append((model, cond, task, rep))
        return out

    def run(self) -> list[RunRecord]:
        cells = self.grid()
        total = len(cells)
        with span_sweep(
            n_models=len(self.models),
            n_conditions=len(self.conditions),
            n_tasks=len(self.tasks),
            repetitions=max(1, self.repetitions),
        ):
            if self.parallelism <= 1:
                for i, (model, cond, task, rep) in enumerate(cells, start=1):
                    rec = self._run_one(model, cond, task, rep)
                    if rec is None:
                        return self.records
                    self.records.append(rec)
                    if self.on_progress:
                        self.on_progress(i, total, rec)
            else:
                with ThreadPoolExecutor(max_workers=self.parallelism) as pool:
                    futures = {
                        pool.submit(self._run_one, m, c, t, r): (m, c, t, r)
                        for m, c, t, r in cells
                    }
                    for i, fut in enumerate(as_completed(futures), start=1):
                        rec = fut.result()
                        if rec is None:
                            continue
                        self.records.append(rec)
                        if self.on_progress:
                            self.on_progress(i, total, rec)
        return self.records

    def _run_one(
        self, model: str, cond: str, task: Any, replicate: int
    ) -> RunRecord | None:
        with span_trial(
            task_id=_task_id(task),
            condition=cond,
            model=model,
            replicate=replicate,
        ) as sp:
            try:
                backend_override = (
                    self.backend_for_condition(cond)
                    if self.backend_for_condition
                    else None
                )
                handle = make_model(model, backend=backend_override)
            except KeyError as e:
                sp.set_attribute("agent_eval.trial.error", f"unknown_model: {e}")
                return RunRecord(
                    task_id=_task_id(task),
                    model=model,
                    condition=cond,
                    passed=False,
                    turns=0,
                    tool_calls=0,
                    invalid_tool_calls=0,
                    usage=TurnUsage(),
                    latency_seconds=0.0,
                    replicate=replicate,
                    error=f"unknown_model: {e}",
                )
            sp.set_attribute("agent_eval.backend", handle.backend.name)
            rec = self.trial(handle, cond, task)
            rec.replicate = replicate
            # Bill the run if pricing is available and cost wasn't pre-set.
            if rec.cost_usd == 0.0:
                rec.cost_usd = cost_usd(model, rec.usage)
            # Surface trial results onto the span.
            sp.set_attribute("agent_eval.trial.passed", rec.passed)
            sp.set_attribute("agent_eval.trial.turns", rec.turns)
            sp.set_attribute("agent_eval.trial.tool_calls", rec.tool_calls)
            sp.set_attribute("agent_eval.trial.invalid_tool_calls", rec.invalid_tool_calls)
            sp.set_attribute("agent_eval.trial.cost_usd", rec.cost_usd)
            sp.set_attribute("agent_eval.trial.latency_seconds", rec.latency_seconds)
            if rec.error:
                sp.set_attribute("agent_eval.trial.error", rec.error)
            if self.budget:
                try:
                    self.budget.add(rec.cost_usd)
                except BudgetExceeded as e:
                    rec.error = (rec.error + "; " if rec.error else "") + f"budget_exceeded: {e}"
                    sp.set_attribute("agent_eval.trial.error", rec.error)
                    return rec
            return rec
