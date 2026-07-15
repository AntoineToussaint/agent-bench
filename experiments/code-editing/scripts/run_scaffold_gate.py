"""Run the same-model scaffold-value gate on code-editing tasks.

This is a pilot harness, not a SWE-bench leaderboard submission. It isolates
control flow on the repository's hermetic edit tasks before spending on the
larger Verified/Pro experiment.

Examples:
    uv run --package code-editing python \
      experiments/code-editing/scripts/run_scaffold_gate.py --dry-run

    uv run --package code-editing python \
      experiments/code-editing/scripts/run_scaffold_gate.py \
      --model claude-sonnet-4-6 --size medium --limit 6 --budget 10
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent_eval import make_model
from agent_eval.reports import write_aggregate_csv, write_csv
from agent_eval.tracing import setup_tracing, shutdown_tracing

from code_editing.bench import discover_tasks
from code_editing.scaffold_gate import analyze_scaffold_gate, write_scaffold_gate
from code_editing.scaffolds import (
    ADAPTIVE_POLICY_VERSION,
    FIXED_PROMPT_VERSION,
    MINIMAL_PROMPT_VERSION,
    SCAFFOLDS,
    run_scaffold_trial,
)


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TASKS = ROOT / "experiments/code-editing/tasks/v2"


def _load_env() -> None:
    for path in (ROOT / ".env", Path.home() / "Development" / ".env", Path.home() / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


def _required_key(model: str) -> str:
    if model.startswith("claude"):
        return "ANTHROPIC_API_KEY"
    if model.startswith("gpt"):
        return "OPENAI_API_KEY"
    if model.startswith("gemini"):
        return "GEMINI_API_KEY"
    return "OPENROUTER_API_KEY"


def _arm_order(
    scaffolds: list[str], *, task_index: int, replicate: int, seed: int
) -> list[str]:
    """Seeded cyclic counterbalance so a small pilot has no fixed first arm."""
    ordered = list(scaffolds)
    random.Random(seed).shuffle(ordered)
    offset = (task_index + replicate) % len(ordered)
    return ordered[offset:] + ordered[:offset]


def _task_digest(task: Any) -> str:
    """Fingerprint task metadata, starter files, and hidden oracle files."""
    digest = hashlib.sha256()
    metadata = {
        "task_id": task.task_id,
        "language": task.language,
        "category": task.category,
        "instructions": task.instructions,
        "oracle_cmd": task.oracle_cmd,
        "files_in_context": task.files_in_context,
    }
    digest.update(json.dumps(metadata, sort_keys=True).encode())
    task_root = task.fixture_dir.parent
    for dirname in ("fixture", "oracle"):
        root = task_root / dirname
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(task_root)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_revision() -> dict[str, Any]:
    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"

    return {
        "commit": run("rev-parse", "HEAD"),
        "dirty": bool(run("status", "--porcelain")),
    }


def _runtime_config(handle: Any) -> dict[str, Any]:
    client = handle.client
    parameters = {
        name: getattr(client, name)
        for name in ("model_id", "max_tokens", "temperature", "reasoning_effort")
        if hasattr(client, name)
    }
    return {
        "client_class": type(client).__name__,
        "backend_class": type(handle.backend).__name__,
        "context_policy_class": type(handle.context_policy).__name__,
        "parameters": parameters,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--scaffolds", nargs="+", choices=SCAFFOLDS, default=list(SCAFFOLDS))
    parser.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--size", choices=["small", "medium", "large", "all"], default="medium")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--budget", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("results/scaffold_gate"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.limit <= 0 or args.repetitions <= 0:
        parser.error("--limit and --repetitions must be positive")
    if args.max_turns < 6:
        parser.error("--max-turns must be at least 6")
    if args.budget <= 0:
        parser.error("--budget must be positive")

    tasks = discover_tasks(args.tasks_dir)
    if args.size != "all":
        tasks = [task for task in tasks if task.task_id.endswith(f"__{args.size}")]
    tasks = tasks[: args.limit]
    if not tasks:
        print("ERROR: no tasks matched", file=sys.stderr)
        return 2

    n_trials = len(tasks) * len(args.scaffolds) * args.repetitions
    print(f"model: {args.model}")
    print(f"scaffolds: {', '.join(args.scaffolds)}")
    print(f"tasks ({len(tasks)}): {', '.join(task.task_id for task in tasks)}")
    print(f"repetitions: {args.repetitions}; trials: {n_trials}; max turns/trial: {args.max_turns}")
    print(f"soft budget stop (checked between trials): ${args.budget:.2f}")
    print(
        "versions: "
        f"minimal={MINIMAL_PROMPT_VERSION}, fixed={FIXED_PROMPT_VERSION}, "
        f"adaptive={ADAPTIVE_POLICY_VERSION}"
    )
    if args.dry_run:
        print("[dry-run] no clients created and no API calls made")
        return 0

    _load_env()
    key = _required_key(args.model)
    if key not in os.environ:
        print(f"ERROR: missing {key}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    setup_tracing(out_path=args.out / "traces.jsonl")
    records = []
    spent = 0.0
    stopped = False
    runtime_config: dict[str, Any] | None = None
    try:
        # Task-major ordering preserves paired coverage under a budget cutoff.
        for task_index, task in enumerate(tasks):
            for replicate in range(args.repetitions):
                arm_order = _arm_order(
                    args.scaffolds,
                    task_index=task_index,
                    replicate=replicate,
                    seed=args.seed,
                )
                for scaffold in arm_order:
                    if spent >= args.budget:
                        stopped = True
                        break
                    print(
                        f"{task.task_id} | {scaffold} | rep={replicate}...",
                        end="",
                        flush=True,
                    )
                    handle = make_model(args.model)
                    if runtime_config is None:
                        runtime_config = _runtime_config(handle)
                    with tempfile.TemporaryDirectory(prefix="scaffold-gate-") as tmp:
                        record = run_scaffold_trial(
                            task,
                            handle,
                            scaffold,
                            Path(tmp) / "work",
                            max_turns=args.max_turns,
                            transcripts_dir=(
                                args.out / "transcripts" / f"rep_{replicate}"
                            ),
                            sessions_dir=args.out / "sessions" / f"rep_{replicate}",
                        )
                    record.replicate = replicate
                    records.append(record)
                    spent += record.cost_usd
                    print(
                        f" {'PASS' if record.passed else 'FAIL'} "
                        f"turns={record.turns} cost=${record.cost_usd:.4f} "
                        f"spent=${spent:.2f}"
                    )
                if stopped:
                    break
            if stopped:
                break
    finally:
        shutdown_tracing()

    write_csv(records, args.out / "per_trial.csv")
    write_aggregate_csv(records, args.out / "per_cell.csv")
    analysis = analyze_scaffold_gate(records, seed=args.seed)
    if analysis is not None:
        write_scaffold_gate(analysis, args.out / "gate.md")
    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git": _git_revision(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "model": args.model,
        "model_runtime": runtime_config,
        "scaffolds": args.scaffolds,
        "task_ids": [task.task_id for task in tasks],
        "task_digests": {task.task_id: _task_digest(task) for task in tasks},
        "max_turns": args.max_turns,
        "repetitions": args.repetitions,
        "seed": args.seed,
        "arm_ordering": "seeded cyclic counterbalance by task and replicate",
        "budget_cap_usd": args.budget,
        "budget_check": "between trials; total may exceed threshold by one trial",
        "spent_usd": spent,
        "budget_stopped": stopped,
        "prompt_versions": {
            "minimal": MINIMAL_PROMPT_VERSION,
            "fixed": FIXED_PROMPT_VERSION,
            "adaptive": ADAPTIVE_POLICY_VERSION,
        },
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(records)} records to {args.out}")
    if analysis is None:
        print("paired report unavailable: not every arm completed a shared task")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
