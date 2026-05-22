"""Smoke tests — no network. Verify the library wires together correctly."""

from __future__ import annotations

from pathlib import Path

from agent_eval import (
    Budget,
    MODELS,
    RunRecord,
    Sweep,
    TurnUsage,
    cost_usd,
)
from agent_eval.reports import write_csv, write_markdown, summarize_markdown
from agent_eval.sweep.budget import BudgetExceeded


def test_models_registry_nonempty() -> None:
    assert "claude-sonnet-4-6" in MODELS
    assert "gpt-5" in MODELS


def test_cost_usd_basic() -> None:
    usage = TurnUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    # Sonnet 4.6 priced at $3/Mtok input, $15/Mtok output.
    cost = cost_usd("claude-sonnet-4-6", usage)
    assert abs(cost - 18.0) < 0.001


def test_budget_caps() -> None:
    b = Budget(cap_usd=1.0)
    b.add(0.4)
    b.add(0.5)
    try:
        b.add(0.2)
    except BudgetExceeded:
        pass
    else:
        raise AssertionError("expected BudgetExceeded")
    assert b.spent_usd == 0.9


def _fake_trial(_client, condition: str, task: str) -> RunRecord:
    """Trial that doesn't hit the network — for plumbing tests."""
    return RunRecord(
        task_id=task,
        model="claude-sonnet-4-6",
        condition=condition,
        passed=condition == "good",
        turns=1,
        tool_calls=1,
        invalid_tool_calls=0,
        usage=TurnUsage(input_tokens=1000, output_tokens=500),
        latency_seconds=0.1,
    )


def test_sweep_grid_and_run() -> None:
    sweep = Sweep(
        models=["claude-sonnet-4-6"],
        conditions=["good", "bad"],
        tasks=["t1", "t2"],
        trial=_fake_trial,
    )
    grid = sweep.grid()
    assert len(grid) == 4
    records = sweep.run()
    assert len(records) == 4
    assert sum(r.passed for r in records) == 2


def test_sweep_costs_are_billed() -> None:
    sweep = Sweep(
        models=["claude-sonnet-4-6"],
        conditions=["good"],
        tasks=["t1"],
        trial=_fake_trial,
    )
    records = sweep.run()
    # 1000 input * $3/M + 500 output * $15/M = $0.0105
    assert abs(records[0].cost_usd - 0.0105) < 1e-6


def test_reports_render(tmp_path: Path) -> None:
    sweep = Sweep(
        models=["claude-sonnet-4-6"],
        conditions=["good", "bad"],
        tasks=["t1", "t2"],
        trial=_fake_trial,
    )
    records = sweep.run()
    write_csv(records, tmp_path / "sweep.csv")
    write_markdown(records, tmp_path / "sweep.md")
    md = (tmp_path / "sweep.md").read_text()
    assert "pass@1" in md
    assert "## Pass matrix" in md
    csv_text = (tmp_path / "sweep.csv").read_text()
    assert "claude-sonnet-4-6" in csv_text
