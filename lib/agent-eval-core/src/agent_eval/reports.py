"""CSV + markdown reports from a list of RunRecords.

Two views:
  - Per-record CSV: one row per trial (including each replicate).
  - Per-cell aggregate: collapse replicates into pass_rate + p25/p50/p75
    distributions for turns / cost / latency / tokens.
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from agent_eval.types import RunRecord


CSV_COLUMNS = [
    "task_id",
    "model",
    "condition",
    "replicate",
    "passed",
    "turns",
    "tool_calls",
    "invalid_tool_calls",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "cost_usd",
    "latency_seconds",
    "error",
]


def write_csv(records: list[RunRecord], out: Path) -> None:
    """One row per trial (replicates produce separate rows)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in records:
            w.writerow(
                {
                    "task_id": r.task_id,
                    "model": r.model,
                    "condition": r.condition,
                    "replicate": r.replicate,
                    "passed": int(r.passed),
                    "turns": r.turns,
                    "tool_calls": r.tool_calls,
                    "invalid_tool_calls": r.invalid_tool_calls,
                    "input_tokens": r.usage.input_tokens,
                    "output_tokens": r.usage.output_tokens,
                    "cache_read_tokens": r.usage.cache_read_tokens,
                    "cache_creation_tokens": r.usage.cache_creation_tokens,
                    "cost_usd": f"{r.cost_usd:.6f}",
                    "latency_seconds": f"{r.latency_seconds:.3f}",
                    "error": r.error or "",
                }
            )


# --- per-cell aggregate over replicates ---


@dataclass
class CellStats:
    """Aggregated stats for one (model, condition, task) cell across N replicates."""

    model: str
    condition: str
    task_id: str
    n: int
    n_passed: int
    pass_rate: float
    # (p25, p50, p75) for each metric
    turns: tuple[float, float, float]
    tool_calls: tuple[float, float, float]
    cost_usd: tuple[float, float, float]
    latency_seconds: tuple[float, float, float]
    total_tokens: tuple[float, float, float]


def _p(xs: list[float]) -> tuple[float, float, float]:
    """(p25, p50, p75) over a non-empty list. Returns (x, x, x) for n=1."""
    if not xs:
        return (0.0, 0.0, 0.0)
    s = sorted(xs)
    n = len(s)
    if n == 1:
        return (s[0], s[0], s[0])
    def q(p: float) -> float:
        idx = p * (n - 1)
        lo = int(idx)
        frac = idx - lo
        if lo + 1 >= n:
            return s[-1]
        return s[lo] * (1 - frac) + s[lo + 1] * frac
    return (q(0.25), q(0.5), q(0.75))


def aggregate_cells(records: list[RunRecord]) -> list[CellStats]:
    """Group by (model, condition, task_id), aggregate replicates."""
    groups: dict[tuple[str, str, str], list[RunRecord]] = defaultdict(list)
    for r in records:
        groups[(r.model, r.condition, r.task_id)].append(r)

    out: list[CellStats] = []
    for (model, cond, task_id), rs in sorted(groups.items()):
        n = len(rs)
        n_passed = sum(r.passed for r in rs)
        out.append(
            CellStats(
                model=model,
                condition=cond,
                task_id=task_id,
                n=n,
                n_passed=n_passed,
                pass_rate=n_passed / n,
                turns=_p([r.turns for r in rs]),
                tool_calls=_p([r.tool_calls for r in rs]),
                cost_usd=_p([r.cost_usd for r in rs]),
                latency_seconds=_p([r.latency_seconds for r in rs]),
                total_tokens=_p(
                    [r.usage.input_tokens + r.usage.output_tokens for r in rs]
                ),
            )
        )
    return out


def write_aggregate_csv(records: list[RunRecord], out: Path) -> None:
    """One row per (model, condition, task) cell with replicate-aggregated stats."""
    cells = aggregate_cells(records)
    out.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "model", "condition", "task_id", "n", "n_passed", "pass_rate",
        "turns_p25", "turns_p50", "turns_p75",
        "tool_calls_p25", "tool_calls_p50", "tool_calls_p75",
        "cost_p25", "cost_p50", "cost_p75",
        "latency_p25", "latency_p50", "latency_p75",
        "tokens_p25", "tokens_p50", "tokens_p75",
    ]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for c in cells:
            w.writerow({
                "model": c.model, "condition": c.condition, "task_id": c.task_id,
                "n": c.n, "n_passed": c.n_passed, "pass_rate": f"{c.pass_rate:.3f}",
                "turns_p25": f"{c.turns[0]:.2f}", "turns_p50": f"{c.turns[1]:.2f}", "turns_p75": f"{c.turns[2]:.2f}",
                "tool_calls_p25": f"{c.tool_calls[0]:.2f}", "tool_calls_p50": f"{c.tool_calls[1]:.2f}", "tool_calls_p75": f"{c.tool_calls[2]:.2f}",
                "cost_p25": f"{c.cost_usd[0]:.6f}", "cost_p50": f"{c.cost_usd[1]:.6f}", "cost_p75": f"{c.cost_usd[2]:.6f}",
                "latency_p25": f"{c.latency_seconds[0]:.3f}", "latency_p50": f"{c.latency_seconds[1]:.3f}", "latency_p75": f"{c.latency_seconds[2]:.3f}",
                "tokens_p25": f"{c.total_tokens[0]:.0f}", "tokens_p50": f"{c.total_tokens[1]:.0f}", "tokens_p75": f"{c.total_tokens[2]:.0f}",
            })


