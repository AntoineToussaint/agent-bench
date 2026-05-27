"""Offline tests for the turn-loop trial (tool_use protocol).

Uses a stub ModelClient that returns canned AssistantMessages so we never
hit a real API. Verifies: the loop drives tool calls, the RepoView is
queried correctly, the final done() answer is scored, escape valves fire.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_eval.protocols import NativeToolUseBackend
from agent_eval.types import (
    AssistantMessage,
    ModelClient,
    ModelHandle,
    ToolCall,
    ToolResult,
    TurnUsage,
)

from file_localization.contract import LocalizationTask
from file_localization.turn_loop_trial import (
    LocalRepoView,
    _Limits,
    make_turn_loop_trial,
)


def _handle(client: ModelClient) -> ModelHandle:
    """Wrap a stub client in a ModelHandle for the trial signature.

    Tests don't care which backend is on the handle when they construct
    the trial with an explicit factory — the factory closes over its own
    backend. Native is a safe default to attach to the handle.
    """
    return ModelHandle(client=client, backend=NativeToolUseBackend())


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
    """

    name: str
    script: list[AssistantMessage]
    _i: int = 0

    def reset(self, system: str) -> None: pass
    def add_user_text(self, text: str) -> None: pass
    def add_tool_results(self, results: list[ToolResult]) -> None: pass

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


def _txt(s: str) -> AssistantMessage:
    return AssistantMessage(text=s, tool_calls=[], usage=TurnUsage(input_tokens=10, output_tokens=5))


def _call(name: str, **kwargs) -> AssistantMessage:
    return AssistantMessage(
        text="",
        tool_calls=[ToolCall(name=name, arguments=kwargs, call_id=f"c{id(kwargs) & 0xFFFF}")],
        usage=TurnUsage(input_tokens=20, output_tokens=10),
    )


# ---------- tests ----------


def test_repo_view_list_grep_view(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    view = LocalRepoView(tmp_path)
    files = view.list_files()
    assert "src/pricing/calc.py" in files
    assert "tests/test_calc.py" in files

    hits = view.grep("compute_total", glob="*.py")
    paths = {h[0] for h in hits}
    assert "src/pricing/calc.py" in paths
    assert "tests/test_calc.py" in paths

    contents = view.view_file("src/pricing/calc.py")
    assert "def compute_total" in contents

    slice_ = view.view_file("src/pricing/calc.py", line_range=(1, 1))
    assert slice_.strip() == "def compute_total(items):"


def test_turn_loop_passes_when_done_returns_gold_files(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    task = _task(tmp_path)

    # Scripted: list_files, then grep, then done with gold files
    script = [
        _call("list_files"),
        _call("grep", pattern="compute_total"),
        _call(
            "done",
            files=["src/pricing/calc.py", "tests/test_calc.py"],
        ),
    ]
    client = _StubClient(name="claude-sonnet-4-6", script=script)
    trial = make_turn_loop_trial(repo_view_for=lambda t: LocalRepoView(tmp_path))
    rec = trial(_handle(client), "turn-loop-tool_use", task)
    assert rec.passed
    assert rec.turns == 3
    assert rec.tool_calls == 3
    assert rec.invalid_tool_calls == 0
    assert rec.extra["done_called"] is True
    assert rec.extra["submitted"] == ["src/pricing/calc.py", "tests/test_calc.py"]
    assert rec.extra["recall"] == 1.0
    assert rec.usage.input_tokens > 0
    assert rec.usage.output_tokens > 0


def test_turn_loop_fails_when_missing_source_file(tmp_path: Path) -> None:
    # Localization scores source files only. Submitting just the test
    # file (no source) must fail because the source file is the gold.
    _build_repo(tmp_path)
    task = _task(tmp_path)
    script = [
        _call("done", files=["tests/test_calc.py"]),  # missing src/pricing/calc.py
    ]
    client = _StubClient(name="claude-haiku-4-5", script=script)
    trial = make_turn_loop_trial(repo_view_for=lambda t: LocalRepoView(tmp_path))
    rec = trial(_handle(client), "turn-loop-tool_use", task)
    assert not rec.passed
    assert rec.extra["recall"] == 0.0  # zero gold sources found
    assert rec.extra["done_called"] is True


def test_turn_loop_passes_when_only_source_file_submitted(tmp_path: Path) -> None:
    # Inverse: submitting just the source file (no test) must PASS,
    # because test files are ignored in scoring.
    _build_repo(tmp_path)
    task = _task(tmp_path)
    script = [
        _call("done", files=["src/pricing/calc.py"]),  # no test file at all
    ]
    client = _StubClient(name="claude-haiku-4-5", script=script)
    trial = make_turn_loop_trial(repo_view_for=lambda t: LocalRepoView(tmp_path))
    rec = trial(_handle(client), "turn-loop-tool_use", task)
    assert rec.passed
    assert rec.extra["recall"] == 1.0


def test_turn_loop_aborts_on_consecutive_errors(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    task = _task(tmp_path)
    # Three consecutive bad calls (unknown tool name)
    script = [
        _call("nonexistent_tool"),
        _call("nonexistent_tool"),
        _call("nonexistent_tool"),
        _call("done", files=[]),
    ]
    client = _StubClient(name="claude-haiku-4-5", script=script)
    trial = make_turn_loop_trial(
        repo_view_for=lambda t: LocalRepoView(tmp_path),
        limits=_Limits(max_consecutive_errors=3),
    )
    rec = trial(_handle(client), "turn-loop-tool_use", task)
    assert rec.error is not None
    assert "consecutive error" in rec.error
    assert not rec.passed


def test_turn_loop_respects_max_turns(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    task = _task(tmp_path)
    # Endless list_files; never calls done
    script = [_call("list_files") for _ in range(20)]
    client = _StubClient(name="claude-haiku-4-5", script=script)
    trial = make_turn_loop_trial(
        repo_view_for=lambda t: LocalRepoView(tmp_path),
        limits=_Limits(max_turns=5, max_no_progress_turns=999),
    )
    rec = trial(_handle(client), "turn-loop-tool_use", task)
    assert rec.turns == 5
    assert not rec.extra["done_called"]
    assert not rec.passed
