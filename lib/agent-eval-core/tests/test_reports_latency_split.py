"""Reporting of the TTFT/generate latency split + decode throughput (NEXT.md #32).

Covers the derived metrics on TurnUsage and their propagation through the
per-record CSV, the per-cell aggregate, and the markdown "Latency split"
section (which must appear only when something streamed).
"""

from __future__ import annotations

from pathlib import Path

from agent_eval import RunRecord, TurnUsage
from agent_eval.reports import (
    aggregate_cells,
    summarize_markdown,
    write_aggregate_csv,
    write_csv,
)


def _rec(task="t1", model="m", condition="c", *, out_tok=500, ttft=0.5, gen=2.0, rep=0):
    return RunRecord(
        task_id=task, model=model, condition=condition, passed=True, turns=1,
        tool_calls=1, invalid_tool_calls=0,
        usage=TurnUsage(input_tokens=1000, output_tokens=out_tok,
                        ttft_seconds=ttft, generate_seconds=gen),
        latency_seconds=ttft + gen, replicate=rep,
    )


# --- derived metrics on TurnUsage ---
def test_decode_tokens_per_s_and_fraction() -> None:
    u = TurnUsage(output_tokens=500, ttft_seconds=0.5, generate_seconds=2.0)
    assert u.decode_tokens_per_s == 250.0        # 500 / 2.0
    assert abs(u.ttft_fraction - 0.2) < 1e-9     # 0.5 / 2.5


def test_derived_metrics_guard_zero_generate() -> None:
    # Non-streaming stub: generate time unknown → rates are 0, not a crash.
    u = TurnUsage(output_tokens=500)
    assert u.decode_tokens_per_s == 0.0
    assert u.ttft_fraction == 0.0


# --- per-record CSV ---
def test_per_record_csv_has_split_columns(tmp_path: Path) -> None:
    out = tmp_path / "trials.csv"
    write_csv([_rec()], out)
    header, row = out.read_text().splitlines()[:2]
    for col in ("ttft_seconds", "generate_seconds", "decode_tokens_per_s"):
        assert col in header
    # decode = 500 / 2.0 = 250.0
    assert "250.0" in row
    assert "0.500" in row  # ttft


# --- aggregate ---
def test_aggregate_cells_carries_split() -> None:
    recs = [_rec(out_tok=t, gen=g, rep=i)
            for i, (t, g) in enumerate([(400, 2.0), (600, 2.0), (500, 2.5)])]
    (c,) = aggregate_cells(recs)
    # generate p50 over [2.0, 2.0, 2.5] = 2.0
    assert c.generate_seconds[1] == 2.0
    assert c.ttft_seconds[1] == 0.5
    # throughput per rec: 200, 300, 200 -> p50 = 200
    assert c.decode_tokens_per_s[1] == 200.0


def test_aggregate_throughput_ignores_non_streamed() -> None:
    # One streamed + one non-streamed replicate: the 0-rate row must not drag
    # the throughput percentile down.
    streamed = _rec(out_tok=500, gen=2.0, rep=0)
    non_streamed = RunRecord(
        task_id="t1", model="m", condition="c", passed=True, turns=1,
        tool_calls=1, invalid_tool_calls=0,
        usage=TurnUsage(input_tokens=1000, output_tokens=500),  # gen=0
        latency_seconds=3.0, replicate=1,
    )
    (c,) = aggregate_cells([streamed, non_streamed])
    assert c.decode_tokens_per_s == (250.0, 250.0, 250.0)  # only the streamed one


def test_aggregate_csv_has_split_columns(tmp_path: Path) -> None:
    out = tmp_path / "agg.csv"
    write_aggregate_csv([_rec(rep=0), _rec(rep=1)], out)
    header = out.read_text().splitlines()[0]
    for col in ("ttft_p50", "generate_p50", "decode_tps_p50"):
        assert col in header


# --- markdown ---
def test_markdown_shows_split_when_streamed() -> None:
    md = summarize_markdown([_rec()])
    assert "Latency split (TTFT vs generate)" in md
    assert "decode tok/s" in md
    assert "ttft_frac" in md


def test_markdown_omits_split_when_not_streamed() -> None:
    # All generate_seconds == 0 (stub client) → no zero-filled table.
    plain = RunRecord(
        task_id="t1", model="m", condition="c", passed=True, turns=1,
        tool_calls=1, invalid_tool_calls=0, usage=TurnUsage(), latency_seconds=0.1,
    )
    md = summarize_markdown([plain])
    assert "Latency split" not in md


def test_markdown_split_in_replicate_mode() -> None:
    recs = [_rec(rep=r) for r in range(3)]
    md = summarize_markdown(recs)
    assert "Latency split (TTFT vs generate)" in md
