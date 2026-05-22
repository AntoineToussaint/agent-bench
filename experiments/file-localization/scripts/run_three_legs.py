"""Run three legs on a small SWE-Bench Lite subset:
    1. one-shot structured (FILE: lines)
    2. turn-loop tool_use
    3. claude-code (production agent)

Each task gets a real repo clone at base_commit. Predicted files are scored
against the gold patch's file set.

Usage:
    cd /Users/antoine/Development/research/agent-bench
    uv run --package file-localization python \
        experiments/file-localization/scripts/run_three_legs.py \
        --n-tasks 1 --model claude-haiku-4-5 --out-dir results/three_legs_smoke

After it runs, see:
    <out_dir>/per_trial.csv          per-record (one row per leg per task)
    <out_dir>/per_cell.csv           aggregated stats
    <out_dir>/summary.md             markdown headline + per-task matrix
    <out_dir>/transcripts/*.json     one transcript per (leg, task)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent_eval import Sweep, dump_transcript
from agent_eval.reports import write_aggregate_csv, write_csv, write_markdown

from file_localization.adapters import load_swebench, to_localization_tasks
from file_localization.llm_trial import make_llm_trial
from file_localization.turn_loop_trial import LocalRepoView, make_turn_loop_trial
from file_localization.agent_cli_trial import is_available, make_claude_code_trial
from file_localization.contract import LocalizationTask
from file_localization.repos import prepare as prepare_repo


def _resolve_env() -> None:
    """Load env from project root + parent dirs (for shared ~/Development/.env)."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        env = parent / ".env"
        if env.exists():
            load_dotenv(env, override=False)


def _build_repo_view_for():
    """Returns a callable LocalizationTask -> LocalRepoView backed by a real clone."""
    cache: dict[str, LocalRepoView] = {}

    def repo_view_for(task: LocalizationTask) -> LocalRepoView:
        key = f"{task.repo}@{task.base_commit}"
        if key in cache:
            return cache[key]
        print(f"  cloning {task.repo} @ {task.base_commit[:12]}...", flush=True)
        path = prepare_repo(task.repo, task.base_commit)
        view = LocalRepoView(path)
        cache[key] = view
        return view

    return repo_view_for


def _smoke_subset(n: int, *, only_repo: str | None = None) -> list[LocalizationTask]:
    """Pick the first N SWE-Bench Lite tasks (optionally filtered by repo)."""
    print(f"loading SWE-Bench Lite (split=test)...", flush=True)
    raw = load_swebench("lite", split="test")
    if only_repo:
        raw = [r for r in raw if r.repo == only_repo]
    raw = raw[:n]
    print(f"  using {len(raw)} task(s)")
    for r in raw:
        print(f"    - {r.instance_id} ({r.repo})")
    return to_localization_tasks(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-tasks", type=int, default=1, help="how many SWE-Bench Lite tasks to use")
    parser.add_argument("--only-repo", default=None, help="restrict to one repo (e.g. 'astropy/astropy')")
    parser.add_argument("--model", default="claude-haiku-4-5", help="model for one-shot and turn-loop legs")
    parser.add_argument("--repetitions", type=int, default=1, help="repeat each cell N times (averages)")
    parser.add_argument("--out-dir", default="results/three_legs", help="output directory under repo root")
    parser.add_argument("--skip-claude-code", action="store_true", help="skip the claude-code leg")
    parser.add_argument("--max-turns", type=int, default=10, help="agent loop turn cap")
    args = parser.parse_args()

    _resolve_env()
    if "ANTHROPIC_API_KEY" not in os.environ:
        print("ERROR: ANTHROPIC_API_KEY not set. Put it in .env or export it.", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    transcripts_dir = out_dir / "transcripts"

    have_claude_code = is_available("claude") and not args.skip_claude_code
    print(f"claude-code CLI available: {have_claude_code}")

    tasks = _smoke_subset(args.n_tasks, only_repo=args.only_repo)
    if not tasks:
        print("No tasks matched. Try --n-tasks 1 (no filter) or pick a valid --only-repo.", file=sys.stderr)
        return 2

    repo_view_for = _build_repo_view_for()

    # Three Trial functions. We dispatch by `condition` inside one wrapper so
    # the sweep can route to whichever leg the cell names.
    one_shot = make_llm_trial(top_k=20)
    turn_loop = make_turn_loop_trial(
        repo_view_for=repo_view_for,
        top_k=20,
        transcripts_dir=transcripts_dir,
    )
    claude_code = (
        make_claude_code_trial(repo_view_for=repo_view_for, top_k=20)
        if have_claude_code
        else None
    )

    def trial(client, condition, task):
        if condition == "one-shot":
            return one_shot(client, condition, task)
        if condition == "turn-loop":
            return turn_loop(client, condition, task)
        if condition == "claude-code":
            assert claude_code is not None
            return claude_code(client, condition, task)
        raise ValueError(f"unknown condition: {condition}")

    conditions = ["one-shot", "turn-loop"]
    if have_claude_code:
        conditions.append("claude-code")

    print(f"\nrunning {len(tasks)} task(s) x {len(conditions)} condition(s) "
          f"x {args.repetitions} replicate(s)... ({len(tasks)*len(conditions)*args.repetitions} trials)")

    def on_progress(i, total, rec):
        score_extra = rec.extra or {}
        recall = score_extra.get("recall", 0.0)
        n_pred = score_extra.get("n_predicted", 0)
        print(
            f"  [{i}/{total}] {rec.task_id} / {rec.condition} / rep{rec.replicate}: "
            f"passed={rec.passed} recall={recall:.2f} predicted={n_pred} "
            f"turns={rec.turns} tokens={rec.usage.input_tokens + rec.usage.output_tokens} "
            f"cost=${rec.cost_usd:.4f} {rec.latency_seconds:.1f}s"
            + (f" ERROR={rec.error}" if rec.error else "")
        )

    sweep = Sweep(
        models=[args.model],
        conditions=conditions,
        tasks=tasks,
        trial=trial,
        repetitions=args.repetitions,
        on_progress=on_progress,
    )
    records = sweep.run()

    write_csv(records, out_dir / "per_trial.csv")
    write_aggregate_csv(records, out_dir / "per_cell.csv")
    write_markdown(records, out_dir / "summary.md")

    # Persist transcripts for offline inspection. The trials build them
    # internally but don't currently surface them on the RunRecord; for now
    # we write only summary records here (full transcripts get written
    # when the trial is called via run() with a transcripts_dir wired in).
    print(f"\nwrote results to {out_dir}/")
    print(f"  per_trial.csv  ({len(records)} rows)")
    print(f"  per_cell.csv")
    print(f"  summary.md")
    print()
    md = (out_dir / "summary.md").read_text()
    print(md[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
