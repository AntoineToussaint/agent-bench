"""CSV + markdown reports from a list of RunRecords.

Two views:
  - Per-record CSV: one row per trial (including each replicate).
  - Per-cell aggregate: collapse replicates into pass_rate + p25/p50/p75
    distributions for turns / cost / latency / tokens.

Latency is reported both as one wall-clock number (`latency_seconds`) and,
when clients stream, split into TTFT vs generate (NEXT.md #32) with a derived
decode throughput (tokens/sec). The markdown grows a "Latency split" section
only when something actually streamed.
"""

from __future__ import annotations

import csv
import json as _json
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
    "failure_mode",
    "submitted",   # JSON-encoded list of predicted files
    "turns",
    "tool_calls",
    "invalid_tool_calls",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "cost_usd",
    "latency_seconds",
    "ttft_seconds",
    "generate_seconds",
    "decode_tokens_per_s",
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
                    "failure_mode": (r.extra or {}).get("failure_mode") or "",
                    "submitted": _json.dumps(
                        (r.extra or {}).get("submitted") or [],
                        ensure_ascii=False,
                    ),
                    "turns": r.turns,
                    "tool_calls": r.tool_calls,
                    "invalid_tool_calls": r.invalid_tool_calls,
                    "input_tokens": r.usage.input_tokens,
                    "output_tokens": r.usage.output_tokens,
                    "cache_read_tokens": r.usage.cache_read_tokens,
                    "cache_creation_tokens": r.usage.cache_creation_tokens,
                    "cost_usd": f"{r.cost_usd:.6f}",
                    "latency_seconds": f"{r.latency_seconds:.3f}",
                    "ttft_seconds": f"{r.usage.ttft_seconds:.3f}",
                    "generate_seconds": f"{r.usage.generate_seconds:.3f}",
                    "decode_tokens_per_s": f"{r.usage.decode_tokens_per_s:.1f}",
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
    # Latency split (NEXT.md #32). ttft/generate are 0-tuples for non-streaming
    # runs; decode_tokens_per_s is aggregated over streamed replicates only.
    ttft_seconds: tuple[float, float, float]
    generate_seconds: tuple[float, float, float]
    decode_tokens_per_s: tuple[float, float, float]


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
                ttft_seconds=_p([r.usage.ttft_seconds for r in rs]),
                generate_seconds=_p([r.usage.generate_seconds for r in rs]),
                # Throughput only makes sense where decode was timed; averaging
                # in 0.0 for non-streamed replicates would understate it.
                decode_tokens_per_s=_p(
                    [r.usage.decode_tokens_per_s for r in rs if r.usage.generate_seconds > 0]
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
        "ttft_p25", "ttft_p50", "ttft_p75",
        "generate_p25", "generate_p50", "generate_p75",
        "decode_tps_p25", "decode_tps_p50", "decode_tps_p75",
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
                "ttft_p25": f"{c.ttft_seconds[0]:.3f}", "ttft_p50": f"{c.ttft_seconds[1]:.3f}", "ttft_p75": f"{c.ttft_seconds[2]:.3f}",
                "generate_p25": f"{c.generate_seconds[0]:.3f}", "generate_p50": f"{c.generate_seconds[1]:.3f}", "generate_p75": f"{c.generate_seconds[2]:.3f}",
                "decode_tps_p25": f"{c.decode_tokens_per_s[0]:.1f}", "decode_tps_p50": f"{c.decode_tokens_per_s[1]:.1f}", "decode_tps_p75": f"{c.decode_tokens_per_s[2]:.1f}",
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
    lines.append(_latency_split_section(records))
    lines.append(_failure_mode_section(records))
    return "\n".join(lines) + "\n"


def _latency_split_section(records: list[RunRecord]) -> str:
    """TTFT-vs-generate breakdown (NEXT.md #32), one row per (model, condition).

    Answers "is this model slow to *start* or slow to *generate*?" directly:
    mean TTFT, mean decode time, the TTFT share of model time, and decode
    throughput (tokens/sec) — the length-normalized generation speed. Returns
    "" when nothing streamed (all generate_seconds == 0), so non-streaming
    runs don't sprout a table of zeros.
    """
    streamed = [r for r in records if r.usage.generate_seconds > 0]
    if not streamed:
        return ""
    groups: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for r in streamed:
        groups[(r.model, r.condition)].append(r)

    lines = [
        "",
        "## Latency split (TTFT vs generate)",
        "",
        "Per NEXT.md #32: is the model slow to *start* (TTFT) or slow to",
        "*generate* (decode)? `ttft_frac` ≈ 1 means startup-bound, ≈ 0 means",
        "decode-bound. `decode tok/s` is length-normalized generation speed.",
        "Averaged over streamed trials only.",
        "",
        "| model | condition | mean_ttft (s) | mean_gen (s) | ttft_frac | decode tok/s |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for (model, cond), rs in sorted(groups.items()):
        mean_ttft = statistics.mean(r.usage.ttft_seconds for r in rs)
        mean_gen = statistics.mean(r.usage.generate_seconds for r in rs)
        mean_frac = statistics.mean(r.usage.ttft_fraction for r in rs)
        mean_tps = statistics.mean(r.usage.decode_tokens_per_s for r in rs)
        lines.append(
            f"| {model} | {cond} | {mean_ttft:.2f} | {mean_gen:.2f} | "
            f"{mean_frac:.2f} | {mean_tps:,.0f} |"
        )
    return "\n".join(lines)


def _failure_mode_section(records: list[RunRecord]) -> str:
    """Render a failures-by-mode breakdown, scoped to failed trials only."""
    failed = [r for r in records if not r.passed]
    if not failed:
        return ""
    # Tally (model, condition, mode).
    tally: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in failed:
        mode = (r.extra or {}).get("failure_mode") or "unclassified"
        tally[(r.model, r.condition, mode)] += 1
    if not tally:
        return ""
    lines = [
        "",
        "## Failure modes",
        "",
        "Each row is a (model, condition, mode) bucket with N=number of",
        "failed trials in that bucket. See `lib/agent-eval-core/FAILURE_MODES.md`",
        "for the taxonomy.",
        "",
        "| model | condition | failure_mode | n |",
        "|---|---|---|---:|",
    ]
    for (model, cond, mode), n in sorted(tally.items()):
        lines.append(f"| {model} | {cond} | `{mode}` | {n} |")
    return "\n".join(lines)


def _summarize_with_replicates(records: list[RunRecord]) -> str:
    """Richer summary for runs with replicates > 1."""
    cells = aggregate_cells(records)
    by_mc: dict[tuple[str, str], list[CellStats]] = defaultdict(list)
    for c in cells:
        by_mc[(c.model, c.condition)].append(c)

    # Pre-collect raw records per (model, condition) so we can aggregate
    # token/tool-call metrics that CellStats doesn't already track.
    raw_by_mc: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for r in records:
        raw_by_mc[(r.model, r.condition)].append(r)

    lines = [
        "| model | condition | tasks | reps | pass | turns p50 | tools p50 | cost p50 | in tok p50 | cache_r p50 | lat p50 |",
        "|---|---|---:|---:|---:|---|---|---|---|---|---|",
    ]
    for (model, cond), cs in sorted(by_mc.items()):
        n_tasks = len(cs)
        reps = max(c.n for c in cs)
        mean_pass = statistics.mean(c.pass_rate for c in cs)
        turn_p50 = statistics.median(c.turns[1] for c in cs)
        turn_p25 = statistics.median(c.turns[0] for c in cs)
        turn_p75 = statistics.median(c.turns[2] for c in cs)
        tool_p50 = statistics.median(c.tool_calls[1] for c in cs)
        tool_p25 = statistics.median(c.tool_calls[0] for c in cs)
        tool_p75 = statistics.median(c.tool_calls[2] for c in cs)
        cost_p50 = statistics.median(c.cost_usd[1] for c in cs)
        cost_p25 = statistics.median(c.cost_usd[0] for c in cs)
        cost_p75 = statistics.median(c.cost_usd[2] for c in cs)
        lat_p50 = statistics.median(c.latency_seconds[1] for c in cs)
        lat_p25 = statistics.median(c.latency_seconds[0] for c in cs)
        lat_p75 = statistics.median(c.latency_seconds[2] for c in cs)
        # Cached tokens + per-trial input tokens come from the raw records.
        # CellStats only carries combined (input+output) so we compute fresh.
        raws = raw_by_mc[(model, cond)]
        in_p50 = statistics.median(r.usage.input_tokens for r in raws)
        cache_p50 = statistics.median(r.usage.cache_read_tokens for r in raws)
        lines.append(
            f"| {model} | {cond} | {n_tasks} | {reps} | {mean_pass:.0%} | "
            f"{turn_p50:.0f} ({turn_p25:.0f}-{turn_p75:.0f}) | "
            f"{tool_p50:.0f} ({tool_p25:.0f}-{tool_p75:.0f}) | "
            f"${cost_p50:.4f} (${cost_p25:.4f}-${cost_p75:.4f}) | "
            f"{in_p50:,.0f} | {cache_p50:,.0f} | "
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
    lines.append(_latency_split_section(records))
    lines.append(_failure_mode_section(records))
    return "\n".join(lines) + "\n"


def write_markdown(records: list[RunRecord], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(summarize_markdown(records), encoding="utf-8")
