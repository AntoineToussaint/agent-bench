"""Live-API smoke trial of the file-localization turn-loop.

Builds a tiny synthetic Python repo in a tmp dir, hands it to the
`make_turn_loop_trial` factory with a real Anthropic client, and reports
what happened. Cost target: ~$0.01-0.05.

Run:
    uv run --package file-localization python \\
        experiments/file-localization/scripts/smoke_turn_loop.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

# Load .env from a few likely locations (repo root, ~/Development, $HOME).
_HERE = Path(__file__).resolve()
for _candidate in (
    _HERE.parents[3] / ".env",                       # repo root
    Path.home() / "Development" / ".env",            # user's central env
    Path.home() / ".env",
):
    if _candidate.is_file():
        load_dotenv(_candidate, override=False)

import agent_eval
from agent_eval.pricing import cost_usd
from agent_eval.types import (
    AssistantMessage,
    ModelClient,
    ToolResult,
    Transcript,
)

from file_localization.contract import LocalizationTask
from file_localization.turn_loop_trial import (
    LocalRepoView,
    _Limits,
    make_turn_loop_trial,
)


# ---------- repo fixture (lifted from tests/test_turn_loop_trial.py) ----------


def _build_repo(root: Path) -> None:
    (root / "src" / "pricing").mkdir(parents=True)
    (root / "src" / "pricing" / "__init__.py").write_text("")
    (root / "src" / "pricing" / "calc.py").write_text(
        "def compute_total(items):\n"
        "    return sum(p for _, p in items)\n"
        "\n"
        "TAX_RATE = 0.08\n"
    )
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_calc.py").write_text(
        "from src.pricing.calc import compute_total\n"
        "\n"
        "def test_smoke(): assert compute_total([('a', 1)]) == 1\n"
    )


# ---------- transparent client wrapper to capture the transcript ----------


class _RecordingClient(ModelClient):
    """Wraps a real ModelClient so we can dump a transcript afterwards.

    The turn-loop trial keeps its `Transcript` internal — we don't have
    access to it from the outside. This wrapper records the same set of
    events as the trial would.
    """

    def __init__(self, inner: ModelClient) -> None:
        self._inner = inner
        self.name = inner.name
        self.transcript = Transcript(system="")

    def reset(self, system: str) -> None:
        self.transcript = Transcript(system=system)
        self._inner.reset(system)

    def add_user_text(self, text: str) -> None:
        self.transcript.add_user_text(text)
        self._inner.add_user_text(text)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        self.transcript.add_tool_results(results)
        self._inner.add_tool_results(results)

    def step(self, tools: list[dict]) -> AssistantMessage:
        msg = self._inner.step(tools)
        self.transcript.add_assistant(msg)
        return msg


# ---------- main ----------


def _dump_transcript(transcript: Transcript, path: Path) -> None:
    payload = {
        "system": transcript.system,
        "entries": transcript.entries,
    }
    path.write_text(json.dumps(payload, indent=2, default=str))


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set (looked in ~/Development/.env etc.)")
        return 2

    model = "claude-haiku-4-5"
    print(f"[smoke] model={model}")
    print(f"[smoke] cwd={Path.cwd()}")

    with tempfile.TemporaryDirectory(prefix="floc-smoke-") as tmp:
        root = Path(tmp)
        _build_repo(root)
        print(f"[smoke] built fixture repo at {root}")
        print(f"[smoke] files: {sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())}")

        task = LocalizationTask(
            instance_id="floc-smoke-1",
            issue_text=(
                "## compute_total ignores tax_rate\n\n"
                "Callers of `compute_total(items)` in `src/pricing/calc.py` "
                "have started passing a `tax_rate` keyword argument so that "
                "the returned subtotal includes sales tax. Today the function "
                "silently drops the kwarg and returns the pre-tax sum, which "
                "breaks downstream invoices.\n\n"
                "Please update `compute_total` so that when callers pass "
                "`tax_rate`, the returned value is `subtotal * (1 + tax_rate)`. "
                "If `tax_rate` is omitted, fall back to the module-level "
                "`TAX_RATE` constant. Add a regression test that fails on "
                "the current code and passes after your fix."
            ),
            repo="demo/pricing",
            base_commit="abc123def456",
            gold_edit_files=frozenset({"src/pricing/calc.py"}),
            gold_test_files=frozenset({"tests/test_calc.py"}),
        )

        inner = agent_eval.make_client(model)
        client = _RecordingClient(inner)

        trial = make_turn_loop_trial(
            repo_view_for=lambda _t: LocalRepoView(root),
            limits=_Limits(max_turns=8),
        )

        print(f"[smoke] running trial (max_turns=8)...")
        rec = trial(client, "turn-loop-tool_use", task)

        # Cost (the trial doesn't populate cost_usd itself).
        rec_cost = cost_usd(model, rec.usage)

        # Dump transcript.
        out_dir = Path(__file__).resolve().parent / "_smoke_out"
        out_dir.mkdir(exist_ok=True)
        transcript_path = out_dir / f"smoke_{task.task_id}__{model}.json"
        _dump_transcript(client.transcript, transcript_path)

        # Pretty report.
        print()
        print("=" * 72)
        print(f"RunRecord for {rec.task_id} ({rec.model}, condition={rec.condition})")
        print("=" * 72)
        print(f"  passed             = {rec.passed}")
        print(f"  turns              = {rec.turns}")
        print(f"  tool_calls         = {rec.tool_calls}")
        print(f"  invalid_tool_calls = {rec.invalid_tool_calls}")
        print(f"  latency_seconds    = {rec.latency_seconds:.2f}")
        print(f"  error              = {rec.error}")
        print(f"  usage              = {asdict(rec.usage)}")
        print(f"  cost_usd           = ${rec_cost:.5f}")
        print()
        print("  extra:")
        for k, v in rec.extra.items():
            print(f"    {k!s:>18} = {v}")
        print()
        print(f"  transcript dumped  -> {transcript_path}")

        # Per-turn breakdown of what tools the model called.
        print()
        print("Turn-by-turn assistant actions:")
        turn_idx = 0
        for entry in client.transcript.entries:
            if entry.get("role") != "assistant":
                continue
            turn_idx += 1
            calls = entry.get("tool_calls", [])
            if not calls:
                txt = (entry.get("text") or "").strip().splitlines()[:1]
                snippet = txt[0][:120] if txt else "(empty)"
                print(f"  T{turn_idx}: no tool_use, text=\"{snippet}\"")
            else:
                for c in calls:
                    args_preview = ", ".join(
                        f"{k}={json.dumps(v) if not isinstance(v, str) else repr(v)[:60]}"
                        for k, v in (c.get("arguments") or {}).items()
                    )
                    print(f"  T{turn_idx}: {c['name']}({args_preview})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
