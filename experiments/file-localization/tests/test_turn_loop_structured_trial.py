"""Offline tests for the structured-protocol turn-loop trial.

Uses a stub ModelClient that returns canned AssistantMessages whose `text`
contains a fenced ```json``` block. The harness must parse the JSON,
apply each action, and reply with a JSON results block.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_eval.protocols import PromptJSONBackend
from agent_eval.types import (
    AssistantMessage,
    ModelClient,
    ModelHandle,
    ToolResult,
    TurnUsage,
)

from file_localization.contract import LocalizationTask
from file_localization.turn_loop_trial import (
    LocalRepoView,
    _Limits,
    make_structured_turn_loop_trial,
)


def _handle(client: ModelClient) -> ModelHandle:
    """Wrap a stub in a ModelHandle. The structured factory pins its own
    backend, so the handle's backend is only used as a fallback (not here)."""
    return ModelHandle(client=client, backend=PromptJSONBackend())


# ---------- repo fixture ----------


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


def _task(root: Path) -> LocalizationTask:
    return LocalizationTask(
        instance_id="demo-1",
        issue_text="compute_total is missing tax computation",
        repo="demo/repo",
        base_commit="abc123def456",
        gold_edit_files=frozenset({"src/pricing/calc.py"}),
        gold_test_files=frozenset({"tests/test_calc.py"}),
    )


# ---------- stub ModelClient ----------


@dataclass
class _StubClient(ModelClient):
    """A scripted client. Each .step() returns the next AssistantMessage
    from `script`; raises if the script runs out before `done` was emitted.

    Records every user message sent to it (system, user texts, tool
    results) so tests can assert on what the harness fed back.
    """

    name: str
    script: list[AssistantMessage]
    user_messages: list[str] = field(default_factory=list)
    tool_results_in: list[list[ToolResult]] = field(default_factory=list)
    _i: int = 0

    def reset(self, system: str) -> None:
        self.user_messages = []
        self.tool_results_in = []

    def add_user_text(self, text: str) -> None:
        self.user_messages.append(text)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        # Structured protocol never invokes this — tool results come back
        # as JSON in user-text. Record any unexpected calls so tests can
        # catch protocol regressions.
        self.tool_results_in.append(results)

    def step(
        self,
        tools: list[dict],
        tool_choice: dict | None = None,
    ) -> AssistantMessage:
        if self._i >= len(self.script):
            raise RuntimeError("stub script exhausted")
        msg = self.script[self._i]
        self._i += 1
        return msg


def _json_msg(payload: dict, *, in_tokens: int = 20, out_tokens: int = 10) -> AssistantMessage:
    text = "```json\n" + json.dumps(payload) + "\n```"
    return AssistantMessage(
        text=text,
        tool_calls=[],
        usage=TurnUsage(input_tokens=in_tokens, output_tokens=out_tokens),
    )


def _raw_msg(text: str) -> AssistantMessage:
    return AssistantMessage(
        text=text,
        tool_calls=[],
        usage=TurnUsage(input_tokens=20, output_tokens=10),
    )


# ---------- tests ----------


