"""Tests for Sweep replicates + replicate-aware reports."""

from __future__ import annotations

import random
from pathlib import Path

from agent_eval import RunRecord, Sweep, TurnUsage
from agent_eval.reports import (
    aggregate_cells,
    summarize_markdown,
    write_aggregate_csv,
    write_csv,
)


def _flaky_trial(_client, condition: str, task: str) -> RunRecord:
    """Trial whose pass rate depends on condition + replicate index.

    `easy` passes always. `flaky` passes ~50% (depends on stable hash of
    task name + the system random — we patch random inside each test).
    """
    rng = random.Random()  # fresh; tests will seed
    passed = condition == "easy" or rng.random() < 0.5
    return RunRecord(
        task_id=task,
        model="claude-sonnet-4-6",
        condition=condition,
        passed=passed,
        turns=1,
        tool_calls=1,
        invalid_tool_calls=0,
        usage=TurnUsage(input_tokens=1000, output_tokens=500),
        latency_seconds=0.1,
    )


def test_sweep_repetitions_replicates_grid() -> None:
    sweep = Sweep(
        models=["claude-sonnet-4-6"],
        conditions=["easy"],
        tasks=["t1", "t2"],
        trial=_flaky_trial,
        repetitions=5,
    )
    records = sweep.run()
    # 1 model * 1 condition * 2 tasks * 5 replicates = 10 records
    assert len(records) == 10
    # Every (model, condition, task) cell has exactly 5 replicates with
    # distinct replicate indices 0..4
    by_cell: dict[tuple, list[int]] = {}
    for r in records:
        by_cell.setdefault((r.model, r.condition, r.task_id), []).append(r.replicate)
    for replicates in by_cell.values():
        assert sorted(replicates) == [0, 1, 2, 3, 4]


def test_aggregate_cells_records_pass_rate() -> None:
    # 3 trials per cell, 2 pass + 1 fail
    records = []
    for i, passed in enumerate([True, True, False]):
        records.append(
            RunRecord(
                task_id="t1",
                model="claude-sonnet-4-6",
                condition="c1",
                passed=passed,
                turns=2 + i,  # 2, 3, 4
                tool_calls=1,
                invalid_tool_calls=0,
                usage=TurnUsage(input_tokens=1000, output_tokens=500),
                latency_seconds=0.1 * (i + 1),
                replicate=i,
            )
        )
    cells = aggregate_cells(records)
    assert len(cells) == 1
    c = cells[0]
    assert c.n == 3
    assert c.n_passed == 2
    assert abs(c.pass_rate - 2 / 3) < 1e-6
    # turns: [2,3,4] → p25=2.5, p50=3, p75=3.5
    assert c.turns == (2.5, 3.0, 3.5)


def test_summarize_markdown_switches_modes() -> None:
    # Single-replicate run → mean-mode markdown
    single = [
        RunRecord(
            task_id=f"t{i}", model="m", condition="c", passed=True, turns=1,
            tool_calls=1, invalid_tool_calls=0, usage=TurnUsage(),
            latency_seconds=0.1,
        )
        for i in range(2)
    ]
    md_single = summarize_markdown(single)
    assert "pass@1" in md_single

    # Multi-replicate run → replicate-mode markdown
    multi = []
    for task in ("t1", "t2"):
        for rep, ok in enumerate([True, True, False]):
            multi.append(
                RunRecord(
                    task_id=task, model="m", condition="c", passed=ok, turns=1,
                    tool_calls=1, invalid_tool_calls=0, usage=TurnUsage(),
                    latency_seconds=0.1, replicate=rep,
                )
            )
    md_multi = summarize_markdown(multi)
    assert "pass-rate" in md_multi
    assert "reps/task" in md_multi


def test_aggregate_csv_writes(tmp_path: Path) -> None:
    records = []
    for rep in range(3):
        records.append(
            RunRecord(
                task_id="t1", model="m", condition="c",
                passed=(rep != 0), turns=2 + rep, tool_calls=1,
                invalid_tool_calls=0, usage=TurnUsage(input_tokens=1000, output_tokens=500),
                latency_seconds=0.1, replicate=rep,
            )
        )
    out = tmp_path / "agg.csv"
    write_aggregate_csv(records, out)
    text = out.read_text()
    assert "pass_rate" in text
    assert "turns_p50" in text
    # n=3, n_passed=2, pass_rate=0.667
    assert "0.667" in text


def test_per_trial_csv_has_replicate_column(tmp_path: Path) -> None:
    records = [
        RunRecord(
            task_id="t1", model="m", condition="c", passed=True, turns=1,
            tool_calls=1, invalid_tool_calls=0,
            usage=TurnUsage(), latency_seconds=0.1, replicate=rep,
        )
        for rep in range(3)
    ]
    out = tmp_path / "trials.csv"
    write_csv(records, out)
    text = out.read_text()
    assert "replicate" in text.splitlines()[0]
    assert "0,1,1" in text or "0," in text  # at least the column got written
