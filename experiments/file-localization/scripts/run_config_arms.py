"""Config-arm oracle-gap diagnostic for the localization phase.

The thesis says: choose the config bundle {model x prompt x context-strategy}
PER PHASE instead of using one config for the whole task. This script answers
one narrow prerequisite question cheaply:

    Is there any oracle routing headroom on this task sample?

This is an optimistic, in-sample upper bound. It is not evidence that a router
can identify the winning arm from deploy-time features, and a single phase
cannot establish that heterogeneous per-phase configs beat one end-to-end
config. A positive gap is necessary but not sufficient evidence for routing.

How it works: run the localization trial across an arm grid (models x context
policies) on N SWE-bench tasks, with `emit_session_dir` so every run drops a
SessionTrace (root + one `localize` node carrying the composite reward + the
config bundle). Then compare:

  - best_single   = max over arms of (mean composite across tasks)   [in-sample]
  - oracle_select = mean over tasks of (max composite across arms)   [oracle ceiling]
  - headroom      = oracle_select - best_single                      [oracle gap]

The paired bootstrap interval resamples tasks and recomputes both quantities.

Also reports a cost-aware view (composite per dollar) since a cheap arm that
ties an expensive one is itself a per-phase-selection win.

Usage:
    cd /Users/antoine/Development/research/agent-bench
    # see the plan + arm grid without spending anything:
    uv run --package file-localization python \\
        experiments/file-localization/scripts/run_config_arms.py --dry-run --n-tasks 5
    # run for real (needs ANTHROPIC_API_KEY; ~$0.2-2 at defaults):
    uv run --package file-localization python \\
        experiments/file-localization/scripts/run_config_arms.py \\
        --n-tasks 5 --budget 5 --out results/config_arms
"""

from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from agent_eval import (
    KeepEverything,
    SessionTrace,
    ToolResultElision,
    make_model,
)
from agent_eval.context.types import ContextPolicy
from agent_eval.reports import write_csv
from agent_eval.tracing import setup_tracing, shutdown_tracing
from agent_eval.types import RunRecord

from file_localization.adapters import load_swebench, to_localization_tasks
from file_localization.difficulty import load_swebench_band
from file_localization.repos import prepare as prepare_repo
from file_localization.turn_loop_trial import LocalRepoView, make_turn_loop_trial


def _load_env() -> None:
    for parent in (
        Path(__file__).resolve().parents[3] / ".env",
        Path.home() / "Development" / ".env",
        Path.home() / ".env",
    ):
        if parent.is_file():
            load_dotenv(parent, override=False)


@dataclass(frozen=True)
class Arm:
    """One config bundle = one point in the {model x context-strategy} grid.

    (Backend/prompt is left at the model's YAML default for this first cut, so
    the varied axes are model and context-strategy. The PhaseConfig the trial
    emits records all three.)
    """

    label: str
    model: str
    context_label: str
    _policy_factory: Callable[[], ContextPolicy]

    def policy(self) -> ContextPolicy:
        return self._policy_factory()


@dataclass
class Headroom:
    """In-sample oracle routing ceiling; not a learned selector estimate."""

    completed: list[str]  # tasks every arm finished (fair comparison)
    arm_mean: dict[str, float]  # per-arm mean composite over completed tasks
    arm_cost: dict[str, float]  # per-arm mean cost
    best_single_arm: str
    best_single: float  # best fixed config's mean composite
    oracle_select: float  # mean over tasks of the best arm per task
    headroom: float  # oracle_select - best_single (>= 0 by construction)
    headroom_ci95: tuple[float, float]  # paired task-bootstrap interval


def headroom_analysis(
    arm_labels: list[str],
    composite: dict[str, dict[str, float]],
    cost: dict[str, dict[str, float]],
    *,
    bootstrap_samples: int = 2_000,
    seed: int = 0,
) -> Headroom | None:
    """Pure analysis (no I/O) so the headline math is unit-tested.

    Restricts to tasks completed by EVERY arm so the comparison is fair.
    Returns None if no task was completed by all arms.

    `headroom` is mathematically >= 0. It is deliberately presented as a
    ceiling, not a routing result: the winning arm uses observed rewards.
    """
    per_arm_tasks = [set(composite.get(label, {})) for label in arm_labels]
    if not per_arm_tasks or any(not s for s in per_arm_tasks):
        return None
    completed = sorted(set.intersection(*per_arm_tasks))
    if not completed:
        return None

    arm_mean = {
        label: statistics.mean(composite[label][t] for t in completed)
        for label in arm_labels
    }
    arm_cost = {
        label: statistics.mean(cost[label][t] for t in completed)
        for label in arm_labels
    }
    best_single_arm = max(arm_mean, key=arm_mean.get)
    best_single = arm_mean[best_single_arm]
    oracle_select = statistics.mean(
        max(composite[label][t] for label in arm_labels) for t in completed
    )
    rng = random.Random(seed)
    bootstrap_gaps: list[float] = []
    for _ in range(max(1, bootstrap_samples)):
        sample = [rng.choice(completed) for _ in completed]
        sampled_arm_means = {
            label: statistics.mean(composite[label][task] for task in sample)
            for label in arm_labels
        }
        sampled_best_fixed = max(sampled_arm_means.values())
        sampled_oracle = statistics.mean(
            max(composite[label][task] for label in arm_labels) for task in sample
        )
        bootstrap_gaps.append(sampled_oracle - sampled_best_fixed)
    bootstrap_gaps.sort()
    lo_idx = int(0.025 * (len(bootstrap_gaps) - 1))
    hi_idx = int(0.975 * (len(bootstrap_gaps) - 1))
    return Headroom(
        completed=completed,
        arm_mean=arm_mean,
        arm_cost=arm_cost,
        best_single_arm=best_single_arm,
        best_single=best_single,
        oracle_select=oracle_select,
        headroom=oracle_select - best_single,
        headroom_ci95=(bootstrap_gaps[lo_idx], bootstrap_gaps[hi_idx]),
    )


