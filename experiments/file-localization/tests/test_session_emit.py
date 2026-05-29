"""The localization trial emits a SessionTrace (TRACE.md / STRATEGY.md Step 1).

Offline: a scripted stub client drives the loop, so no API is hit. Verifies the
live trial produces a one-phase SessionTrace whose `localize` node carries the
oracle reward (= composite score) and the config bundle — i.e. the unit the
Step-2 contextual bandit will compare. Also exercises the cross-config fork by
running two stubbed "arms" and picking the winner with `best_leaf`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_eval import SessionTrace
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
from file_localization.turn_loop_trial import LocalRepoView, make_turn_loop_trial


def _build_repo(root: Path) -> None:
    (root / "src" / "pricing").mkdir(parents=True)
    (root / "src" / "pricing" / "__init__.py").write_text("")
    (root / "src" / "pricing" / "calc.py").write_text("TAX_RATE = 0.08\n")
    (root / "src" / "pricing" / "other.py").write_text("X = 1\n")
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_calc.py").write_text("def test_smoke(): assert True\n")


def _task() -> LocalizationTask:
    return LocalizationTask(
        instance_id="demo-1",
        issue_text="compute_total is missing tax computation",
        repo="demo/repo",
        base_commit="abc123",
        gold_edit_files=frozenset({"src/pricing/calc.py"}),
        gold_test_files=frozenset({"tests/test_calc.py"}),
    )


@dataclass
class _StubClient(ModelClient):
    name: str
    script: list[AssistantMessage]
    _i: int = 0

    def reset(self, system: str) -> None: ...
    def add_user_text(self, text: str) -> None: ...
    def add_tool_results(self, results: list[ToolResult]) -> None: ...

    def step(self, tools: list[dict], tool_choice: dict | None = None) -> AssistantMessage:
        msg = self.script[self._i]
        self._i += 1
        return msg


def _done(files: list[str]) -> AssistantMessage:
    return AssistantMessage(
        text="",
        tool_calls=[ToolCall(name="done", arguments={"files": files}, call_id="c1")],
        usage=TurnUsage(input_tokens=20, output_tokens=10),
    )


def _handle(client: ModelClient) -> ModelHandle:
    return ModelHandle(client=client, backend=NativeToolUseBackend())


def test_trial_emits_session_trace_with_localize_node(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    task = _task()
    client = _StubClient(name="claude-sonnet-4-6", script=[_done(["src/pricing/calc.py"])])
    trial = make_turn_loop_trial(
        repo_view_for=lambda t: LocalRepoView(tmp_path),
        emit_session_dir=tmp_path / "sessions",
    )
    rec = trial(_handle(client), "turn-loop-tool_use", task)

    assert rec.passed
    spath = rec.extra["session_path"]
    assert spath is not None

    trace = SessionTrace.from_jsonl(spath)
    assert trace.task_id == "demo-1"
    nodes = trace.phase_nodes("localize")
    assert len(nodes) == 1
    node = nodes[0]
    # Reward = composite (continuous), oracle-kind, with the breakdown.
    assert node.reward.kind == "oracle"
    assert node.reward.value == 1.0          # all gold found, no FPs
    assert node.reward.detail["passed"] is True
    assert node.reward.detail["recall"] == 1.0
    # Config bundle = the bandit arm.
    assert node.config.model == "claude-sonnet-4-6"
    assert node.config.as_arm()[0] == "claude-sonnet-4-6"
    # Read-only phase => conversation captured, no env snapshot.
    assert node.snapshot.env_ref is None
    assert node.snapshot.conversation is not None
    # Linked to the OTEL trace id space (may be the all-zero no-op span when
    # tracing isn't set up, but the field exists).
    assert hasattr(node, "span_id")


def test_two_config_arms_fork_and_best_leaf_picks_winner(tmp_path: Path) -> None:
    """Run two configs on the same task, graft them under one SessionTrace,
    and confirm best_leaf selects the higher-composite arm — the Step-2
    bandit comparison, end-to-end through the live trial."""
    _build_repo(tmp_path)
    task = _task()

    # Arm A (haiku): submits the right source file BUT also a spurious one →
    # composite docked by the false-positive penalty.
    rec_a = make_turn_loop_trial(
        repo_view_for=lambda t: LocalRepoView(tmp_path),
        emit_session_dir=tmp_path / "sessions",
    )(
        _handle(_StubClient(name="claude-haiku-4-5",
                            script=[_done(["src/pricing/calc.py", "src/pricing/other.py"])])),
        "arm-a", task,
    )
    # Arm B (sonnet): submits exactly the gold source file → composite 1.0.
    rec_b = make_turn_loop_trial(
        repo_view_for=lambda t: LocalRepoView(tmp_path),
        emit_session_dir=tmp_path / "sessions",
    )(
        _handle(_StubClient(name="claude-sonnet-4-6",
                            script=[_done(["src/pricing/calc.py"])])),
        "arm-b", task,
    )

    ta = SessionTrace.from_jsonl(rec_a.extra["session_path"])
    tb = SessionTrace.from_jsonl(rec_b.extra["session_path"])
    node_a = ta.phase_nodes("localize")[0]
    node_b = tb.phase_nodes("localize")[0]

    # Both pass (recall=1) but A is penalized for the false positive, so B's
    # continuous reward is strictly higher — exactly why the bandit needs the
    # composite, not just `passed`.
    assert node_a.reward.detail["passed"] is True
    assert node_b.reward.detail["passed"] is True
    assert node_b.reward.value > node_a.reward.value

    # Graft both arms as siblings under one session and pick the winner.
    combined = SessionTrace(task_id=task.task_id)
    root = combined.start()
    combined.add(phase="localize", config=node_a.config, parent=root,
                 snapshot=node_a.snapshot, reward=node_a.reward)
    combined.add(phase="localize", config=node_b.config, parent=root,
                 snapshot=node_b.snapshot, reward=node_b.reward)
    best = combined.best_leaf("localize")
    assert best.config.model == "claude-sonnet-4-6"