# --- markdown ---


def summarize_markdown(records: list[RunRecord]) -> str:
    """Render headline table + pass matrix as markdown.

    When all cells have replicate==0 (n=1), the headline shows means.
    When some cells have replicates>1, the headline switches to a richer
    view with pass-rate (n_passed/n) and median values with p25-p75 ranges.
    """
    if not records:
        return "(no records)\n"

    max_rep = max(r.replicate for r in records)
    has_replicates = max_rep > 0

    if has_replicates:
        return _summarize_with_replicates(records)
    return _summarize_means(records)


def _summarize_means(records: list[RunRecord]) -> str:
    groups: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for r in records:
        groups[(r.model, r.condition)].append(r)

    lines = [
        "| model | condition | n | pass@1 | invalid/turn | mean_tokens | mean_cost_usd | mean_latency (s) |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for (model, cond), rs in sorted(groups.items()):
        n = len(rs)
        pass_rate = sum(r.passed for r in rs) / n
        invalid_rate = sum(r.invalid_tool_calls for r in rs) / max(
            sum(r.tool_calls for r in rs), 1
        )
        mean_tokens = statistics.mean(
            r.usage.input_tokens + r.usage.output_tokens for r in rs
        )
        mean_cost = statistics.mean(r.cost_usd for r in rs)
        mean_latency = statistics.mean(r.latency_seconds for r in rs)
        lines.append(
            f"| {model} | {cond} | {n} | {pass_rate:.1%} | {invalid_rate:.1%} | "
            f"{mean_tokens:,.0f} | ${mean_cost:.4f} | {mean_latency:.1f} |"
        )

    tasks = sorted({r.task_id for r in records})
    models = sorted({r.model for r in records})
    lines.append("\n## Pass matrix\n")
    lines.append("Each cell: pass-rate across conditions for that (task, model).\n")
    head = "| task | " + " | ".join(models) + " |"
    sep = "|---|" + "|".join(["---:"] * len(models)) + "|"
    lines.append(head)
    lines.append(sep)
    for task in tasks:
        row = [task]
        for model in models:
            entries = [r for r in records if r.task_id == task and r.model == model]
            if not entries:
                row.append("—")
            else:
                pr = sum(e.passed for e in entries) / len(entries)
                row.append(f"{pr:.0%}")
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def _summarize_with_replicates(records: list[RunRecord]) -> str:
    """Richer summary for runs with replicates > 1."""
    cells = aggregate_cells(records)
    by_mc: dict[tuple[str, str], list[CellStats]] = defaultdict(list)
    for c in cells:
        by_mc[(c.model, c.condition)].append(c)

    lines = [
        "| model | condition | tasks | reps/task | pass-rate | turns p50 (p25-p75) | cost p50 (p25-p75) | lat p50 (p25-p75) |",
        "|---|---|---:|---:|---:|---|---|---|",
    ]
    for (model, cond), cs in sorted(by_mc.items()):
        n_tasks = len(cs)
        reps = max(c.n for c in cs)
        mean_pass = statistics.mean(c.pass_rate for c in cs)
        turn_p50 = statistics.median(c.turns[1] for c in cs)
        turn_p25 = statistics.median(c.turns[0] for c in cs)
        turn_p75 = statistics.median(c.turns[2] for c in cs)
        cost_p50 = statistics.median(c.cost_usd[1] for c in cs)
        cost_p25 = statistics.median(c.cost_usd[0] for c in cs)
        cost_p75 = statistics.median(c.cost_usd[2] for c in cs)
        lat_p50 = statistics.median(c.latency_seconds[1] for c in cs)
        lat_p25 = statistics.median(c.latency_seconds[0] for c in cs)
        lat_p75 = statistics.median(c.latency_seconds[2] for c in cs)
        lines.append(
            f"| {model} | {cond} | {n_tasks} | {reps} | {mean_pass:.1%} | "
            f"{turn_p50:.1f} ({turn_p25:.1f}-{turn_p75:.1f}) | "
            f"${cost_p50:.4f} (${cost_p25:.4f}-${cost_p75:.4f}) | "
            f"{lat_p50:.1f}s ({lat_p25:.1f}-{lat_p75:.1f}) |"
        )

    lines.append("\n## Per-task pass-rate (n_passed/n_replicates)\n")
    tasks = sorted({c.task_id for c in cells})
    models = sorted({c.model for c in cells})
    head = "| task | " + " | ".join(models) + " |"
    sep = "|---|" + "|".join(["---:"] * len(models)) + "|"
    lines.append(head)
    lines.append(sep)
    for task in tasks:
        row = [task]
        for model in models:
            entries = [c for c in cells if c.task_id == task and c.model == model]
            if not entries:
                row.append("—")
            else:
                rates = [e.pass_rate for e in entries]
                if len(rates) == 1:
                    e = entries[0]
                    row.append(f"{e.n_passed}/{e.n}")
                else:
                    row.append(f"{min(rates):.0%}-{max(rates):.0%}")
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def write_markdown(records: list[RunRecord], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(summarize_markdown(records), encoding="utf-8")
