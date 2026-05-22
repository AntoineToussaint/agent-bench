"""Generate the headline figures from the sweep data.

Reads sweep_rich_wide.jsonl (39-tool data) + sweep_bloat.jsonl (80, 150-tool data),
combines them, recomputes wall-clock latency for two-phase rows, and emits 4 PNGs
under data/figures/:

  fig01_pareto_cost_accuracy.png    — cost × success per architecture
  fig02_bloat_tax_curve.png         — cost-per-success vs catalog size
  fig03_accuracy_curve.png          — success rate vs catalog size
  fig04_cost_vs_latency.png         — wall-clock latency × cost

Usage:
  uv run python scripts/figures.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import polars as pl


# ---------- load + clean ----------


def _wallclock(row: dict) -> float:
    pipeline = row.get("pipeline", []) or []
    phase = row.get("phase", "")
    if not pipeline:
        return float(row.get("total_latency_ms", 0))
    if any(s.get("parallel_group") is not None for s in pipeline):
        seq = sum(s["latency_ms"] for s in pipeline if s.get("parallel_group") is None)
        groups: dict[int, list[float]] = {}
        for s in pipeline:
            g = s.get("parallel_group")
            if g is not None:
                groups.setdefault(g, []).append(s["latency_ms"])
        return seq + sum(max(v) for v in groups.values())
    if phase.startswith("2phase") and len(pipeline) >= 2:
        return pipeline[0]["latency_ms"] + max(s["latency_ms"] for s in pipeline[1:])
    return sum(s["latency_ms"] for s in pipeline)


def load_combined() -> pl.DataFrame:
    rich_wide = pl.read_ndjson("data/runs/sweep_rich_wide.jsonl").filter(
        pl.col("granularity") == "narrow-rich"
    )
    bloat = pl.read_ndjson("data/runs/sweep_bloat.jsonl")
    df = pl.concat([rich_wide, bloat], how="diagonal_relaxed")
    df = df.with_columns(pl.Series("wall_ms", [_wallclock(r) for r in df.iter_rows(named=True)]))
    return df


def aggregate(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.group_by(["phase", "model", "granularity"])
        .agg(
            n=pl.len(),
            success=pl.col("success").cast(pl.Float64).mean(),
            cost=pl.col("total_cost_usd").mean(),
            wall_s=(pl.col("wall_ms") / 1000).mean(),
        )
        .with_columns(
            cost_per_success=pl.when(pl.col("success") > 0)
            .then(pl.col("cost") / pl.col("success"))
            .otherwise(None),
            tool_count=pl.col("granularity").map_elements(
                lambda g: {"narrow-rich": 39, "narrow-rich-80": 80, "narrow-rich-150": 150}[g],
                return_dtype=pl.Int64,
            ),
            arch=pl.col("phase") + " · " + pl.col("model").map_elements(
                lambda m: m.split("-")[1], return_dtype=pl.Utf8
            ),
        )
    )


# ---------- style ----------

ARCH_COLORS = {
    "1phase · haiku":                       "#2563eb",  # blue
    "1phase · sonnet":                      "#dc2626",  # red — the catastrophe
    "2phase · haiku":                       "#16a34a",  # green — the winner
    "2phase · sonnet":                      "#0891b2",  # cyan
    "2phase-sel-haiku-args-sonnet · haiku": "#9333ea",  # purple — mixed
    "2phase-sel-haiku-args-sonnet · sonnet":"#9333ea",  # same color (model param ignored for mixed phase)
}

ARCH_LABELS = {
    "1phase · haiku":                       "1phase × Haiku",
    "1phase · sonnet":                      "1phase × Sonnet",
    "2phase · haiku":                       "2phase × Haiku-Haiku",
    "2phase · sonnet":                      "2phase × Sonnet-Sonnet",
    "2phase-sel-haiku-args-sonnet · haiku": "2phase mixed (Haiku→Sonnet)",
    "2phase-sel-haiku-args-sonnet · sonnet":"2phase mixed (Haiku→Sonnet)",
}

ARCH_ORDER = [
    "1phase · sonnet",
    "1phase · haiku",
    "2phase · sonnet",
    "2phase-sel-haiku-args-sonnet · haiku",
    "2phase · haiku",
]


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, alpha=0.25, linestyle=":")
    ax.tick_params(labelsize=9)


def _arch_lines(ax, agg: pl.DataFrame, x_col: str, y_col: str, log_y: bool = False):
    """Plot one line per architecture, with markers at each catalog size."""
    plotted_labels = set()
    for arch in ARCH_ORDER:
        sub = agg.filter(pl.col("arch") == arch).sort("tool_count")
        if sub.height == 0:
            continue
        xs = sub[x_col].to_list()
        ys = sub[y_col].to_list()
        # Dedup: for mixed (the model param doesn't matter), only label once
        label = ARCH_LABELS[arch] if ARCH_LABELS[arch] not in plotted_labels else None
        plotted_labels.add(ARCH_LABELS[arch])
        ax.plot(
            xs, ys,
            color=ARCH_COLORS[arch],
            marker="o", markersize=7, linewidth=2.4,
            label=label, alpha=0.95,
        )
    if log_y:
        ax.set_yscale("log")


# ---------- figures ----------


def fig01_pareto(agg: pl.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    for arch in ARCH_ORDER:
        sub = agg.filter(pl.col("arch") == arch).sort("tool_count")
        if sub.height == 0:
            continue
        # Size scales with catalog count; marker increases with tool count
        sizes = [50 + tc * 1.2 for tc in sub["tool_count"].to_list()]
        ax.scatter(
            sub["cost"].to_list(),
            (pl.Series(sub["success"]) * 100).to_list(),
            s=sizes,
            color=ARCH_COLORS[arch],
            label=ARCH_LABELS[arch] if arch != "2phase-sel-haiku-args-sonnet · sonnet" else None,
            edgecolor="white", linewidth=1.3, alpha=0.9, zorder=3,
        )
        # Connecting line showing catalog-size progression
        ax.plot(
            sub["cost"].to_list(),
            (pl.Series(sub["success"]) * 100).to_list(),
            color=ARCH_COLORS[arch], alpha=0.4, linewidth=1.2, zorder=2,
        )
    # Annotate catalog sizes for one reference architecture (1phase Haiku)
    ref = agg.filter(pl.col("arch") == "1phase · haiku").sort("tool_count")
    for tc, c, s in zip(ref["tool_count"], ref["cost"], ref["success"]):
        ax.annotate(
            f"{tc}", (c, s * 100),
            textcoords="offset points", xytext=(8, -3), fontsize=8, color="#444",
        )

    ax.set_xscale("log")
    ax.set_xlabel("Cost per query (USD, log scale)", fontsize=11)
    ax.set_ylabel("One-shot success rate (%)", fontsize=11)
    ax.set_title(
        "Cost × accuracy Pareto across catalog sizes (39 → 80 → 150 tools)",
        fontsize=12, weight="bold", pad=12,
    )
    ax.set_ylim(0, 105)
    _style(ax)
    ax.legend(loc="lower right", fontsize=9, frameon=True, framealpha=0.95)
    fig.text(
        0.5, -0.02,
        "Marker size scales with catalog count (39 / 80 / 150 tools). Numbers annotate sizes on the 1phase-Haiku line.",
        ha="center", fontsize=8, color="#666",
    )
    fig.tight_layout()
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig02_bloat_tax(agg: pl.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    _arch_lines(ax, agg, "tool_count", "cost_per_success", log_y=True)
    ax.set_xlabel("Catalog size (tools)", fontsize=11)
    ax.set_ylabel("Cost per successful query (USD, log scale)", fontsize=11)
    ax.set_title(
        "Bloat-tax curve: cost-per-success as catalog grows",
        fontsize=12, weight="bold", pad=12,
    )
    # Reference markers for real-world scales
    ax.axvline(39, color="#999", linestyle=":", linewidth=1, alpha=0.6)
    ax.axvline(80, color="#999", linestyle=":", linewidth=1, alpha=0.6)
    ax.axvline(150, color="#999", linestyle=":", linewidth=1, alpha=0.6)
    ymin, ymax = ax.get_ylim()
    ax.text(80, ymax * 0.7, "≈ real GitHub MCP", fontsize=8, color="#666", ha="center", rotation=90)
    ax.text(150, ymax * 0.7, "multi-MCP setup", fontsize=8, color="#666", ha="center", rotation=90)
    _style(ax)
    ax.legend(loc="lower right", fontsize=9, frameon=True, framealpha=0.95)
    fig.tight_layout()
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig03_accuracy_curve(agg: pl.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    plotted = set()
    for arch in ARCH_ORDER:
        sub = agg.filter(pl.col("arch") == arch).sort("tool_count")
        if sub.height == 0:
            continue
        label = ARCH_LABELS[arch] if ARCH_LABELS[arch] not in plotted else None
        plotted.add(ARCH_LABELS[arch])
        ax.plot(
            sub["tool_count"].to_list(),
            [s * 100 for s in sub["success"].to_list()],
            color=ARCH_COLORS[arch], marker="o", markersize=7, linewidth=2.4,
            label=label, alpha=0.95,
        )
    ax.set_xlabel("Catalog size (tools)", fontsize=11)
    ax.set_ylabel("One-shot success rate (%)", fontsize=11)
    ax.set_title(
        "Accuracy vs catalog size: two-phase stays flat, one-phase doesn't",
        fontsize=12, weight="bold", pad=12,
    )
    ax.set_ylim(0, 105)
    ax.axvline(39, color="#999", linestyle=":", linewidth=1, alpha=0.6)
    ax.axvline(80, color="#999", linestyle=":", linewidth=1, alpha=0.6)
    ax.axvline(150, color="#999", linestyle=":", linewidth=1, alpha=0.6)
    _style(ax)
    ax.legend(loc="lower left", fontsize=9, frameon=True, framealpha=0.95)
    fig.tight_layout()
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig04_cost_vs_latency(agg: pl.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    for arch in ARCH_ORDER:
        sub = agg.filter(pl.col("arch") == arch).sort("tool_count")
        if sub.height == 0:
            continue
        sizes = [50 + tc * 1.2 for tc in sub["tool_count"].to_list()]
        ax.scatter(
            sub["wall_s"].to_list(), sub["cost"].to_list(),
            s=sizes, color=ARCH_COLORS[arch],
            label=ARCH_LABELS[arch] if arch != "2phase-sel-haiku-args-sonnet · sonnet" else None,
            edgecolor="white", linewidth=1.3, alpha=0.9, zorder=3,
        )
        ax.plot(
            sub["wall_s"].to_list(), sub["cost"].to_list(),
            color=ARCH_COLORS[arch], alpha=0.4, linewidth=1.2, zorder=2,
        )
    ax.set_xlabel("Wall-clock latency per query (seconds)", fontsize=11)
    ax.set_ylabel("Cost per query (USD, log scale)", fontsize=11)
    ax.set_yscale("log")
    ax.set_title(
        "Cost × latency: two-phase pays a small latency premium for big cost savings",
        fontsize=12, weight="bold", pad=12,
    )
    _style(ax)
    ax.legend(loc="upper right", fontsize=9, frameon=True, framealpha=0.95)
    fig.text(
        0.5, -0.02,
        "Marker size scales with catalog count (39 / 80 / 150 tools). Lower-left is better.",
        ha="center", fontsize=8, color="#666",
    )
    fig.tight_layout()
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------- main ----------


def main() -> int:
    out_dir = Path("data/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_combined()
    agg = aggregate(df)
    print(f"Loaded {df.height} runs; {agg.height} (phase × model × granularity) cells")

    fig01_pareto(agg, out_dir / "fig01_pareto_cost_accuracy.png")
    fig02_bloat_tax(agg, out_dir / "fig02_bloat_tax_curve.png")
    fig03_accuracy_curve(agg, out_dir / "fig03_accuracy_curve.png")
    fig04_cost_vs_latency(agg, out_dir / "fig04_cost_vs_latency.png")

    print("Wrote 4 figures to data/figures/")
    for p in sorted(out_dir.glob("*.png")):
        print(f"  {p}  ({p.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
