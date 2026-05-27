"""Cross-experiment capability scorecard.

Runs one model across a small slice of every experiment in the
monorepo and writes a one-page summary:

    capability         pass-rate  cost  latency
    edit  (code)       66.7%       $0.18    14.3s
    plan  (tool-use)   80.0%       $0.04     2.1s
    find  (locate)     100%        $0.07    11.6s

The point isn't to benchmark a model (each cell is N=3 by default);
it's to validate that all three experiments still wire end-to-end
through the shared `agent-eval-core` plumbing — and to give a single
"is this model worth a real sweep?" go/no-go signal.

For real benchmarking, run each experiment's own sweep script.

Usage:
    uv run python scripts/run_all_experiments.py \\
        --model claude-haiku-4-5 \\
        --out results/scorecard_haiku

    # bigger slice (slower)
    uv run python scripts/run_all_experiments.py \\
        --model claude-sonnet-4-6 \\
        --n 5 \\
        --out results/scorecard_sonnet
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from agent_eval import Sweep, make_model
from agent_eval.reports import write_csv, write_markdown
from agent_eval.tracing import setup_tracing, shutdown_tracing
from agent_eval.types import ModelHandle, RunRecord


def _load_env() -> None:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        env = parent / ".env"
        if env.exists():
            load_dotenv(env, override=False)


# ============ file-localization slice ============


def _run_localize(model: str, n: int, out_dir: Path) -> list[RunRecord]:
    from file_localization.adapters import load_swebench, to_localization_tasks
    from file_localization.repos import prepare as prepare_repo
    from file_localization.turn_loop_trial import (
        LocalRepoView,
        make_turn_loop_trial,
    )

    raw = load_swebench("lite", split="test")[:n]
    tasks = to_localization_tasks(raw)

    cache: dict[str, LocalRepoView] = {}

    def repo_view_for(task):
        key = f"{task.repo}@{task.base_commit}"
        if key not in cache:
            cache[key] = LocalRepoView(prepare_repo(task.repo, task.base_commit))
        return cache[key]

    trial = make_turn_loop_trial(
        repo_view_for=repo_view_for,
        top_k=20,
        transcripts_dir=out_dir / "localize" / "transcripts",
    )

    def trial_fn(handle: ModelHandle, condition: str, task):
        return trial(handle, condition, task)

    sweep = Sweep(
        models=[model],
        conditions=["localize"],
        tasks=tasks,
        trial=trial_fn,
        repetitions=1,
    )
    return sweep.run()


# ============ tool-selection slice ============


def _run_select(model: str, n: int, out_dir: Path) -> list[RunRecord]:
    from tool_selection.adapters import tasks_by_difficulty
    from tool_selection.approaches.full import FullApproach
    from tool_selection.catalogs import get_catalog
    from tool_selection.phases.one_phase import OnePhase
    from tool_selection.trial import make_trial

    easy = tasks_by_difficulty().get("easy", [])[:n]
    if not easy:
        print("  no easy tool-selection tasks found", file=sys.stderr)
        return []

    catalog = get_catalog("narrow")
    trial = make_trial(FullApproach(), catalog, OnePhase())

    sweep = Sweep(
        models=[model],
        conditions=["select"],
        tasks=easy,
        trial=trial,
        repetitions=1,
    )
    return sweep.run()


# ============ code-editing slice ============


def _run_edit(model: str, n: int, out_dir: Path) -> list[RunRecord]:
    from code_editing.bench import discover_tasks, run_trial
    from code_editing.formats import FORMAT_REGISTRY

    tasks_dir = Path(__file__).parent.parent / "experiments" / "code-editing" / "tasks" / "v2"
    # discover_tasks() returns EditTask objects directly (not ids).
    specs = list(discover_tasks(tasks_dir))[:n]
    fmt = FORMAT_REGISTRY["search_replace"]()
    transcripts_dir = out_dir / "edit" / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    handle = make_model(model)
    records: list[RunRecord] = []
    for spec in specs:
        with tempfile.TemporaryDirectory(prefix=f"ce-{spec.task_id}-") as tmp:
            workdir = Path(tmp) / "work"
            rec = run_trial(
                task=spec,
                model=handle.client,    # legacy positional
                fmt=fmt,
                workdir=workdir,
                max_turns=10,
                transcripts_dir=transcripts_dir,
                handle=handle,           # routes through backend + OTEL
            )
        rec.condition = "edit"
        records.append(rec)
    return records


# ============ scorecard ============


def _summarize(records: list[RunRecord], label: str) -> str:
    if not records:
        return f"| {label} | n=0 | — | — | — | — | — |"
    n = len(records)
    pass_rate = sum(r.passed for r in records) / n
    mean_cost = statistics.mean(r.cost_usd for r in records)
    mean_lat = statistics.mean(r.latency_seconds for r in records)
    # Step-level metrics — present on records from turn-loop trials.
    extras = [r.extra or {} for r in records]
    wasted = [e["wasted_turn_fraction"] for e in extras if "wasted_turn_fraction" in e]
    batch = [e["batch_efficiency"] for e in extras if "batch_efficiency" in e and e["batch_efficiency"] > 0]
    # Context observation: peak input tokens (see HARNESS.md).
    peak_in = [e["peak_input_tokens"] for e in extras if e.get("peak_input_tokens")]
    wasted_str = f"{statistics.mean(wasted):>5.0%}" if wasted else "—"
    batch_str = f"{statistics.mean(batch):>4.1f}" if batch else "—"
    peak_str = f"{statistics.mean(peak_in):>5,.0f}" if peak_in else "—"
    return (
        f"| {label:<22} | {n} | {pass_rate:>5.0%} | ${mean_cost:>6.4f} | "
        f"{mean_lat:>5.1f}s | {wasted_str} | {batch_str} | {peak_str} |"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default="claude-haiku-4-5", help="model id (any registered)")
    p.add_argument(
        "--n",
        type=int,
        default=3,
        help="tasks per experiment. Default 3 = ~9 trials, ~2 min.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output directory. Default: results/scorecard_<model>",
    )
    p.add_argument(
        "--skip",
        action="append",
        default=[],
        choices=["localize", "select", "edit"],
        help="skip an experiment (repeatable)",
    )
    args = p.parse_args()

    _load_env()
    if "ANTHROPIC_API_KEY" not in os.environ and "OPENAI_API_KEY" not in os.environ:
        print("ERROR: no API key set. Put one in .env.", file=sys.stderr)
        return 2

    out = args.out or Path(f"results/scorecard_{args.model.replace('-', '_')}")
    out.mkdir(parents=True, exist_ok=True)
    setup_tracing(out_path=out / "traces.jsonl")

    print(f"running scorecard for {args.model} (n={args.n} per experiment)...", file=sys.stderr)
    print(f"  skipping: {args.skip or 'nothing'}", file=sys.stderr)

    all_records: list[tuple[str, list[RunRecord]]] = []

    for label, runner in [
        ("find  (localize)", _run_localize),
        ("plan  (tool-use)", _run_select),
        ("edit  (code)", _run_edit),
    ]:
        short = label.split()[0]
        if short in args.skip:
            print(f"  skip {short}", file=sys.stderr)
            continue
        print(f"  running {label}...", file=sys.stderr, flush=True)
        try:
            records = runner(args.model, args.n, out)
        except Exception as e:  # noqa: BLE001
            print(f"    ERROR: {type(e).__name__}: {e}", file=sys.stderr)
            records = []
        all_records.append((label, records))
        n_pass = sum(r.passed for r in records)
        print(f"    {n_pass}/{len(records)} passed", file=sys.stderr)

    shutdown_tracing()

    # Write per-experiment CSV (one combined file).
    flat = [r for _, rs in all_records for r in rs]
    if flat:
        write_csv(flat, out / "per_trial.csv")
        write_markdown(flat, out / "full_summary.md")

    # Write the headline scorecard.
    lines = [
        f"# Capability scorecard — {args.model}",
        "",
        f"N={args.n} tasks per experiment. Smoke run, not a benchmark.",
        "Each experiment uses its default backend from `data/model_backends.yaml`.",
        "",
        "Step-level columns (only for turn-loop trials):",
        "- **wasted%**: fraction of turns that didn't make progress (re-tried same call, or all calls errored)",
        "- **batch**: mean actions per active turn — higher = better batching, lower = chatty",
        "- **peak in**: max input_tokens any single turn used (proxy for context bloat — see HARNESS.md)",
        "",
        "| capability             |  n | pass | cost     | latency | wasted% | batch | peak in |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, recs in all_records:
        lines.append(_summarize(recs, label))
    lines.append("")
    lines.append("Reproduce per-experiment with the experiment's own sweep script.")
    summary = "\n".join(lines) + "\n"
    (out / "scorecard.md").write_text(summary, encoding="utf-8")
    print("\n" + summary)
    print(f"wrote scorecard to {out}/scorecard.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
