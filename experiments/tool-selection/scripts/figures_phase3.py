"""Phase 3 figures.

Reads data/runs/phase3_v4.jsonl and emits:
  fig_p3_first_try.png  — first-try success rate per (failure_mode, condition)
                          with error bars across replicates
  fig_p3_cost.png       — average cost-per-episode per condition (both modes
                          averaged)
  fig_p3_trajectory.png — per-episode first-try success (line plot, episode
                          index on x-axis, success-rate-across-replicates on y)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl


CONDITION_LABELS = {
    "baseline": "Baseline (no lessons)",
    "lessons-only": "Lessons-only (text in user message)",
    "promotion-llm": "Promotion (LLM-synthesized derived tool)",
    "description-augment": "Description-augment (edit the source tool's docs)",
}

CONDITION_COLORS = {
    "baseline": "#dc2626",            # red — pays full failure tax
    "lessons-only": "#f59e0b",        # amber — middle
    "promotion-llm": "#0891b2",       # cyan — heavy
    "description-augment": "#16a34a", # green — the winner
}


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, alpha=0.25, linestyle=":")
    ax.tick_params(labelsize=9)


def load() -> pl.DataFrame:
    # Prefer phase35 if present (4 conditions including description-augment)
    p35 = Path("data/runs/phase35.jsonl")
    if p35.exists():
        return pl.read_ndjson(p35)
    return pl.read_ndjson("data/runs/phase3_v4.jsonl")


def _per_replicate(df: pl.DataFrame) -> pl.DataFrame:
    """Aggregate per (mode, condition, replicate): first-try count and total cost."""
    # Older runs used a 'promotions' column; phase 3.5 uses 'events'. Be lenient.
    cols = df.columns
    events_col = "events" if "events" in cols else ("promotions" if "promotions" in cols else None)
    aggs = [
        pl.len().alias("n_episodes"),
        pl.col("first_try_success").cast(pl.Int64).sum().alias("first_try"),
        pl.col("cost_total_usd").sum().alias("total_cost"),
    ]
    if events_col:
        aggs.append(pl.col(events_col).list.len().sum().alias("events_count"))
    return (
        df.group_by(["failure_mode", "condition", "replicate"])
        .agg(aggs)
        .with_columns(first_try_rate=pl.col("first_try") / pl.col("n_episodes"))
    )


def fig_first_try(df: pl.DataFrame, out: Path) -> None:
    """Bar chart: first-try rate per (mode, condition), error bars over replicates."""
    per_rep = _per_replicate(df)
    summary = (
        per_rep.group_by(["failure_mode", "condition"])
        .agg(
            mean=pl.col("first_try_rate").mean(),
            std=pl.col("first_try_rate").std(),
            n=pl.len(),
        )
        .sort(["failure_mode", "condition"])
    )

    modes = sorted(df["failure_mode"].unique().to_list())
    conditions = ["baseline", "lessons-only", "promotion-llm", "description-augment"]
    n_modes = len(modes)
    n_conds = len(conditions)
    bar_w = 0.2
    x = np.arange(n_modes)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for ci, cond in enumerate(conditions):
        means = []
        stds = []
        for mode in modes:
            row = summary.filter((pl.col("failure_mode") == mode) & (pl.col("condition") == cond))
            if row.height == 0:
                means.append(0)
                stds.append(0)
            else:
                r = row.row(0, named=True)
                means.append(r["mean"] * 100)
                stds.append((r["std"] or 0) * 100)
        offset = (ci - (n_conds - 1) / 2) * bar_w
        ax.bar(
            x + offset, means, bar_w,
            yerr=stds, capsize=4,
            label=CONDITION_LABELS[cond],
            color=CONDITION_COLORS[cond], edgecolor="white", linewidth=1.5,
        )
        for xi, m, s in zip(x, means, stds):
            ax.text(xi + offset, m + max(s, 1) + 2, f"{m:.0f}%", ha="center", fontsize=9, color="#333")

    # Count replicates from the data
    n_reps = df["replicate"].n_unique()
    n_eps = int(df["episode_index"].max())
    ax.set_xticks(x)
    ax.set_xticklabels([f"{m}\n({n_reps} replicates × {n_eps} episodes)" for m in modes], fontsize=10)
    ax.set_ylabel("First-try success rate (%)", fontsize=11)
    ax.set_ylim(0, 110)
    ax.set_title(
        "Phase 3: lesson promotion to derived tools — first-try success across failure modes",
        fontsize=12, weight="bold", pad=12,
    )
    _style(ax)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.95)
    fig.tight_layout()
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_cost(df: pl.DataFrame, out: Path) -> None:
    """Bar chart: cost per (mode, condition)."""
    per_rep = _per_replicate(df)
    summary = (
        per_rep.group_by(["failure_mode", "condition"])
        .agg(
            mean=pl.col("total_cost").mean(),
            std=pl.col("total_cost").std(),
        )
        .sort(["failure_mode", "condition"])
    )

    modes = sorted(df["failure_mode"].unique().to_list())
    conditions = ["baseline", "lessons-only", "promotion-llm", "description-augment"]
    bar_w = 0.2
    x = np.arange(len(modes))

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for ci, cond in enumerate(conditions):
        means = []
        stds = []
        for mode in modes:
            row = summary.filter((pl.col("failure_mode") == mode) & (pl.col("condition") == cond))
            if row.height == 0:
                means.append(0); stds.append(0)
            else:
                r = row.row(0, named=True)
                means.append(r["mean"]); stds.append(r["std"] or 0)
        offset = (ci - (len(conditions) - 1) / 2) * bar_w
        ax.bar(
            x + offset, means, bar_w, yerr=stds, capsize=4,
            label=CONDITION_LABELS[cond], color=CONDITION_COLORS[cond],
            edgecolor="white", linewidth=1.5,
        )
        for xi, m, s in zip(x, means, stds):
            ax.text(xi + offset, m + max(s, 0.001) + 0.002, f"${m:.3f}", ha="center", fontsize=8, color="#333")

    ax.set_xticks(x)
    ax.set_xticklabels(modes, fontsize=10)
    ax.set_ylabel("Total cost across 5-episode sequence (USD, summed across attempts)", fontsize=11)
    ax.set_title(
        "Phase 3: total cost per 5-episode sequence (includes classifier + synth overhead)",
        fontsize=12, weight="bold", pad=12,
    )
    _style(ax)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    fig.tight_layout()
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_trajectory(df: pl.DataFrame, out: Path) -> None:
    """Per-episode first-try success rate trajectory."""
    summary = (
        df.group_by(["failure_mode", "condition", "episode_index"])
        .agg(rate=pl.col("first_try_success").cast(pl.Float64).mean())
        .sort(["failure_mode", "condition", "episode_index"])
    )

    modes = sorted(df["failure_mode"].unique().to_list())
    conditions = ["baseline", "lessons-only", "promotion-llm", "description-augment"]

    fig, axes = plt.subplots(1, len(modes), figsize=(11, 4.5), sharey=True)
    if len(modes) == 1:
        axes = [axes]
    for ax, mode in zip(axes, modes):
        for cond in conditions:
            sub = summary.filter((pl.col("failure_mode") == mode) & (pl.col("condition") == cond)).sort("episode_index")
            xs = sub["episode_index"].to_list()
            ys = [r * 100 for r in sub["rate"].to_list()]
            ax.plot(
                xs, ys, marker="o", markersize=8, linewidth=2.5,
                label=CONDITION_LABELS[cond], color=CONDITION_COLORS[cond], alpha=0.95,
            )
        ax.set_title(f"{mode}", fontsize=11, weight="bold")
        ax.set_xlabel("Episode index", fontsize=10)
        ax.set_xticks([1, 2, 3, 4, 5])
        _style(ax)
    axes[0].set_ylabel("First-try success rate (%)\n(mean across replicates)", fontsize=10)
    axes[-1].legend(loc="lower right", fontsize=8, framealpha=0.95)
    fig.suptitle(
        "Phase 3 trajectory: first-try success per episode, by failure mode",
        fontsize=12, weight="bold", y=1.02,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main():
    out_dir = Path("data/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load()
    print(f"Loaded {df.height} rows")
    print(df.group_by(["failure_mode", "condition"]).agg(n=pl.len()).sort(["failure_mode", "condition"]))
    fig_first_try(df, out_dir / "fig_p3_first_try.png")
    fig_cost(df, out_dir / "fig_p3_cost.png")
    fig_trajectory(df, out_dir / "fig_p3_trajectory.png")
    print(f"\nWrote 3 phase-3 figures to {out_dir}")


if __name__ == "__main__":
    main()
