"""Tier-1 context-policy ablation on file-localization.

Holds (model, backend, task) fixed; varies only the ContextPolicy across
3 conditions. The same 3 tasks run under each policy; we compare:

  - pass-rate (does pruning hurt accuracy?)
  - mean cost (does pruning save money?)
  - cache_hit_rate (does pruning break the prompt cache?)
  - peak_input_tokens (does pruning actually bound the context?)
  - failure_mode shifts (does context_amnesia rise? does anything else?)

Output: one combined CSV + a markdown summary contrasting the 3 policies.

Usage:
    cd /Users/antoine/Development/research/agent-bench
    uv run --with-editable experiments/file-localization python \\
        experiments/file-localization/scripts/run_context_ablation.py \\
        --model claude-haiku-4-5 \\
        --n-tasks 3 \\
        --out results/ctx_ablation
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent_eval import (
    KeepEverything,
    Sweep,
    SlidingWindow,
    ToolResultElision,
    make_model,
)
from agent_eval.reports import write_csv, write_markdown
from agent_eval.tracing import setup_tracing, shutdown_tracing
from agent_eval.types import ModelHandle, RunRecord

from file_localization.adapters import load_swebench, to_localization_tasks
from file_localization.repos import prepare as prepare_repo
from file_localization.turn_loop_trial import LocalRepoView, make_turn_loop_trial


def _load_env() -> None:
    for parent in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        env = parent / ".env"
        if env.exists():
            load_dotenv(env, override=False)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default="claude-haiku-4-5")
    p.add_argument("--n-tasks", type=int, default=3)
    p.add_argument("--out", type=Path, default=Path("results/ctx_ablation"))
    args = p.parse_args()

    _load_env()
    if "ANTHROPIC_API_KEY" not in os.environ:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    setup_tracing(out_path=args.out / "traces.jsonl")

    # Three policies — the Tier-1 lineup.
    policies = [
        ("keep_everything", KeepEverything()),
        ("tool_result_elision_2", ToolResultElision(keep_recent=2)),
        ("sliding_window_5", SlidingWindow(n_turns=5)),
    ]

    print(f"loading SWE-Bench Lite first {args.n_tasks} tasks...", flush=True)
    raw = load_swebench("lite", split="test")[: args.n_tasks]
    tasks = to_localization_tasks(raw)

    cache: dict[str, LocalRepoView] = {}

    def repo_view_for(task):
        key = f"{task.repo}@{task.base_commit}"
        if key not in cache:
            print(f"  cloning {task.repo}@{task.base_commit[:12]}...", flush=True)
            cache[key] = LocalRepoView(prepare_repo(task.repo, task.base_commit))
        return cache[key]

    trial = make_turn_loop_trial(
        repo_view_for=repo_view_for,
        top_k=20,
        transcripts_dir=args.out / "transcripts",
    )

    # Run each (policy, task) cell. Build a fresh ModelHandle per cell so
    # context-history doesn't bleed between runs.
    records: list[RunRecord] = []
    for policy_label, policy in policies:
        print(f"\n=== policy: {policy_label} ===", flush=True)
        for task in tasks:
            handle = make_model(args.model, context_policy=policy)
            print(f"  {task.instance_id}...", end="", flush=True)
            rec = trial(handle, policy_label, task)
            records.append(rec)
            extra = rec.extra or {}
            print(
                f" passed={rec.passed} cost=${rec.cost_usd:.4f} "
                f"turns={rec.turns} peak_in={extra.get('peak_input_tokens', 0):,} "
                f"cache_hit={extra.get('cache_hit_rate', 0):.0%} "
                f"mode={extra.get('failure_mode') or '—'}",
                flush=True,
            )

    write_csv(records, args.out / "per_trial.csv")
    shutdown_tracing()

    # Per-policy summary.
    print("\n" + "=" * 78)
    print(f"{'policy':<28} | pass | cost     | peak_in | cache% | wasted% | mode-mix")
    print("-" * 100)
    summary_lines: list[str] = [
        f"# Context-policy ablation — {args.model}",
        "",
        f"N={args.n_tasks} tasks × {len(policies)} policies = {len(records)} trials.",
        "Same tasks, same model, same backend — only the context policy varies.",
        "",
        "| policy | pass | mean cost | peak in p50 | cache% | wasted% | failure modes |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for policy_label, _ in policies:
        sub = [r for r in records if r.condition == policy_label]
        if not sub:
            continue
        pass_rate = sum(r.passed for r in sub) / len(sub)
        mean_cost = statistics.mean(r.cost_usd for r in sub)
        peak_in_p50 = statistics.median(
            (r.extra or {}).get("peak_input_tokens", 0) for r in sub
        )
        cache_pct = statistics.mean(
            (r.extra or {}).get("cache_hit_rate", 0.0) for r in sub
        )
        wasted_pct = statistics.mean(
            (r.extra or {}).get("wasted_turn_fraction", 0.0) for r in sub
        )
        modes = [(r.extra or {}).get("failure_mode") for r in sub if not r.passed]
        mode_str = ", ".join(f"`{m}`" for m in modes if m) or "—"

        line = (
            f"{policy_label:<28} | {pass_rate:>4.0%} | ${mean_cost:>7.4f} | "
            f"{peak_in_p50:>7,.0f} | {cache_pct:>5.0%} | {wasted_pct:>6.0%} | {mode_str}"
        )
        print(line)
        summary_lines.append(
            f"| `{policy_label}` | {pass_rate:.0%} | ${mean_cost:.4f} | "
            f"{peak_in_p50:,.0f} | {cache_pct:.0%} | {wasted_pct:.0%} | {mode_str} |"
        )

    (args.out / "ablation.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    write_markdown(records, args.out / "full_summary.md")
    print(f"\nwrote: {args.out}/per_trial.csv, ablation.md, full_summary.md, traces.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
