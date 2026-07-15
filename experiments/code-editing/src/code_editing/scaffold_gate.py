"""Paired analysis for the scaffold-value experiment."""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from pathlib import Path

from agent_eval.types import RunRecord


@dataclass(frozen=True)
class PairedEffect:
    arm: str
    pass_rate_delta: float
    pass_rate_delta_ci95: tuple[float, float]
    mean_cost_delta_usd: float
    mean_latency_delta_seconds: float
    mean_turn_delta: float
    wins: int
    ties: int
    losses: int


@dataclass(frozen=True)
class ScaffoldGateAnalysis:
    control: str
    completed_tasks: tuple[str, ...]
    arm_pass_rate: dict[str, float]
    arm_mean_cost_usd: dict[str, float]
    arm_cost_per_resolved_usd: dict[str, float | None]
    arm_mean_latency_seconds: dict[str, float]
    arm_mean_turns: dict[str, float]
    arm_failure_modes: dict[str, dict[str, int]]
    effects: dict[str, PairedEffect]


def analyze_scaffold_gate(
    records: list[RunRecord],
    *,
    control: str = "minimal_free_loop_v1",
    bootstrap_samples: int = 5_000,
    seed: int = 0,
) -> ScaffoldGateAnalysis | None:
    """Aggregate replicates within task, then compare arms on shared tasks."""
    cells: dict[str, dict[str, list[RunRecord]]] = {}
    for record in records:
        cells.setdefault(record.condition, {}).setdefault(record.task_id, []).append(record)
    if control not in cells or len(cells) < 2:
        return None

    completed = sorted(set.intersection(*(set(tasks) for tasks in cells.values())))
    if not completed:
        return None

    def task_pass(arm: str, task: str) -> float:
        return statistics.mean(float(record.passed) for record in cells[arm][task])

    def task_cost(arm: str, task: str) -> float:
        return statistics.mean(record.cost_usd for record in cells[arm][task])

    def task_latency(arm: str, task: str) -> float:
        return statistics.mean(record.latency_seconds for record in cells[arm][task])

    def task_turns(arm: str, task: str) -> float:
        return statistics.mean(record.turns for record in cells[arm][task])

    arm_pass_rate = {
        arm: statistics.mean(task_pass(arm, task) for task in completed)
        for arm in cells
    }
    arm_mean_cost_usd = {
        arm: statistics.mean(task_cost(arm, task) for task in completed)
        for arm in cells
    }
    arm_cost_per_resolved_usd = {
        arm: (
            arm_mean_cost_usd[arm] / arm_pass_rate[arm]
            if arm_pass_rate[arm] > 0
            else None
        )
        for arm in cells
    }
    arm_mean_latency_seconds = {
        arm: statistics.mean(task_latency(arm, task) for task in completed)
        for arm in cells
    }
    arm_mean_turns = {
        arm: statistics.mean(task_turns(arm, task) for task in completed)
        for arm in cells
    }
    arm_failure_modes: dict[str, dict[str, int]] = {}
    for arm, tasks in cells.items():
        counts: dict[str, int] = {}
        for task in completed:
            for record in tasks[task]:
                if record.passed:
                    continue
                mode = str(record.extra.get("failure_mode") or "unclassified")
                counts[mode] = counts.get(mode, 0) + 1
        arm_failure_modes[arm] = counts

    effects: dict[str, PairedEffect] = {}
    for arm in cells:
        if arm == control:
            continue
        pass_diffs = [
            task_pass(arm, task) - task_pass(control, task) for task in completed
        ]
        cost_diffs = [
            task_cost(arm, task) - task_cost(control, task) for task in completed
        ]
        latency_diffs = [
            task_latency(arm, task) - task_latency(control, task)
            for task in completed
        ]
        turn_diffs = [
            task_turns(arm, task) - task_turns(control, task)
            for task in completed
        ]
        rng = random.Random(f"{seed}:{arm}")
        boot: list[float] = []
        for _ in range(max(1, bootstrap_samples)):
            sampled = [rng.choice(pass_diffs) for _ in pass_diffs]
            boot.append(statistics.mean(sampled))
        boot.sort()
        lo = boot[int(0.025 * (len(boot) - 1))]
        hi = boot[int(0.975 * (len(boot) - 1))]
        effects[arm] = PairedEffect(
            arm=arm,
            pass_rate_delta=statistics.mean(pass_diffs),
            pass_rate_delta_ci95=(lo, hi),
            mean_cost_delta_usd=statistics.mean(cost_diffs),
            mean_latency_delta_seconds=statistics.mean(latency_diffs),
            mean_turn_delta=statistics.mean(turn_diffs),
            wins=sum(diff > 0 for diff in pass_diffs),
            ties=sum(diff == 0 for diff in pass_diffs),
            losses=sum(diff < 0 for diff in pass_diffs),
        )

    return ScaffoldGateAnalysis(
        control=control,
        completed_tasks=tuple(completed),
        arm_pass_rate=arm_pass_rate,
        arm_mean_cost_usd=arm_mean_cost_usd,
        arm_cost_per_resolved_usd=arm_cost_per_resolved_usd,
        arm_mean_latency_seconds=arm_mean_latency_seconds,
        arm_mean_turns=arm_mean_turns,
        arm_failure_modes=arm_failure_modes,
        effects=effects,
    )


