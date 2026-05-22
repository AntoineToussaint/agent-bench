"""Minimal end-to-end example.

Runs a tiny 2x2 sweep with a fake (offline) trial fn so it works without API keys.
For a real run, swap `fake_trial` for a function that hits the model.

Usage:
    uv run python examples/minimal_sweep.py
"""

from __future__ import annotations

from pathlib import Path

from agent_eval import RunRecord, Sweep, TurnUsage
from agent_eval.reports import summarize_markdown, write_csv, write_markdown


def fake_trial(_client, condition: str, task: str) -> RunRecord:
    """A trial that doesn't hit the network — placeholder."""
    return RunRecord(
        task_id=task,
        model="claude-sonnet-4-6",
        condition=condition,
        passed=(condition == "easy"),
        turns=1,
        tool_calls=1,
        invalid_tool_calls=0,
        usage=TurnUsage(input_tokens=1000, output_tokens=500),
        latency_seconds=0.1,
    )


def main() -> None:
    sweep = Sweep(
        models=["claude-sonnet-4-6"],
        conditions=["easy", "hard"],
        tasks=["arithmetic", "regex", "json-parse"],
        trial=fake_trial,
    )
    records = sweep.run()
    out = Path("examples/out")
    write_csv(records, out / "sweep.csv")
    write_markdown(records, out / "sweep.md")
    print(summarize_markdown(records))
    print(f"\nWrote {len(records)} records to {out}/")


if __name__ == "__main__":
    main()
