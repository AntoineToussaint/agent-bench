"""Offline tests for the common scaffold-value execution contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_eval import SessionTrace
from agent_eval.protocols import NativeToolUseBackend
from agent_eval.types import (
    AssistantMessage,
    ModelClient,
    ModelHandle,
    RunRecord,
    ToolCall,
    ToolResult,
    TurnUsage,
)

from code_editing.contract import EditTask
from code_editing.scaffold_gate import analyze_scaffold_gate, render_scaffold_gate
from code_editing.scaffolds import choose_scaffold, run_scaffold_trial


@dataclass
class ScriptedClient(ModelClient):
    name: str
    script: list[AssistantMessage]
    index: int = 0

    def reset(self, system: str) -> None: ...

    def add_user_text(self, text: str) -> None: ...

    def add_tool_results(self, results: list[ToolResult]) -> None: ...

    def step(
        self,
        tools: list[dict],
        tool_choice: dict | None = None,
    ) -> AssistantMessage:
        message = self.script[self.index]
        self.index += 1
        return message


def _message(name: str, arguments: dict, call_id: str) -> AssistantMessage:
    return AssistantMessage(
        text="",
        tool_calls=[ToolCall(name=name, arguments=arguments, call_id=call_id)],
        usage=TurnUsage(input_tokens=10, output_tokens=3),
    )


def _task(tmp_path: Path, *, category: str = "localized_bug") -> EditTask:
    task_dir = tmp_path / "task"
    fixture = task_dir / "fixture"
    oracle = task_dir / "oracle" / "_overlay" / "tests"
    (fixture / "tests").mkdir(parents=True)
    oracle.mkdir(parents=True)
    (fixture / "calc.py").write_text(
        "def qualifies(value):\n    return value > 10\n", encoding="utf-8"
    )
    # Public test does not cover the boundary; hidden test does.
    (fixture / "tests" / "test_public.py").write_text(
        "from calc import qualifies\n\n"
        "def test_above_boundary():\n    assert qualifies(11)\n",
        encoding="utf-8",
    )
    (oracle / "test_hidden.py").write_text(
        "from calc import qualifies\n\n"
        "def test_inclusive_boundary():\n    assert qualifies(10)\n",
        encoding="utf-8",
    )
    return EditTask(
        task_id="inclusive-boundary",
        language="python",
        category=category,
        fixture_dir=fixture,
        instructions="Make the threshold inclusive in calc.py without changing other behavior.",
        oracle_cmd=[
            "python",
            "-m",
            "pytest",
            "-q",
            "tests/",
            "_overlay/tests/",
        ],
        files_in_context=["calc.py"],
    )


def _handle(script: list[AssistantMessage]) -> ModelHandle:
    return ModelHandle(
        client=ScriptedClient(name="test-model", script=script),
        backend=NativeToolUseBackend(),
    )


def test_minimal_free_loop_can_edit_test_and_finish(tmp_path: Path) -> None:
    task = _task(tmp_path)
    handle = _handle(
        [
            _message("view_file", {"path": "calc.py"}, "v1"),
            _message(
                "str_replace",
                {
                    "path": "calc.py",
                    "old_str": "return value > 10",
                    "new_str": "return value >= 10",
                },
                "e1",
            ),
            _message("run_tests", {}, "t1"),
            _message("done", {"summary": "inclusive threshold"}, "d1"),
        ]
    )
    record = run_scaffold_trial(
        task,
        handle,
        "minimal_free_loop_v1",
        tmp_path / "work-minimal",
        max_turns=6,
        sessions_dir=tmp_path / "sessions",
    )

    assert record.passed
    assert record.turns == 4
    assert record.extra["selected_scaffold"] == "minimal_free_loop_v1"
    trace = SessionTrace.from_jsonl(record.extra["session_path"])
    solve = trace.phase_nodes("solve")
    assert len(solve) == 1
    assert solve[0].reward is not None and solve[0].reward.value == 1.0
    public_runs = solve[0].metadata["public_test_runs"]
    assert public_runs[0]["passed"] is True
    assert "_overlay" not in public_runs[0]["stdout_tail"]


def test_fixed_phases_emit_localize_repair_test_verify_trace(tmp_path: Path) -> None:
    task = _task(tmp_path)
    handle = _handle(
        [
            _message(
                "submit_localization",
                {"files": ["calc.py"], "rationale": "threshold function"},
                "l1",
            ),
            _message(
                "str_replace",
                {
                    "path": "calc.py",
                    "old_str": "return value > 10",
                    "new_str": "return value >= 10",
                },
                "e1",
            ),
            _message("done", {"summary": "fixed"}, "d1"),
            _message("done", {"summary": "verified"}, "d2"),
        ]
    )
    record = run_scaffold_trial(
        task,
        handle,
        "fixed_phases_v1",
        tmp_path / "work-fixed",
        max_turns=8,
        sessions_dir=tmp_path / "sessions",
    )

    assert record.passed
    assert record.extra["localized_files"] == ["calc.py"]
    assert record.extra["public_tests"]["passed"] is True
    trace = SessionTrace.from_jsonl(record.extra["session_path"])
    assert [node.phase for node in trace][1:] == [
        "localize",
        "repair",
        "test",
        "verify",
    ]
    test_node = trace.phase_nodes("test")[0]
    assert test_node.reward is not None
    assert test_node.reward.kind == "prod"
    assert test_node.reward.value == 1.0


def test_adaptive_router_uses_only_deploy_time_task_features(tmp_path: Path) -> None:
    simple = _task(tmp_path / "simple")
    complex_task = _task(tmp_path / "complex", category="multi_site")
    assert choose_scaffold(simple).selected == "minimal_free_loop_v1"
    decision = choose_scaffold(complex_task)
    assert decision.selected == "fixed_phases_v1"
    assert decision.features["category"] == "multi_site"


def test_adaptive_arm_runs_selected_scaffold_but_keeps_arm_identity(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path, category="multi_site")
    handle = _handle(
        [
            _message(
                "submit_localization",
                {"files": ["calc.py"], "rationale": "threshold function"},
                "l1",
            ),
            _message(
                "str_replace",
                {
                    "path": "calc.py",
                    "old_str": "return value > 10",
                    "new_str": "return value >= 10",
                },
                "e1",
            ),
            _message("done", {"summary": "fixed"}, "d1"),
            _message("done", {"summary": "verified"}, "d2"),
        ]
    )
    record = run_scaffold_trial(
        task,
        handle,
        "heuristic_adaptive_v1",
        tmp_path / "work-adaptive",
        max_turns=8,
        sessions_dir=tmp_path / "sessions",
    )

    assert record.passed
    assert record.condition == "heuristic_adaptive_v1"
    assert record.extra["adaptive_selected"] == "fixed_phases_v1"
    assert record.extra["selected_scaffold"] == "fixed_phases_v1"
    assert record.extra["adaptive_policy_version"] == "issue-router-v1"


def _record(task: str, arm: str, passed: bool, cost: float) -> RunRecord:
    return RunRecord(
        task_id=task,
        model="test-model",
        condition=arm,
        passed=passed,
        turns=1,
        tool_calls=1,
        invalid_tool_calls=0,
        usage=TurnUsage(),
        latency_seconds=0.0,
        cost_usd=cost,
    )


def test_gate_analysis_is_paired_on_shared_tasks() -> None:
    records = [
        _record("t1", "minimal_free_loop_v1", False, 0.10),
        _record("t2", "minimal_free_loop_v1", True, 0.10),
        _record("t1", "fixed_phases_v1", True, 0.14),
        _record("t2", "fixed_phases_v1", True, 0.12),
        _record("t1", "heuristic_adaptive_v1", True, 0.11),
        _record("t2", "heuristic_adaptive_v1", True, 0.10),
    ]
    analysis = analyze_scaffold_gate(records, bootstrap_samples=500, seed=3)
    assert analysis is not None
    assert analysis.completed_tasks == ("t1", "t2")
    fixed = analysis.effects["fixed_phases_v1"]
    assert fixed.pass_rate_delta == 0.5
    assert fixed.wins == 1 and fixed.ties == 1 and fixed.losses == 0
    assert analysis.arm_cost_per_resolved_usd["fixed_phases_v1"] == 0.13
    assert analysis.arm_mean_turns["fixed_phases_v1"] == 1
    report = render_scaffold_gate(analysis)
    assert "paired bootstrap 95% interval" in report
    assert "cost/resolved" in report
    assert "Failed-trial modes" in report
    assert "not a leaderboard result" in report
