"""Patch Cascade smoke — does a cheap-draft + strong-correction ladder beat
solving from scratch on the cost/quality frontier?

The bet (see the design discussion): output tokens dominate cost + latency on
the expensive model. If a stronger model only has to emit a short *diff*
correcting a cheaper model's draft — instead of a full answer — its
output-token bill drops. The catch: corrections re-read context (input cost)
and a big quality gap means a big diff, so the win is conditional. This script
maps where on the frontier it actually pays.

Conditions
  haiku-scratch / sonnet-scratch / opus-scratch  — single-shot baselines
  patch-cascade-3   haiku -> sonnet -> opus, corrections = diffs   (the proposal)
  patch-cascade-2   haiku -> opus, corrections = diffs             (does sonnet rung pay?)
  cascade-rewrite-3 haiku -> sonnet -> opus, corrections = full rewrites
                                                  (isolates diff-output savings)

Gap band (Haiku fails single-shot, Opus passes — where a cascade has something
to prove): c04 c05 c06 c07 c08 c12. Smoke runs a 2-task subset.

Usage
  cd /Users/antoine/Development/research/agent-bench
  # plan only, no API spend:
  uv run --package code-editing python \
    experiments/code-editing/scripts/run_patch_cascade.py --dry-run
  # real run (needs ANTHROPIC_API_KEY; smoke ~ a few cents):
  uv run --package code-editing python \
    experiments/code-editing/scripts/run_patch_cascade.py \
    --tasks c06_extract_function,c08_add_feature --size medium \
    --out results/patch_cascade_smoke
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from agent_eval import RunRecord, make_client
from code_editing.adapters.filesystem import discover_tasks
from code_editing.formats import FORMAT_REGISTRY
from code_editing.bench.runner import run_cascade, run_single_shot

HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-4-6"
OPUS = "claude-opus-4-8"

EXP_ROOT = Path(__file__).resolve().parents[1]
TASKS_ROOT = EXP_ROOT / "tasks" / "v2"

# Gap-band tasks (Haiku fails single-shot, Opus passes) from the existing
# haiku/opus single-mode results. Smoke defaults to two of them.
GAP_BAND = [
    "c04_signature_change", "c05_api_migration", "c06_extract_function",
    "c07_inline_function", "c08_add_feature", "c12_hygiene",
]


def _conditions(gate_model: str):
    """Return (name, builder) pairs. Builder takes (task, workdir, tdir) -> RunRecord."""
    fmt = FORMAT_REGISTRY["search_replace"]()

    def scratch(model):
        def run(task, workdir, tdir):
            return run_single_shot(task, make_client(model), fmt, workdir, transcripts_dir=tdir)
        return run

    def cascade(models, style, gated=False):
        def run(task, workdir, tdir):
            clients = [make_client(m) for m in models]
            gate = make_client(gate_model) if gated else None
            return run_cascade(
                task, clients, fmt, workdir,
                correction_style=style, gate_client=gate, transcripts_dir=tdir,
            )
        return run

    # The load-bearing comparison: diff (Patch Cascade) vs rewrite (≈ a vanilla
    # cascade that regenerates on escalation), at the same ladder + same gating.
    # If diff doesn't beat rewrite, the diff knob adds nothing over FrugalGPT.
    return [
        ("haiku-scratch", scratch(HAIKU)),
        ("sonnet-scratch", scratch(SONNET)),
        ("opus-scratch", scratch(OPUS)),
        # ungated (always run every tier)
        ("cascade-2-diff", cascade([HAIKU, OPUS], "diff")),
        ("cascade-2-rewrite", cascade([HAIKU, OPUS], "rewrite")),
        ("cascade-3-diff", cascade([HAIKU, SONNET, OPUS], "diff")),
        ("cascade-3-rewrite", cascade([HAIKU, SONNET, OPUS], "rewrite")),
        # gated: a cheap conservative judge halts the ladder when confident
        ("cascade-2-diff-gated", cascade([HAIKU, OPUS], "diff", gated=True)),
        ("cascade-2-rewrite-gated", cascade([HAIKU, OPUS], "rewrite", gated=True)),
        ("cascade-3-diff-gated", cascade([HAIKU, SONNET, OPUS], "diff", gated=True)),
        ("cascade-3-rewrite-gated", cascade([HAIKU, SONNET, OPUS], "rewrite", gated=True)),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="c06_extract_function,c08_add_feature",
                    help="comma-separated task prefixes (default: 2 gap-band tasks)")
    ap.add_argument("--size", default="medium", choices=["small", "medium", "large"])
    ap.add_argument("--out", default="results/patch_cascade_smoke")
    ap.add_argument("--gate-model", default=HAIKU, help="cheap judge for the early-stop gate")
    ap.add_argument("--reps", type=int, default=3, help="repetitions per cell (kills single-run noise)")
    ap.add_argument("--sizes", default=None, help="comma list of sizes (overrides --size), e.g. medium,large")
    ap.add_argument("--only", default=None, help="comma list of condition names to run (subset)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, spend nothing")
    args = ap.parse_args()

    load_dotenv()
    prefixes = [t.strip() for t in args.tasks.split(",") if t.strip()]
    sizes = [s.strip() for s in (args.sizes.split(",") if args.sizes else [args.size]) if s.strip()]
    all_tasks = discover_tasks(TASKS_ROOT)
    wanted = {f"{p}__{s}" for p in prefixes for s in sizes}
    tasks = [t for t in all_tasks if t.task_id in wanted]
    conditions = _conditions(args.gate_model)
    if args.only:
        keep = {c.strip() for c in args.only.split(",")}
        conditions = [(n, b) for (n, b) in conditions if n in keep]

    if not tasks:
        print(f"no tasks matched {sorted(wanted)} under {TASKS_ROOT}", file=sys.stderr)
        return 1

    print(f"Patch Cascade smoke — {len(tasks)} task(s) x {len(conditions)} condition(s)")
    for t in tasks:
        print(f"  task: {t.task_id}  ({t.category}, {t.language})")
    for name, _ in conditions:
        print(f"  condition: {name}")
    print(f"  pricing: haiku 1/5  sonnet 3/15  opus 5/25  ($/Mtok in/out)")

    if args.dry_run:
        print("\n[dry-run] no API calls made. Re-run without --dry-run (needs "
              "ANTHROPIC_API_KEY) to execute.")
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nERROR: ANTHROPIC_API_KEY not set (no .env found either). "
              "Set it and re-run, e.g.:\n  ANTHROPIC_API_KEY=sk-... uv run ...",
              file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tdir = out / "transcripts"
    # (task_id, condition, rep, rec)
    records: list[tuple[str, str, int, RunRecord]] = []

    print(f"\nrunning {len(tasks)} task(s) x {len(conditions)} cond(s) x {args.reps} rep(s) "
          f"= {len(tasks) * len(conditions) * args.reps} trials\n")
    for task in tasks:
        for name, builder in conditions:
            for rep in range(args.reps):
                with tempfile.TemporaryDirectory() as tmp:
                    rec = builder(task, Path(tmp), tdir)
                records.append((task.task_id, name, rep, rec))
                fpt = rec.extra.get("first_passing_tier", "-")
                stop = rec.extra.get("stopped_early_at_tier", None)
                gd = ";".join(f"t{d['tier']}:{'C' if d['confident'] else 'N'}"
                              f"{'ok' if d['correct'] else 'X'}"
                              for d in rec.extra.get("gate_decisions", []))
                print(f"  {task.task_id:24s} {name:24s} r{rep} "
                      f"pass={int(rec.passed)} ${rec.cost_usd:.4f} {rec.latency_seconds:5.1f}s "
                      f"fpt={fpt} stop={stop} gate=[{gd}]"
                      + (f"  ERR={rec.error}" if rec.error else ""))

    # ---- per-trial CSV ----
    csv_path = out / "per_trial.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "condition", "rep", "passed", "cost_usd", "latency_s",
                    "ttft_s", "generate_s",
                    "input_tokens", "output_tokens", "cache_read_tokens",
                    "top_tier_output_tokens", "changed_file_chars", "diff_chars",
                    "edit_fraction", "draft_failing_tests", "first_passing_tier",
                    "stopped_early_at_tier", "tiers_run", "gate_decisions",
                    "tiers", "error"])
        for tid, name, rep, rec in records:
            w.writerow([
                tid, name, rep, int(rec.passed), f"{rec.cost_usd:.6f}",
                f"{rec.latency_seconds:.3f}",
                f"{rec.usage.ttft_seconds:.3f}", f"{rec.usage.generate_seconds:.3f}",
                rec.usage.input_tokens,
                rec.usage.output_tokens, rec.usage.cache_read_tokens,
                rec.extra.get("top_tier_output_tokens", ""),
                rec.extra.get("changed_file_chars", ""),
                rec.extra.get("diff_chars", ""),
                rec.extra.get("edit_fraction", ""),
                rec.extra.get("draft_failing_tests", ""),
                rec.extra.get("first_passing_tier", ""),
                rec.extra.get("stopped_early_at_tier", ""),
                rec.extra.get("tiers_run", ""),
                ";".join(f"t{d['tier']}:{'C' if d['confident'] else 'N'}"
                         f"{'ok' if d['correct'] else 'X'}"
                         for d in rec.extra.get("gate_decisions", [])),
                "|".join(rec.extra.get("tiers", [])), rec.error or "",
            ])

    # ---- aggregate per (task, condition): the result-grade view ----
    from collections import OrderedDict
    agg: "OrderedDict[tuple[str,str], list[RunRecord]]" = OrderedDict()
    for tid, name, _rep, rec in records:
        agg.setdefault((tid, name), []).append(rec)

    def _mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    summary_path = out / "summary.csv"
    print(f"\n=== AGGREGATE (mean over {args.reps} reps) ===")
    hdr = (f"  {'task':24s} {'condition':24s} {'pass%':>6s} {'$mean':>8s} "
           f"{'lat':>6s} {'ttft':>6s} {'gen':>6s} {'gate_acc':>9s} {'early%':>7s}")
    print(hdr)
    with summary_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "condition", "n", "pass_rate", "mean_cost_usd",
                    "mean_latency_s", "mean_ttft_s", "mean_generate_s",
                    "gate_n", "gate_accuracy", "early_stop_rate"])
        for (tid, name), recs in agg.items():
            n = len(recs)
            pass_rate = _mean([1.0 if r.passed else 0.0 for r in recs])
            mean_cost = _mean([r.cost_usd for r in recs])
            mean_lat = _mean([r.latency_seconds for r in recs])
            mean_ttft = _mean([r.usage.ttft_seconds for r in recs])
            mean_gen = _mean([r.usage.generate_seconds for r in recs])
            gate_dec = [d for r in recs for d in r.extra.get("gate_decisions", [])]
            gate_n = len(gate_dec)
            gate_acc = _mean([1.0 if d["correct"] else 0.0 for d in gate_dec]) if gate_n else None
            early = _mean([1.0 if r.extra.get("stopped_early_at_tier") is not None else 0.0
                           for r in recs])
            acc_s = f"{gate_acc:.2f}({gate_n})" if gate_acc is not None else "-"
            print(f"  {tid:24s} {name:24s} {pass_rate*100:5.0f}% ${mean_cost:7.4f} "
                  f"{mean_lat:5.1f}s {mean_ttft:5.1f}s {mean_gen:5.1f}s {acc_s:>9s} {early*100:6.0f}%")
            w.writerow([tid, name, n, f"{pass_rate:.3f}", f"{mean_cost:.6f}",
                        f"{mean_lat:.3f}", f"{mean_ttft:.3f}", f"{mean_gen:.3f}", gate_n,
                        f"{gate_acc:.3f}" if gate_acc is not None else "",
                        f"{early:.3f}"])

    print(f"\nwrote {csv_path} and {summary_path}")
    print("Key reads: (1) diff vs rewrite at same ladder+gating — does the diff "
          "knob beat plain regeneration? (2) gate_acc — did the conservative gate "
          "stop false-CONFIDENTs? (3) cascade rows that Pareto-beat opus-scratch "
          "(>= pass% at < $mean).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