def default_arms(models: list[str]) -> list[Arm]:
    arms: list[Arm] = []
    for m in models:
        # ToolResultElision currently understands Anthropic message blocks only;
        # avoid duplicate no-op arms for other providers.
        ctx: list[tuple[str, Callable[[], ContextPolicy]]] = [
            ("keep_everything", KeepEverything)
        ]
        if m.startswith("claude"):
            ctx.append(
                ("tool_result_elision_2", lambda: ToolResultElision(keep_recent=2))
            )
        for clabel, factory in ctx:
            arms.append(
                Arm(
                    label=f"{m}|{clabel}",
                    model=m,
                    context_label=clabel,
                    _policy_factory=factory,
                )
            )
    return arms


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--models", nargs="+", default=["claude-haiku-4-5", "claude-sonnet-4-6"]
    )
    p.add_argument("--n-tasks", type=int, default=5)
    p.add_argument("--dataset", default="verified")
    p.add_argument(
        "--difficulty-band",
        choices=["all", "unsolved", "hard", "medium", "easy"],
        default="hard",
        help="model-solvability band; defaults away from saturated easy tasks",
    )
    p.add_argument(
        "--difficulty-csv",
        type=Path,
        default=(
            Path(__file__).resolve().parents[3]
            / "lib/agent-eval-core/data/swebench_verified_difficulty.csv"
        ),
    )
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--top-k", type=int, default=20)
    p.add_argument(
        "--budget", type=float, default=5.0, help="USD cap; stop before exceeding"
    )
    p.add_argument("--out", type=Path, default=Path("results/config_arms"))
    p.add_argument(
        "--dry-run", action="store_true", help="print the plan + arm grid; no API calls"
    )
    args = p.parse_args()

    _load_env()
    arms = default_arms(args.models)

    print(f"arms ({len(arms)}):")
    for a in arms:
        print(f"  - {a.label}")
    print(
        f"tasks: SWE-bench {args.dataset}, band={args.difficulty_band}, "
        f"n={args.n_tasks}, seed={args.seed}"
    )
    print(
        f"grid: {len(arms)} arms x {args.n_tasks} tasks = {len(arms) * args.n_tasks} trials"
    )
    print(f"budget cap: ${args.budget:.2f}")

    if args.dry_run:
        print(
            "\n[dry-run] no tasks loaded, no API calls. Re-run without --dry-run to execute."
        )
        return 0

    required_keys = set()
    for model in args.models:
        if model.startswith("claude"):
            required_keys.add("ANTHROPIC_API_KEY")
        elif model.startswith("gpt"):
            required_keys.add("OPENAI_API_KEY")
        elif model.startswith("gemini"):
            required_keys.add("GEMINI_API_KEY")
        else:
            required_keys.add("OPENROUTER_API_KEY")
    missing_keys = sorted(key for key in required_keys if key not in os.environ)
    if missing_keys:
        print(f"ERROR: missing {', '.join(missing_keys)}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    setup_tracing(out_path=args.out / "traces.jsonl")

    print(f"\nloading SWE-bench {args.dataset} tasks...", flush=True)
    if args.difficulty_band == "all":
        raw = load_swebench(args.dataset, split="test")[: args.n_tasks]
        tasks = to_localization_tasks(raw)
    else:
        tasks = load_swebench_band(
            args.difficulty_band,
            csv_path=args.difficulty_csv,
            dataset=args.dataset,
            n=args.n_tasks,
            seed=args.seed,
        )

    cache: dict[str, LocalRepoView] = {}

    def repo_view_for(task):
        key = f"{task.repo}@{task.base_commit}"
        if key not in cache:
            print(f"  cloning {task.repo}@{task.base_commit[:12]}...", flush=True)
            cache[key] = LocalRepoView(prepare_repo(task.repo, task.base_commit))
        return cache[key]

    trial = make_turn_loop_trial(
        repo_view_for=repo_view_for,
        top_k=args.top_k,
        transcripts_dir=args.out / "transcripts",
        emit_session_dir=args.out / "sessions",
    )

    # composite[arm_label][task_id] = reward value (from the emitted SessionTrace)
    composite: dict[str, dict[str, float]] = {a.label: {} for a in arms}
    cost: dict[str, dict[str, float]] = {a.label: {} for a in arms}
    records: list[RunRecord] = []
    spent = 0.0
    stopped = False

    for a in arms:
        if stopped:
            break
        print(f"\n=== arm: {a.label} ===", flush=True)
        for task in tasks:
            if spent >= args.budget:
                print(
                    f"  [budget] stopping: ${spent:.2f} >= ${args.budget:.2f}",
                    flush=True,
                )
                stopped = True
                break
            handle = make_model(a.model, context_policy=a.policy())
            print(f"  {task.instance_id}...", end="", flush=True)
            rec = trial(handle, a.label, task)
            records.append(rec)
            spent += rec.cost_usd

            # Pull the reward straight from the emitted SessionTrace — the
            # whole point of Step 1 is that the trace is the source of truth.
            reward = None
            spath = (rec.extra or {}).get("session_path")
            if spath:
                node = SessionTrace.from_jsonl(spath).phase_nodes("localize")[0]
                reward = node.reward.value
            reward = (
                reward
                if reward is not None
                else (rec.extra or {}).get("composite", 0.0)
            )
            composite[a.label][task.task_id] = reward
            cost[a.label][task.task_id] = rec.cost_usd
            print(
                f" composite={reward:.3f} passed={rec.passed} cost=${rec.cost_usd:.4f} "
                f"(spent ${spent:.2f})",
                flush=True,
            )

    write_csv(records, args.out / "per_trial.csv")
    shutdown_tracing()

    # ---- the headline analysis (pure fn, unit-tested) ----
    h = headroom_analysis([a.label for a in arms], composite, cost, seed=args.seed)

    lines = [
        f"# Localization config arms — oracle-gap diagnostic ({len(arms)} arms)",
        "",
        f"Arms: {', '.join(a.label for a in arms)}",
        f"Tasks fully covered by every arm: {len(h.completed) if h else 0}"
        + (
            f" (of {args.n_tasks} requested)"
            if (not h or len(h.completed) != args.n_tasks)
            else ""
        ),
        f"Total spent: ${spent:.2f}" + (" — budget-stopped early" if stopped else ""),
        "",
    ]

    if h is None:
        lines.append(
            "No task was completed by every arm (budget cut off too early). "
            "Re-run with a higher --budget or fewer arms/tasks."
        )
        (args.out / "headroom.md").write_text("\n".join(lines) + "\n")
        print("\n".join(lines))
        print(f"\nwrote: {args.out}/per_trial.csv, headroom.md (incomplete)")
        return 0

    lines += [
        "## Per-arm (fixed config)",
        "",
        "| arm | mean composite | mean cost | composite/$ |",
        "|---|---:|---:|---:|",
    ]
    for a in arms:
        cpd = (
            h.arm_mean[a.label] / h.arm_cost[a.label]
            if h.arm_cost[a.label] > 0
            else 0.0
        )
        star = " ⭐" if a.label == h.best_single_arm else ""
        lines.append(
            f"| `{a.label}`{star} | {h.arm_mean[a.label]:.3f} | ${h.arm_cost[a.label]:.4f} | {cpd:.1f} |"
        )

    lines += [
        "",
        "## The headline",
        "",
        f"- **best single config** (`{h.best_single_arm}`): **{h.best_single:.3f}**",
        f"- **per-task oracle selection**: **{h.oracle_select:.3f}**",
        f"- **headroom** (oracle − best single): **{h.headroom:+.3f}**",
        (
            "- **paired task-bootstrap 95% interval**: "
            f"**[{h.headroom_ci95[0]:+.3f}, {h.headroom_ci95[1]:+.3f}]**"
        ),
        "",
    ]
    if h.headroom <= 1e-6:
        lines.append(
            "**Verdict: no headroom.** The best fixed config ties the per-task "
            "oracle on this set — a per-phase config bandit cannot help here. "
            "The tasks may still be too uniform or the arms too similar."
        )
    else:
        lines.append(
            f"**Verdict: {h.headroom:+.3f} headroom exists.** Picking the config "
            "after observing its reward beats the best in-sample fixed config. "
            "This is only an oracle ceiling: it does not show that deploy-time "
            "task/state features predict the winning arm, and it does not test "
            "cross-phase heterogeneity. Next require a held-out router result "
            "inside the end-to-end phased-vs-free-loop experiment."
        )

    (args.out / "headroom.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\nwrote: {args.out}/per_trial.csv, headroom.md, sessions/, traces.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