def render_scaffold_gate(analysis: ScaffoldGateAnalysis) -> str:
    """Render an evidence-calibrated markdown report."""
    lines = [
        "# Scaffold-value gate",
        "",
        f"Control: `{analysis.control}`",
        f"Tasks completed by every arm: {len(analysis.completed_tasks)}",
        "",
        "## Arm outcomes",
        "",
        "| arm | pass rate | mean cost/task | cost/resolved | mean latency | mean turns |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm in sorted(analysis.arm_pass_rate):
        cost_per_resolved = analysis.arm_cost_per_resolved_usd[arm]
        rendered_cpr = (
            f"${cost_per_resolved:.4f}" if cost_per_resolved is not None else "—"
        )
        lines.append(
            f"| `{arm}` | {analysis.arm_pass_rate[arm]:.1%} | "
            f"${analysis.arm_mean_cost_usd[arm]:.4f} | {rendered_cpr} | "
            f"{analysis.arm_mean_latency_seconds[arm]:.1f}s | "
            f"{analysis.arm_mean_turns[arm]:.1f} |"
        )

    lines += [
        "",
        "## Paired effects vs control",
        "",
        "| arm | Δ pass rate | paired bootstrap 95% interval | Δ cost/task | Δ latency | Δ turns | W/T/L |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in sorted(analysis.effects):
        effect = analysis.effects[arm]
        lines.append(
            f"| `{arm}` | {effect.pass_rate_delta:+.1%} | "
            f"[{effect.pass_rate_delta_ci95[0]:+.1%}, "
            f"{effect.pass_rate_delta_ci95[1]:+.1%}] | "
            f"${effect.mean_cost_delta_usd:+.4f} | "
            f"{effect.mean_latency_delta_seconds:+.1f}s | "
            f"{effect.mean_turn_delta:+.1f} | "
            f"{effect.wins}/{effect.ties}/{effect.losses} |"
        )

    lines += ["", "## Failed-trial modes", ""]
    for arm in sorted(analysis.arm_failure_modes):
        counts = analysis.arm_failure_modes[arm]
        rendered = ", ".join(
            f"`{mode}`: {count}" for mode, count in sorted(counts.items())
        )
        lines.append(f"- `{arm}` — {rendered or 'none'}")

    lines += [
        "",
        "## Interpretation",
        "",
        "This is a paired scaffold comparison, not a leaderboard result. A scaffold "
        "earns the next optimization stage only if it improves resolved rate with "
        "uncertainty excluding zero, or is Pareto-better on resolved rate and cost. "
        "Pin task IDs, model settings, prompt versions, and environment before a "
        "confirmatory run.",
    ]
    return "\n".join(lines) + "\n"


def write_scaffold_gate(analysis: ScaffoldGateAnalysis, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_scaffold_gate(analysis), encoding="utf-8")


__all__ = [
    "PairedEffect",
    "ScaffoldGateAnalysis",
    "analyze_scaffold_gate",
    "render_scaffold_gate",
    "write_scaffold_gate",
]
