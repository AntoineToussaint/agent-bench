"""Comparable end-to-end scaffold arms for the scaffold-value gate.

This is intentionally a *shared execution contract*: every arm receives the
same task, model/backend, edit operations, public-test operation, turn cap, and
final hidden oracle. The only intervention is control flow.

The minimal arm is a versioned linear free loop over structured workspace
tools. It is the correct in-repo scaffold control, but it is not presented as
an official mini-SWE-agent reproduction (which uses a sandboxed bash tool).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from agent_eval import (
    PhaseConfig,
    PhaseReward,
    RunRecord,
    SessionTrace,
    Snapshot,
    Transcript,
)
from agent_eval.failure_modes import classify_code_editing
from agent_eval.pricing import cost_usd
from agent_eval.protocols import ToolSpec
from agent_eval.types import (
    AssistantMessage,
    ModelHandle,
    ToolCall,
    ToolResult,
    TurnUsage,
)

from code_editing.bench.oracle import OracleResult, run_oracle
from code_editing.bench.task import materialize
from code_editing.formats.base import LIST_FILES_TOOL, VIEW_FILE_TOOL, apply_common
from code_editing.formats.search_replace import SearchReplaceFormat
from code_editing.types import TaskSpec


ScaffoldName = Literal[
    "minimal_free_loop_v1",
    "fixed_phases_v1",
    "heuristic_adaptive_v1",
]

SCAFFOLDS: tuple[ScaffoldName, ...] = (
    "minimal_free_loop_v1",
    "fixed_phases_v1",
    "heuristic_adaptive_v1",
)

MINIMAL_PROMPT_VERSION = "minimal-linear-v1"
FIXED_PROMPT_VERSION = "fixed-phases-v1"
ADAPTIVE_POLICY_VERSION = "issue-router-v1"

_EDIT_TOOL_NAMES = {"str_replace", "create_file", "delete_file"}

RUN_TESTS_TOOL: dict[str, Any] = {
    "name": "run_tests",
    "description": (
        "Run the task's public test suite in the current workspace. Hidden "
        "benchmark tests are excluded. Use the failure output to improve the patch."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

SUBMIT_LOCALIZATION_TOOL: dict[str, Any] = {
    "name": "submit_localization",
    "description": "Finish localization with the smallest set of files likely to need edits.",
    "input_schema": {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Workspace-relative file paths to hand to repair.",
            },
            "rationale": {"type": "string"},
        },
        "required": ["files"],
    },
}


MINIMAL_SYSTEM = """You are a code-editing agent in a linear free loop.

Solve the task using the available workspace tools. You control the workflow:
inspect files, edit, run public tests when useful, and call `done` only when the
patch is ready. Make the minimum correct change. Never inspect `_overlay`; it is
reserved for the hidden final benchmark oracle. You have a hard turn budget."""

LOCALIZE_SYSTEM = """You are the localization phase of a code-editing agent.

Inspect the workspace without editing it. Identify the smallest set of files
that the repair phase should receive. End by calling `submit_localization`.
Do not include hidden `_overlay` paths."""

REPAIR_SYSTEM = """You are the repair phase of a code-editing agent.

Implement the task using the localized handoff and workspace tools. Do not run
tests in this phase; a separate test phase follows. Make the minimum complete
change, then call `done`."""

VERIFY_SYSTEM = """You are the verification/correction phase of a code-editing agent.

