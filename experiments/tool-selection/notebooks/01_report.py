"""Strategy verdict notebook — Pareto analysis of one-shot tool-calling.

Run: `uv run marimo edit notebooks/01_report.py`

Inputs: data/runs/sweep_*.jsonl (one row per (strategy × granularity × model × task))

Outputs:
  - Success rate per strategy (overall, per-granularity, per-difficulty)
  - Cost-per-query distribution per strategy
  - Latency-per-query distribution per strategy
  - Pareto frontier: cost vs success-rate
  - Per-strategy failure mode breakdown (hallucinations / forbidden / schema)
"""

import marimo

__generated_with = "0.23.5"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    from pathlib import Path
    import polars as pl
    import altair as alt

    return alt, mo, pl, Path


@app.cell
def _(Path, pl):
    runs_dir = Path("data/runs")
    files = sorted(runs_dir.glob("sweep_*.jsonl"))
    df = pl.concat([pl.read_ndjson(f) for f in files]) if files else pl.DataFrame()
    df.shape, files
    return df, files


@app.cell
def _(df, mo):
    mo.md(
        f"""
        # Tool-selection strategy verdict

        Loaded **{df.height} runs** across {df['strategy'].n_unique() if df.height else 0} strategies,
        {df['granularity'].n_unique() if df.height else 0} granularities,
        {df['model'].n_unique() if df.height else 0} final-shot models,
        {df['task_id'].n_unique() if df.height else 0} tasks.

        Goal: find the **most efficient pipeline** for one-shot tool-call correctness.
        Efficiency = (success rate) / (cost-per-query, latency).
        """
    )
    return


@app.cell
def _(df, pl):
    if df.height == 0:
        summary = pl.DataFrame()
    else:
        summary = (
            df.group_by(["strategy", "granularity"])
            .agg(
                n=pl.len(),
                success_rate=pl.col("success").cast(pl.Float64).mean(),
                avg_cost=pl.col("total_cost_usd").mean(),
                p50_cost=pl.col("total_cost_usd").median(),
                avg_latency_ms=pl.col("total_latency_ms").mean(),
                p50_latency_ms=pl.col("total_latency_ms").median(),
                avg_surfaced=pl.col("surfaced_count").mean(),
                hallucination_rate=pl.col("hallucinated").list.len().cast(pl.Float64).mean(),
                forbidden_rate=pl.col("forbidden_called").list.len().cast(pl.Float64).mean(),
                schema_err_rate=pl.col("schema_invalid").list.len().cast(pl.Float64).mean(),
            )
            .sort(["granularity", "success_rate", "avg_cost"], descending=[False, True, False])
        )
    summary
    return (summary,)


@app.cell
def _(alt, mo, summary):
    if summary.height == 0:
        chart = mo.md("_(no data yet — run `scripts/run_sweep.py` first)_")
    else:
        df = summary.to_pandas()
        chart = (
            alt.Chart(df)
            .mark_circle(size=160, opacity=0.85)
            .encode(
                x=alt.X("avg_cost:Q", title="Avg cost per query (USD)", scale=alt.Scale(type="log")),
                y=alt.Y("success_rate:Q", title="One-shot success rate", scale=alt.Scale(domain=[0, 1.05])),
                color="strategy:N",
                shape="granularity:N",
                tooltip=["strategy", "granularity", "success_rate", "avg_cost", "avg_latency_ms", "n"],
            )
            .properties(width=720, height=420, title="Cost × correctness Pareto")
            .interactive()
        )
    chart
    return


@app.cell
def _(alt, mo, summary):
    if summary.height == 0:
        chart2 = mo.md("")
    else:
        df = summary.to_pandas()
        chart2 = (
            alt.Chart(df)
            .mark_circle(size=160, opacity=0.85)
            .encode(
                x=alt.X("avg_latency_ms:Q", title="Avg latency per query (ms)", scale=alt.Scale(type="log")),
                y=alt.Y("success_rate:Q", title="One-shot success rate", scale=alt.Scale(domain=[0, 1.05])),
                color="strategy:N",
                shape="granularity:N",
                tooltip=["strategy", "granularity", "success_rate", "avg_latency_ms", "avg_cost", "n"],
            )
            .properties(width=720, height=420, title="Latency × correctness Pareto")
            .interactive()
        )
    chart2
    return


@app.cell
def _(df, mo, pl):
    if df.height == 0:
        per_diff = pl.DataFrame()
    else:
        per_diff = (
            df.group_by(["strategy", "task_difficulty"])
            .agg(
                n=pl.len(),
                success_rate=pl.col("success").cast(pl.Float64).mean(),
            )
            .pivot(values="success_rate", index="strategy", on="task_difficulty")
            .sort("strategy")
        )
    mo.md("### Success rate per (strategy × difficulty)")
    return (per_diff,)


@app.cell
def _(per_diff):
    per_diff
    return


@app.cell
def _(df, mo, pl):
    if df.height == 0:
        failures = pl.DataFrame()
    else:
        failures = (
            df.filter(~pl.col("success"))
            .select(
                "strategy", "granularity", "task_id", "task_difficulty",
                "required_matched", "required_total",
                "missing", "hallucinated", "forbidden_called", "schema_invalid",
                "surfaced_count", "n_calls",
            )
            .sort(["task_difficulty", "strategy"])
        )
    mo.md(f"### All failures ({failures.height})")
    return (failures,)


@app.cell
def _(failures):
    failures
    return


@app.cell
def _(df, mo, pl):
    if df.height == 0:
        verdict_md = mo.md("_(no data — run the sweep first)_")
    else:
        # Pick the strategy that wins on success rate, ties broken by cost
        agg = (
            df.group_by("strategy")
            .agg(
                success=pl.col("success").cast(pl.Float64).mean(),
                avg_cost=pl.col("total_cost_usd").mean(),
                avg_latency_ms=pl.col("total_latency_ms").mean(),
            )
            .sort(["success", "avg_cost"], descending=[True, False])
        )
        if agg.height > 0:
            top = agg.row(0, named=True)
            verdict_md = mo.md(
                f"""
                ## Verdict
                **Best overall strategy: `{top["strategy"]}`** —
                {top["success"]:.0%} success rate at ${top["avg_cost"]:.4f}/query, {top["avg_latency_ms"]:.0f}ms latency.

                Full ranking (success-rate first, cost tiebreaker):
                """
            )
        else:
            verdict_md = mo.md("_(no aggregable data)_")
    verdict_md
    return (agg,)


@app.cell
def _(agg):
    agg
    return


if __name__ == "__main__":
    app.run()
