"""Offline wiring test for run_cascade — uses a stub ModelClient (no network).

Validates the parts that are easy to get wrong without spending API calls:
  - tier 0 drafts, later tiers correct, edits land in ONE workdir (no re-materialize)
  - cost is summed PER TIER at each tier's own model price
  - diff style routes through the format's str_replace; rewrite style uses write_file
  - first_passing_tier is recorded when a tier's edit makes the oracle pass
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent_eval.types import AssistantMessage, ToolCall, TurnUsage
from code_editing.contract import EditTask
from code_editing.formats import FORMAT_REGISTRY
from code_editing.bench.runner import run_cascade


class StubClient:
    """A scripted ModelClient: each .step() pops the next queued response.

    `name` must be a real priced model so cost_usd is non-zero.
    """

    def __init__(self, name: str, responses: list[AssistantMessage]):
        self.name = name
        self._responses = list(responses)
        self.system: str | None = None

    def reset(self, system: str) -> None:
        self.system = system

    def add_user_text(self, text: str) -> None:  # noqa: D401
        pass

    def add_tool_results(self, results) -> None:  # noqa: D401
        pass

    def step(self, tools, tool_choice=None) -> AssistantMessage:
        return self._responses.pop(0)


def _msg(tool_calls, in_tok, out_tok, ttft=0.0, gen=0.0) -> AssistantMessage:
    return AssistantMessage(
        text="", tool_calls=tool_calls,
        usage=TurnUsage(input_tokens=in_tok, output_tokens=out_tok,
                        ttft_seconds=ttft, generate_seconds=gen),
    )


@pytest.fixture
def buggy_task(tmp_path):
    """Minimal task: target.py must define add() correctly for the oracle."""
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "target.py").write_text("def add(a, b):\n    return a - b\n")
    # oracle/ is merged after fixture by materialize(); overlay tests put the
    # workdir root on sys.path themselves, exactly like the real v2 tasks.
    oracle = tmp_path / "oracle" / "_overlay" / "tests"
    oracle.mkdir(parents=True)
    (oracle / "test_add.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[2]))\n"
        "\n"
        "def test_add():\n"
        "    import target\n"
        "    assert target.add(2, 3) == 5\n"
    )
    return EditTask(
        task_id="stub_add__medium",
        language="python",
        category="localized_bug",
        fixture_dir=fixture,
        instructions="Fix add() so it returns a + b.",
        oracle_cmd=["python", "-m", "pytest", "-q", "_overlay/tests/"],
        files_in_context=["target.py"],
    )


def test_cascade_diff_corrects_draft_and_sums_cost(buggy_task):
    fmt = FORMAT_REGISTRY["search_replace"]()
    # Tier 0 (haiku) draft: wrong edit (a * b) — still fails the oracle.
    draft = StubClient("claude-haiku-4-5", [_msg(
        [ToolCall("str_replace", {"path": "target.py",
                                  "old_str": "return a - b", "new_str": "return a * b"}, "c0")],
        in_tok=1000, out_tok=400,
    )])
    # Tier 1 (opus) correction: small diff that fixes it (-> a + b).
    fix = StubClient("claude-opus-4-8", [_msg(
        [ToolCall("str_replace", {"path": "target.py",
                                  "old_str": "return a * b", "new_str": "return a + b"}, "c1")],
        in_tok=1200, out_tok=80,
    )])

    with tempfile.TemporaryDirectory() as tmp:
        rec = run_cascade(buggy_task, [draft, fix], fmt, Path(tmp),
                          correction_style="diff", condition_name="patch-cascade-2")

    assert rec.passed is True
    # draft alone did NOT pass; the correction tier flipped it.
    assert rec.extra["draft_passed"] is False
    assert rec.extra["first_passing_tier"] == 1
    # cost summed per tier at each model's price:
    #   haiku 1/5: 1000*1 + 400*5 = 3000 / 1e6 = 0.003
    #   opus  5/25: 1200*5 + 80*25 = 8000 / 1e6 = 0.008
    assert rec.cost_usd == pytest.approx(0.011, rel=1e-6)
    assert rec.usage.output_tokens == 480  # 400 + 80
    assert rec.extra["top_tier_output_tokens"] == 80
    assert [t["model"] for t in rec.extra["per_tier"]] == [
        "claude-haiku-4-5", "claude-opus-4-8"]


def test_cascade_sums_ttft_and_generate(buggy_task):
    """Latency decomposition (NEXT.md #32) is summed across tiers."""
    fmt = FORMAT_REGISTRY["search_replace"]()
    draft = StubClient("claude-haiku-4-5", [_msg(
        [ToolCall("str_replace", {"path": "target.py",
                                  "old_str": "return a - b", "new_str": "return a * b"}, "c0")],
        in_tok=1000, out_tok=400, ttft=0.5, gen=2.0,
    )])
    fix = StubClient("claude-opus-4-8", [_msg(
        [ToolCall("str_replace", {"path": "target.py",
                                  "old_str": "return a * b", "new_str": "return a + b"}, "c1")],
        in_tok=1200, out_tok=80, ttft=0.8, gen=0.6,
    )])
    with tempfile.TemporaryDirectory() as tmp:
        rec = run_cascade(buggy_task, [draft, fix], fmt, Path(tmp), correction_style="diff")
    assert rec.usage.ttft_seconds == pytest.approx(1.3)      # 0.5 + 0.8
    assert rec.usage.generate_seconds == pytest.approx(2.6)  # 2.0 + 0.6
    assert [t["ttft_s"] for t in rec.extra["per_tier"]] == [0.5, 0.8]


def test_cascade_rewrite_uses_write_file(buggy_task):
    fmt = FORMAT_REGISTRY["search_replace"]()
    draft = StubClient("claude-haiku-4-5", [_msg(
        [ToolCall("str_replace", {"path": "target.py",
                                  "old_str": "return a - b", "new_str": "return a * b"}, "c0")],
        in_tok=1000, out_tok=400,
    )])
    # rewrite-style correction: whole-file overwrite via write_file.
    fix = StubClient("claude-opus-4-8", [_msg(
        [ToolCall("write_file", {"path": "target.py",
                                 "content": "def add(a, b):\n    return a + b\n"}, "c1")],
        in_tok=1200, out_tok=300,
    )])
    with tempfile.TemporaryDirectory() as tmp:
        rec = run_cascade(buggy_task, [draft, fix], fmt, Path(tmp),
                          correction_style="rewrite", condition_name="cascade-rewrite-2")
    assert rec.passed is True
    assert rec.extra["first_passing_tier"] == 1
    # rewrite emits more output than a diff would (300 vs 80) — the ablation's point.
    assert rec.extra["top_tier_output_tokens"] == 300


def _text_msg(text, in_tok, out_tok) -> AssistantMessage:
    return AssistantMessage(text=text, tool_calls=[],
                            usage=TurnUsage(input_tokens=in_tok, output_tokens=out_tok))


def test_gate_stops_early_when_confident(buggy_task):
    """Draft already correct -> a confident gate halts the ladder at tier 0,
    the expensive tiers never run, and the gate's cost is counted."""
    fmt = FORMAT_REGISTRY["search_replace"]()
    draft = StubClient("claude-haiku-4-5", [_msg(
        [ToolCall("str_replace", {"path": "target.py",
                                  "old_str": "return a - b", "new_str": "return a + b"}, "c0")],
        in_tok=1000, out_tok=400,
    )])
    # This opus tier must NOT run if the gate stops early — give it a response
    # that would FAIL so the test proves it was skipped.
    opus = StubClient("claude-opus-4-8", [_msg(
        [ToolCall("str_replace", {"path": "target.py",
                                  "old_str": "return a + b", "new_str": "return a - b"}, "x")],
        in_tok=9999, out_tok=9999,
    )])
    gate = StubClient("claude-haiku-4-5", [_text_msg("CONFIDENT — add returns a+b.", 1100, 12)])

    with tempfile.TemporaryDirectory() as tmp:
        rec = run_cascade(buggy_task, [draft, opus], fmt, Path(tmp),
                          correction_style="diff", gate_client=gate)

    assert rec.passed is True
    assert rec.extra["stopped_early_at_tier"] == 0
    assert rec.extra["tiers_run"] == 1            # opus tier skipped
    # gate was correct: it said CONFIDENT and the draft did pass.
    assert rec.extra["gate_decisions"] == [{"tier": 0, "confident": True, "correct": True}]
    # cost = haiku draft (0.003) + haiku gate (1100*1 + 12*5 = 1160 / 1e6)
    assert rec.cost_usd == pytest.approx(0.003 + 0.00116, rel=1e-6)


def test_gate_escalates_when_not_confident(buggy_task):
    """Draft wrong -> gate says NOT_CONFIDENT -> opus tier runs and fixes it."""
    fmt = FORMAT_REGISTRY["search_replace"]()
    draft = StubClient("claude-haiku-4-5", [_msg(
        [ToolCall("str_replace", {"path": "target.py",
                                  "old_str": "return a - b", "new_str": "return a * b"}, "c0")],
        in_tok=1000, out_tok=400,
    )])
    opus = StubClient("claude-opus-4-8", [_msg(
        [ToolCall("str_replace", {"path": "target.py",
                                  "old_str": "return a * b", "new_str": "return a + b"}, "c1")],
        in_tok=1200, out_tok=80,
    )])
    gate = StubClient("claude-haiku-4-5", [_text_msg("NOT_CONFIDENT — multiplies.", 1100, 12)])

    with tempfile.TemporaryDirectory() as tmp:
        rec = run_cascade(buggy_task, [draft, opus], fmt, Path(tmp),
                          correction_style="diff", gate_client=gate)

    assert rec.passed is True
    assert rec.extra["stopped_early_at_tier"] is None
    assert rec.extra["tiers_run"] == 2
    # gate correct: NOT_CONFIDENT while the draft genuinely failed.
    assert rec.extra["gate_decisions"] == [{"tier": 0, "confident": False, "correct": True}]


def test_cascade_draft_already_correct_no_op_correction(buggy_task):
    fmt = FORMAT_REGISTRY["search_replace"]()
    # Draft fixes it immediately.
    draft = StubClient("claude-haiku-4-5", [_msg(
        [ToolCall("str_replace", {"path": "target.py",
                                  "old_str": "return a - b", "new_str": "return a + b"}, "c0")],
        in_tok=1000, out_tok=400,
    )])
    # Correction tier correctly emits ZERO edits.
    noop = StubClient("claude-opus-4-8", [_msg([], in_tok=1200, out_tok=10)])
    with tempfile.TemporaryDirectory() as tmp:
        rec = run_cascade(buggy_task, [draft, noop], fmt, Path(tmp),
                          correction_style="diff")
    assert rec.passed is True
    assert rec.extra["draft_passed"] is True
    assert rec.extra["first_passing_tier"] == 0  # passed at the draft
    assert rec.extra["per_tier"][1]["n_edits"] == 0
