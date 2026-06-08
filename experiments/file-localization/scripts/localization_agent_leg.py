"""Agent leg of the localization bake-off: run the agentic turn-loop (iterative
grep/list/view -> done(files)) on the SAME instances as the static retrievers
(bm25/ripgrep/embedding), so we can put agentic search on the same recall table.

This is the no-indexing debate's actual claim: does an LLM that searches the repo
on demand beat a static index? Static arms live in scripts via the cli + runner;
this adds the agentic point. Uses Haiku (mirrors Claude Code's Explore subagent).

Loads instances from a local SWE-bench jsonl (e.g. Mind's swe_bench_verified.jsonl)
filtered to a manifest (easiest_10) so it matches the static run exactly.

Usage:
  cd /Users/antoine/Development/research/agent-bench
  uv run --package file-localization python \
    experiments/file-localization/scripts/localization_agent_leg.py \
    --jsonl /tmp/easiest10.jsonl --model claude-haiku-4-5 --n 1   # smoke
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent_eval import Sweep
from file_localization.adapters.hf_swebench import RawTask, to_localization_tasks
from file_localization.contract import LocalizationTask
from file_localization.repos import prepare as prepare_repo
from file_localization.turn_loop_trial import LocalRepoView, make_turn_loop_trial


def _load_tasks(jsonl: Path, manifest: Path | None, n: int | None):
    rows = [json.loads(l) for l in jsonl.read_text().splitlines() if l.strip()]
    if manifest:
        ids = {l.strip() for l in manifest.read_text().splitlines() if l.strip()}
        rows = [r for r in rows if r.get("instance_id") in ids]
    raws = [
        RawTask(
            instance_id=r["instance_id"], repo=r["repo"], base_commit=r["base_commit"],
            problem_statement=r["problem_statement"], patch=r["patch"],
            test_patch=r.get("test_patch", ""),
        )
        for r in rows
    ]
    tasks = to_localization_tasks(raws)
    return tasks[:n] if n else tasks


def _build_repo_view_for():
    cache: dict[str, LocalRepoView] = {}

    def repo_view_for(task: LocalizationTask) -> LocalRepoView:
        key = f"{task.repo}@{task.base_commit}"
        if key not in cache:
            print(f"  cloning {task.repo} @ {task.base_commit[:12]}...", flush=True)
            cache[key] = LocalRepoView(prepare_repo(task.repo, task.base_commit))
        return cache[key]

    return repo_view_for


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", type=Path, required=True, help="local SWE-bench jsonl")
    ap.add_argument("--manifest", type=Path, default=None, help="optional instance-id manifest filter")
    ap.add_argument("--model", default="claude-haiku-4-5")
    ap.add_argument("--n", type=int, default=None, help="cap tasks (1 = smoke)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--out", default="results/localization_bakeoff_agent")
    args = ap.parse_args()
    load_dotenv(Path("/Users/antoine/Development/.env"), override=False)
    load_dotenv()

    tasks = _load_tasks(args.jsonl, args.manifest, args.n)
    if not tasks:
        print("no tasks", file=sys.stderr)
        return 1
    print(f"agent leg: {len(tasks)} task(s) x model {args.model} (turn-loop)")
    for t in tasks:
        print(f"  - {t.instance_id} ({t.repo})  gold={sorted(t.gold_edit_files)}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    turn_loop = make_turn_loop_trial(
        repo_view_for=_build_repo_view_for(), top_k=20,
        transcripts_dir=out / "transcripts",
    )

    def trial(client, condition, task):
        return turn_loop(client, condition, task)

    def on_progress(i, total, rec):
        x = rec.extra or {}
        print(f"  [{i}/{total}] {rec.task_id}: pass={rec.passed} recall={x.get('recall',0):.2f} "
              f"submitted={x.get('submitted')} turns={rec.turns} cost=${rec.cost_usd:.4f} "
              f"{rec.latency_seconds:.1f}s" + (f" ERR={rec.error}" if rec.error else ""))

    records = Sweep(
        models=[args.model], conditions=["turn-loop"], tasks=tasks,
        trial=trial, repetitions=args.reps, on_progress=on_progress,
    ).run()

    with (out / "per_trial.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["instance_id", "model", "passed", "recall", "n_predicted",
                    "submitted", "turns", "cost_usd", "latency_s", "error"])
        for r in records:
            x = r.extra or {}
            w.writerow([r.task_id, r.model, int(r.passed), x.get("recall", ""),
                        x.get("n_predicted", ""), "|".join(x.get("submitted", []) or []),
                        r.turns, f"{r.cost_usd:.6f}", f"{r.latency_seconds:.3f}", r.error or ""])
    n_pass = sum(1 for r in records if r.passed)
    print(f"\nagent (turn-loop) strict-pass: {n_pass}/{len(records)}; wrote {out}/per_trial.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