def test_structured_turn_loop_passes_when_done_returns_gold_files(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    task = _task(tmp_path)

    script = [
        _json_msg({"thought": "let me list", "actions": [{"op": "list_files", "args": {}}]}),
        _json_msg(
            {
                "thought": "grep for symbol",
                "actions": [{"op": "grep", "args": {"pattern": "compute_total"}}],
            }
        ),
        _json_msg(
            {
                "thought": "done",
                "done": True,
                "files": ["src/pricing/calc.py", "tests/test_calc.py"],
            }
        ),
    ]
    client = _StubClient(name="claude-sonnet-4-6", script=script)
    trial = make_structured_turn_loop_trial(repo_view_for=lambda t: LocalRepoView(tmp_path))
    rec = trial(_handle(client), "turn-loop-structured", task)

    assert rec.passed
    assert rec.turns == 3
    # 1 list_files + 1 grep + 1 done action = 3 "tool calls" (for parity)
    assert rec.tool_calls == 3
    assert rec.invalid_tool_calls == 0
    assert rec.extra["done_called"] is True
    assert rec.extra["submitted"] == ["src/pricing/calc.py", "tests/test_calc.py"]
    assert rec.extra["recall"] == 1.0
    assert rec.usage.input_tokens > 0
    assert rec.usage.output_tokens > 0

    # Harness must NOT use the tool_use API for result-passing.
    assert client.tool_results_in == []
    # Two results-blocks should have been fed back as user-text (after
    # the first two turns; the third turn is `done` so no results follow).
    results_msgs = [m for m in client.user_messages if '"results"' in m]
    assert len(results_msgs) == 2
    # And the results blocks should be valid JSON we can round-trip.
    for msg in results_msgs:
        body = msg.split("```json", 1)[1].split("```", 1)[0].strip()
        parsed = json.loads(body)
        assert isinstance(parsed["results"], list)
        assert parsed["results"][0]["status"] == "ok"


def test_structured_turn_loop_fails_when_missing_source_file(tmp_path: Path) -> None:
    # Submitting only a test file (no source) must fail — test files
    # are ignored in scoring, so the model effectively submitted nothing.
    _build_repo(tmp_path)
    task = _task(tmp_path)
    script = [
        _json_msg(
            {
                "thought": "done early",
                "done": True,
                "files": ["tests/test_calc.py"],  # missing src/pricing/calc.py
            }
        ),
    ]
    client = _StubClient(name="claude-haiku-4-5", script=script)
    trial = make_structured_turn_loop_trial(repo_view_for=lambda t: LocalRepoView(tmp_path))
    rec = trial(_handle(client), "turn-loop-structured", task)
    assert not rec.passed
    assert rec.extra["recall"] == 0.0
    assert rec.extra["done_called"] is True
    assert rec.extra["submitted"] == ["tests/test_calc.py"]


def test_structured_turn_loop_parse_error_counts_as_invalid(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    task = _task(tmp_path)
    # Turn 1: garbage (no fenced block, not valid JSON).
    # Turn 2: recover and submit done with gold files.
    script = [
        _raw_msg("I'm just going to ramble without any JSON whatsoever."),
        _json_msg(
            {
                "thought": "ok now done",
                "done": True,
                "files": ["src/pricing/calc.py", "tests/test_calc.py"],
            }
        ),
    ]
    client = _StubClient(name="claude-haiku-4-5", script=script)
    trial = make_structured_turn_loop_trial(
        repo_view_for=lambda t: LocalRepoView(tmp_path),
        limits=_Limits(max_consecutive_errors=5, max_no_progress_turns=999),
    )
    rec = trial(_handle(client), "turn-loop-structured", task)

    assert rec.passed
    assert rec.turns == 2
    assert rec.invalid_tool_calls == 1
    # The harness should have surfaced a structured error to the model.
    err_msgs = [m for m in client.user_messages if '"error"' in m]
    assert len(err_msgs) == 1
    body = err_msgs[0].split("```json", 1)[1].split("```", 1)[0].strip()
    parsed = json.loads(body)
    assert "json parse error" in parsed["error"]
    assert parsed["actions_applied"] == []


def test_structured_turn_loop_respects_max_turns(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    task = _task(tmp_path)
    # Endless list_files; never submits `done`.
    script = [
        _json_msg({"thought": "list again", "actions": [{"op": "list_files", "args": {}}]})
        for _ in range(20)
    ]
    client = _StubClient(name="claude-haiku-4-5", script=script)
    trial = make_structured_turn_loop_trial(
        repo_view_for=lambda t: LocalRepoView(tmp_path),
        limits=_Limits(max_turns=5, max_no_progress_turns=999),
    )
    rec = trial(_handle(client), "turn-loop-structured", task)
    assert rec.turns == 5
    assert not rec.extra["done_called"]
    assert not rec.passed


def test_structured_turn_loop_multiple_actions_in_one_turn(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    task = _task(tmp_path)
    # Turn 1: batch three actions. Turn 2: done.
    script = [
        _json_msg(
            {
                "thought": "batch explore",
                "actions": [
                    {"op": "list_files", "args": {}},
                    {"op": "grep", "args": {"pattern": "compute_total", "glob": "*.py"}},
                    {"op": "view_file", "args": {"path": "src/pricing/calc.py"}},
                ],
            }
        ),
        _json_msg(
            {
                "thought": "done",
                "done": True,
                "files": ["src/pricing/calc.py", "tests/test_calc.py"],
            }
        ),
    ]
    client = _StubClient(name="claude-haiku-4-5", script=script)
    trial = make_structured_turn_loop_trial(repo_view_for=lambda t: LocalRepoView(tmp_path))
    rec = trial(_handle(client), "turn-loop-structured", task)

    assert rec.passed
    assert rec.turns == 2
    # 3 actions in turn 1 + 1 "done" in turn 2 = 4.
    assert rec.tool_calls == 4
    assert rec.invalid_tool_calls == 0

    # The single results-block returned to the model must contain all 3
    # results in the order submitted.
    results_msgs = [m for m in client.user_messages if '"results"' in m]
    assert len(results_msgs) == 1
    body = results_msgs[0].split("```json", 1)[1].split("```", 1)[0].strip()
    parsed = json.loads(body)
    assert [r["op"] for r in parsed["results"]] == ["list_files", "grep", "view_file"]
    assert all(r["status"] == "ok" for r in parsed["results"])


def test_structured_turn_loop_aborts_on_consecutive_errors(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    task = _task(tmp_path)
    # Three turns of invalid-op actions. Bad op → _apply returns error.
    script = [
        _json_msg({"thought": "bad", "actions": [{"op": "nonexistent_tool", "args": {}}]}),
        _json_msg({"thought": "bad", "actions": [{"op": "nonexistent_tool", "args": {}}]}),
        _json_msg({"thought": "bad", "actions": [{"op": "nonexistent_tool", "args": {}}]}),
        _json_msg({"thought": "give up", "done": True, "files": []}),
    ]
    client = _StubClient(name="claude-haiku-4-5", script=script)
    trial = make_structured_turn_loop_trial(
        repo_view_for=lambda t: LocalRepoView(tmp_path),
        limits=_Limits(max_consecutive_errors=3),
    )
    rec = trial(_handle(client), "turn-loop-structured", task)
    assert rec.error is not None
    assert "consecutive error" in rec.error
    assert not rec.passed