Review the task, current files, localization handoff, and public-test result.
Correct any remaining defect, rerun public tests when useful, and call `done`
when the patch is ready for the hidden final oracle."""


@dataclass
class PhaseRun:
    name: str
    transcript: Transcript
    usage: TurnUsage = field(default_factory=TurnUsage)
    turns: int = 0
    tool_calls: int = 0
    invalid_tool_calls: int = 0
    write_attempts: int = 0
    latency_seconds: float = 0.0
    terminal_called: bool = False
    error: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdaptiveDecision:
    selected: Literal["minimal_free_loop_v1", "fixed_phases_v1"]
    policy_version: str
    reason: str
    features: dict[str, int | str]


def choose_scaffold(task: TaskSpec) -> AdaptiveDecision:
    """Deploy-time-only heuristic router used as the first adaptive baseline.

    It deliberately uses no benchmark outcome, gold patch, or hidden tests.
    This is a frozen baseline to beat with a learned held-out router later.
    """
    words = len(task.instructions.split())
    n_seed_files = len(task.files_in_context)
    complex_categories = {
        "api_migration",
        "config_code",
        "cross_file_rename",
        "extract_function",
        "multi_site",
        "test_work",
        "type_changes",
    }
    use_fixed = (
        n_seed_files > 1
        or words >= 90
        or task.category in complex_categories
    )
    selected: Literal["minimal_free_loop_v1", "fixed_phases_v1"] = (
        "fixed_phases_v1" if use_fixed else "minimal_free_loop_v1"
    )
    reason = (
        "multi-file/long/structurally-complex issue"
        if use_fixed
        else "short single-file issue"
    )
    return AdaptiveDecision(
        selected=selected,
        policy_version=ADAPTIVE_POLICY_VERSION,
        reason=reason,
        features={
            "instruction_words": words,
            "seed_files": n_seed_files,
            "category": task.category,
        },
    )


def run_scaffold_trial(
    task: TaskSpec,
    handle: ModelHandle,
    scaffold: ScaffoldName,
    workdir: Path,
    *,
    max_turns: int = 12,
    transcripts_dir: Path | None = None,
    sessions_dir: Path | None = None,
) -> RunRecord:
    """Run one scaffold arm under the common comparison contract."""
    if max_turns < 6:
        raise ValueError("scaffold comparison needs max_turns >= 6")
    started = time.monotonic()
    if scaffold == "heuristic_adaptive_v1":
        decision = choose_scaffold(task)
        record = _run_selected(
            task,
            handle,
            decision.selected,
            workdir,
            max_turns=max_turns,
            transcripts_dir=transcripts_dir,
            sessions_dir=sessions_dir,
            condition=scaffold,
        )
        record.extra.update(
            {
                "adaptive_policy_version": decision.policy_version,
                "adaptive_selected": decision.selected,
                "adaptive_reason": decision.reason,
                "adaptive_features": decision.features,
            }
        )
        record.latency_seconds = time.monotonic() - started
        return record
    record = _run_selected(
        task,
        handle,
        scaffold,
        workdir,
        max_turns=max_turns,
        transcripts_dir=transcripts_dir,
        sessions_dir=sessions_dir,
        condition=scaffold,
    )
    record.latency_seconds = time.monotonic() - started
    return record


def _run_selected(
    task: TaskSpec,
    handle: ModelHandle,
    selected: Literal["minimal_free_loop_v1", "fixed_phases_v1"],
    workdir: Path,
    *,
    max_turns: int,
    transcripts_dir: Path | None,
    sessions_dir: Path | None,
    condition: ScaffoldName,
) -> RunRecord:
    materialize(task, workdir)
    workdir = workdir.resolve()
    if selected == "minimal_free_loop_v1":
        return _run_minimal(
            task,
            handle,
            workdir,
            max_turns=max_turns,
            transcripts_dir=transcripts_dir,
            sessions_dir=sessions_dir,
            condition=condition,
        )
    return _run_fixed(
        task,
        handle,
        workdir,
        max_turns=max_turns,
        transcripts_dir=transcripts_dir,
        sessions_dir=sessions_dir,
        condition=condition,
    )


def _run_minimal(
    task: TaskSpec,
    handle: ModelHandle,
    workdir: Path,
    *,
    max_turns: int,
    transcripts_dir: Path | None,
    sessions_dir: Path | None,
    condition: ScaffoldName,
) -> RunRecord:
    fmt = SearchReplaceFormat()
    tools = _tools_with_public_tests(fmt)
    public_runs: list[dict[str, Any]] = []

    def apply(call: ToolCall) -> ToolResult:
        if call.name == "run_tests":
            result = _run_public_tests(task, workdir)
            public_runs.append(_oracle_dict(result))
            return _test_tool_result(call, result)
        return fmt.apply(call, workdir)

    phase = _run_tool_phase(
        handle,
        name="solve",
        system=MINIMAL_SYSTEM,
        user=_task_message(task),
        tools=tools,
        apply=apply,
        terminal_tool="done",
        max_turns=max_turns,
    )
    oracle = run_oracle(list(task.oracle_cmd), workdir)

    trace = SessionTrace(task_id=task.task_id)
    root = trace.start()
    trace.add(
        phase="solve",
        config=_phase_config(handle, MINIMAL_PROMPT_VERSION, "linear_full_history"),
        parent=root,
        snapshot=Snapshot.from_transcript(phase.transcript),
        reward=PhaseReward(
            value=float(oracle.passed),
            kind="oracle",
            detail={"passed": oracle.passed, "returncode": oracle.returncode},
        ),
        metadata={
            "workspace_digest": _workspace_digest(workdir),
            "public_test_runs": public_runs,
        },
    )
    return _record(
        task,
        handle,
        condition,
        selected="minimal_free_loop_v1",
        phases=[phase],
        oracle=oracle,
        trace=trace,
        workdir=workdir,
        transcripts_dir=transcripts_dir,
        sessions_dir=sessions_dir,
    )


def _run_fixed(
    task: TaskSpec,
    handle: ModelHandle,
    workdir: Path,
    *,
    max_turns: int,
    transcripts_dir: Path | None,
    sessions_dir: Path | None,
    condition: ScaffoldName,
) -> RunRecord:
    fmt = SearchReplaceFormat()
    localized: list[str] = []

    def apply_localize(call: ToolCall) -> ToolResult:
        common = apply_common(call, workdir)
        if common is not None:
            return common
        if call.name != "submit_localization":
            return ToolResult(call.call_id, "error", f"unknown tool: {call.name}")
        raw_files = call.arguments.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            return ToolResult(call.call_id, "error", "`files` must be a non-empty list")
        seen: set[str] = set()
        for raw in raw_files:
            rel = _workspace_rel_file(workdir, raw)
            if rel is None or rel in seen:
                continue
            localized.append(rel)
            seen.add(rel)
        if not localized:
            return ToolResult(call.call_id, "error", "no submitted workspace files exist")
        return ToolResult(call.call_id, "ok", "localized: " + ", ".join(localized))

    localization = _run_tool_phase(
        handle,
        name="localize",
        system=LOCALIZE_SYSTEM,
        user=_task_message(task),
        tools=[LIST_FILES_TOOL, VIEW_FILE_TOOL, SUBMIT_LOCALIZATION_TOOL],
        apply=apply_localize,
        terminal_tool="submit_localization",
        max_turns=min(3, max_turns),
    )
    used = localization.turns
    if not localized:
        localized = list(
            dict.fromkeys(
                rel
                for raw in task.files_in_context
                if (rel := _workspace_rel_file(workdir, raw)) is not None
            )
        )

    remaining = max(0, max_turns - used)
    reserve_verify = min(3, max(1, remaining // 3)) if remaining else 0
    repair_cap = max(0, remaining - reserve_verify)
    repair = _run_tool_phase(
        handle,
        name="repair",
        system=REPAIR_SYSTEM,
        user=_repair_message(task, workdir, localized),
        tools=fmt.tools(),
        apply=lambda call: fmt.apply(call, workdir),
        terminal_tool="done",
        max_turns=repair_cap,
    )
    repair_digest = _workspace_digest(workdir)
    used += repair.turns

    public_result = _run_public_tests(task, workdir)
    test_transcript = Transcript(system="Deterministic public-test phase")
    test_transcript.add_user_text(_render_test_result(public_result))
    test_phase = PhaseRun(
        name="test",
        transcript=test_transcript,
        artifacts={"public_tests": _oracle_dict(public_result)},
    )

    verify_cap = max(0, max_turns - used)
    verify_public_runs: list[dict[str, Any]] = []

    def apply_verify(call: ToolCall) -> ToolResult:
        if call.name == "run_tests":
            result = _run_public_tests(task, workdir)
            verify_public_runs.append(_oracle_dict(result))
            return _test_tool_result(call, result)
        return fmt.apply(call, workdir)

    verify = _run_tool_phase(
        handle,
        name="verify",
        system=VERIFY_SYSTEM,
        user=_verify_message(task, workdir, localized, public_result),
        tools=_tools_with_public_tests(fmt),
        apply=apply_verify,
        terminal_tool="done",
        max_turns=verify_cap,
    )
    verify.artifacts["public_test_runs"] = verify_public_runs
    oracle = run_oracle(list(task.oracle_cmd), workdir)

    trace = SessionTrace(task_id=task.task_id)
    parent = trace.start()
    localize_node = trace.add(
        phase="localize",
        config=_phase_config(handle, FIXED_PROMPT_VERSION + ":localize", "phase_reset"),
        parent=parent,
        snapshot=Snapshot.from_transcript(localization.transcript),
        metadata={"localized_files": localized},
    )
    repair_node = trace.add(
        phase="repair",
        config=_phase_config(handle, FIXED_PROMPT_VERSION + ":repair", "localized_handoff"),
        parent=localize_node,
        snapshot=Snapshot.from_transcript(repair.transcript),
        metadata={"workspace_digest": repair_digest},
    )
    test_node = trace.add(
        phase="test",
        config=PhaseConfig(model="deterministic-public-tests", prompt_id="public-tests-v1"),
        parent=repair_node,
        snapshot=Snapshot.from_transcript(test_phase.transcript),
        reward=PhaseReward(
            value=float(public_result.passed),
            kind="prod",
            detail=_oracle_dict(public_result),
        ),
    )
    trace.add(
        phase="verify",
        config=_phase_config(handle, FIXED_PROMPT_VERSION + ":verify", "test_handoff"),
        parent=test_node,
        snapshot=Snapshot.from_transcript(verify.transcript),
        reward=PhaseReward(
            value=float(oracle.passed),
            kind="oracle",
            detail={"passed": oracle.passed, "returncode": oracle.returncode},
        ),
        metadata={"workspace_digest": _workspace_digest(workdir)},
    )
    return _record(
        task,
        handle,
        condition,
        selected="fixed_phases_v1",
        phases=[localization, repair, test_phase, verify],
        oracle=oracle,
        trace=trace,
        workdir=workdir,
        transcripts_dir=transcripts_dir,
        sessions_dir=sessions_dir,
        extra={"localized_files": localized, "public_tests": _oracle_dict(public_result)},
    )


def _run_tool_phase(
    handle: ModelHandle,
    *,
    name: str,
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    apply: Callable[[ToolCall], ToolResult],
    terminal_tool: str,
    max_turns: int,
) -> PhaseRun:
    specs = [
        ToolSpec(
            name=tool["name"],
            description=tool.get("description", ""),
            input_schema=tool.get("input_schema", {}),
        )
        for tool in tools
    ]
    addendum = handle.backend.system_prompt_addendum(specs)
    full_system = system + (("\n\n" + addendum) if addendum else "")
    transcript = Transcript(system=full_system)
    phase = PhaseRun(name=name, transcript=transcript)
    if max_turns <= 0:
        phase.error = "turn budget exhausted before phase"
        return phase

    client = handle.client
    client.reset(full_system)
    client.add_user_text(user)
    transcript.add_user_text(user)

    for turn in range(1, max_turns + 1):
        phase.turns = turn
        started = time.monotonic()
        try:
            response = (
                handle.backend.request_terminal(client, specs, terminal_tool)
                if turn == max_turns
                else handle.backend.request(client, specs)
            )
        except Exception as exc:  # noqa: BLE001
            phase.latency_seconds += time.monotonic() - started
            phase.error = f"model_error: {type(exc).__name__}: {exc}"
            break
        phase.latency_seconds += time.monotonic() - started
        _accumulate_usage(phase.usage, response.usage)
        transcript.add_assistant(
            AssistantMessage(
                text=response.raw_text,
                tool_calls=response.actions,
                usage=response.usage,
                raw={"backend": response.backend_name},
            )
        )
        phase.invalid_tool_calls += response.invalid_attempts
        if not response.actions:
            handle.backend.send_hint(
                client,
                f"Call an available tool. Finish this phase with `{terminal_tool}`.",
            )
            transcript.add_user_text("(nudge: no tool actions)")
            continue

        results: list[ToolResult] = []
        for call in response.actions:
            phase.tool_calls += 1
            if call.name in _EDIT_TOOL_NAMES:
                phase.write_attempts += 1
            result = apply(call)
            if result.status == "error":
                phase.invalid_tool_calls += 1
            results.append(result)
            if call.name == terminal_tool and result.status == "ok":
                phase.terminal_called = True
        handle.backend.send_results(client, response.actions, results)
        transcript.add_tool_results(results)
        if phase.terminal_called:
            break
    if not phase.terminal_called and phase.error is None:
        phase.error = f"phase ended without `{terminal_tool}`"
    return phase


def _record(
    task: TaskSpec,
    handle: ModelHandle,
    condition: ScaffoldName,
    *,
    selected: str,
    phases: list[PhaseRun],
    oracle: OracleResult,
    trace: SessionTrace,
    workdir: Path,
    transcripts_dir: Path | None,
    sessions_dir: Path | None,
    extra: dict[str, Any] | None = None,
) -> RunRecord:
    usage = TurnUsage()
    for phase in phases:
        _accumulate_usage(usage, phase.usage)
    error = "; ".join(f"{p.name}: {p.error}" for p in phases if p.error) or None
    tool_calls = sum(p.tool_calls for p in phases)
    invalid = sum(p.invalid_tool_calls for p in phases)
    writes = sum(p.write_attempts for p in phases)

    transcript_path = None
    if transcripts_dir is not None:
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        path = transcripts_dir / f"{task.task_id}__{handle.client.name}__{condition}.json"
        path.write_text(
            json.dumps(
                {
                    "task_id": task.task_id,
                    "model": handle.client.name,
                    "condition": condition,
                    "selected_scaffold": selected,
                    "phases": [
                        {
                            "name": phase.name,
                            "turns": phase.turns,
                            "tool_calls": phase.tool_calls,
                            "invalid_tool_calls": phase.invalid_tool_calls,
                            "error": phase.error,
                            "artifacts": phase.artifacts,
                            "system": phase.transcript.system,
                            "entries": phase.transcript.entries,
                        }
                        for phase in phases
                    ],
                    "oracle": _oracle_dict(oracle),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        transcript_path = str(path)

    session_path = None
    if sessions_dir is not None:
        sessions_dir.mkdir(parents=True, exist_ok=True)
        path = sessions_dir / f"{task.task_id}__{handle.client.name}__{condition}.jsonl"
        trace.to_jsonl(path)
        session_path = str(path)

    failure = classify_code_editing(
        oracle_passed=oracle.passed,
        tool_calls=tool_calls,
        invalid_tool_calls=invalid,
        write_attempts=writes,
        error=error,
    )
    return RunRecord(
        task_id=task.task_id,
        model=handle.client.name,
        condition=condition,
        passed=oracle.passed,
        turns=sum(p.turns for p in phases),
        tool_calls=tool_calls,
        invalid_tool_calls=invalid,
        usage=usage,
        latency_seconds=sum(p.latency_seconds for p in phases),
        cost_usd=cost_usd(handle.client.name, usage),
        stdout=oracle.stdout[-2000:],
        stderr=oracle.stderr[-2000:],
        error=error,
        transcript_path=transcript_path,
        extra={
            "scaffold": condition,
            "selected_scaffold": selected,
            "prompt_versions": {
                "minimal": MINIMAL_PROMPT_VERSION,
                "fixed": FIXED_PROMPT_VERSION,
                "adaptive": ADAPTIVE_POLICY_VERSION,
            },
            "failure_mode": failure,
            "write_attempts": writes,
            "phase_turns": {p.name: p.turns for p in phases},
            "phase_errors": {p.name: p.error for p in phases if p.error},
            "workspace_digest": _workspace_digest(workdir),
            "session_path": session_path,
            **(extra or {}),
        },
    )


def _tools_with_public_tests(fmt: SearchReplaceFormat) -> list[dict[str, Any]]:
    tools = list(fmt.tools())
    done_index = next(
        (index for index, tool in enumerate(tools) if tool["name"] == "done"),
        len(tools),
    )
    tools.insert(done_index, RUN_TESTS_TOOL)
    return tools


def _public_test_command(command: list[str] | tuple[str, ...]) -> list[str]:
    """Remove hidden-overlay operands while preserving the executable/options."""
    return [part for part in command if "_overlay" not in str(part)]


def _run_public_tests(task: TaskSpec, workdir: Path) -> OracleResult:
    command = _public_test_command(task.oracle_cmd)
    if not command:
        return OracleResult(False, -3, "", "no public test command available")
    return run_oracle(command, workdir)


def _test_tool_result(call: ToolCall, result: OracleResult) -> ToolResult:
    return ToolResult(
        call.call_id,
        "ok",
        _render_test_result(result),
    )


def _render_test_result(result: OracleResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    return (
        f"public tests: {status} (returncode={result.returncode})\n"
        f"stdout:\n{result.stdout[-3000:]}\n"
        f"stderr:\n{result.stderr[-3000:]}"
    )


def _oracle_dict(result: OracleResult) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-1000:],
        "stderr_tail": result.stderr[-1000:],
    }


def _task_message(task: TaskSpec) -> str:
    return f"# Task: {task.task_id}\n\n{task.instructions.strip()}"


def _repair_message(task: TaskSpec, workdir: Path, localized: list[str]) -> str:
    parts = [_task_message(task), "", "# Localization handoff"]
    if localized:
        parts.append("Candidate files: " + ", ".join(localized))
        for rel in localized:
            path = workdir / rel
            if path.is_file():
                parts.append(f"\n## `{rel}`\n```\n{path.read_text(errors='replace')}\n```")
    else:
        parts.append("No valid candidate files were submitted; inspect the workspace.")
    return "\n".join(parts)


def _verify_message(
    task: TaskSpec,
    workdir: Path,
    localized: list[str],
    public_result: OracleResult,
) -> str:
    return (
        _repair_message(task, workdir, localized)
        + "\n\n# Public-test handoff\n"
        + _render_test_result(public_result)
    )


def _phase_config(
    handle: ModelHandle, prompt_id: str, context_strategy: str
) -> PhaseConfig:
    return PhaseConfig(
        model=handle.client.name,
        prompt_id=prompt_id,
        context_strategy=context_strategy,
    )


def _workspace_rel_file(workdir: Path, raw: object) -> str | None:
    candidate = Path(str(raw))
    if candidate.is_absolute():
        return None
    root = workdir.resolve()
    resolved = (root / candidate).resolve()
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return None
    if not rel.parts or rel.parts[0] == "_overlay" or not resolved.is_file():
        return None
    return rel.as_posix()


def _workspace_digest(workdir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(workdir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(workdir)
        ignored = {"_overlay", "__pycache__", ".pytest_cache", ".git", "node_modules"}
        if ignored.intersection(rel.parts):
            continue
        digest.update(str(rel).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _accumulate_usage(total: TurnUsage, turn: TurnUsage) -> None:
    total.input_tokens += turn.input_tokens
    total.output_tokens += turn.output_tokens
    total.cache_read_tokens += turn.cache_read_tokens
    total.cache_creation_tokens += turn.cache_creation_tokens
    total.ttft_seconds += turn.ttft_seconds
    total.generate_seconds += turn.generate_seconds


__all__ = [
    "ADAPTIVE_POLICY_VERSION",
    "AdaptiveDecision",
    "FIXED_PROMPT_VERSION",
    "MINIMAL_PROMPT_VERSION",
    "SCAFFOLDS",
    "ScaffoldName",
    "choose_scaffold",
    "run_scaffold_trial",
]
