"""Trial runner — one (task, model, format) combination end-to-end."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agent_eval import ModelClient, RunRecord, ToolCall, ToolResult, Transcript, TurnUsage
from agent_eval.failure_modes import classify_code_editing
from agent_eval.pricing import cost_usd
from agent_eval.protocols import ToolSpec
from agent_eval.tracing import (
    record_llm_usage,
    span_llm_request,
    span_tool_call,
    span_turn,
)
from agent_eval.types import ModelHandle

from code_editing.bench.oracle import run_oracle
from code_editing.bench.task import materialize
from code_editing.formats.base import EditFormat
from code_editing.types import TaskSpec


def _tools_to_specs(tool_dicts: list[dict[str, Any]]) -> list[ToolSpec]:
    """Convert an EditFormat's `.tools()` (Anthropic shape) into ToolSpec."""
    return [
        ToolSpec(
            name=t["name"],
            description=t.get("description", ""),
            input_schema=t.get("input_schema", {}),
        )
        for t in tool_dicts
    ]


def _resolve_client_and_backend(
    model: ModelClient,
    handle: ModelHandle | None,
) -> tuple[ModelClient, Any, str]:
    """Pick (client, backend, backend_name) from either a raw client or a handle.

    Backward-compat: when handle is None, returns the raw client with
    backend=None and backend_name="legacy". The runner then takes the
    legacy `model.step(tools)` path.
    """
    if handle is not None:
        return handle.client, handle.backend, handle.backend.name
    return model, None, "legacy"


_READ_ONLY_TOOLS = {"view_file", "list_files", "done"}


SYSTEM_BASE = (
    "You are a code-editing assistant. You will be given a small project and a "
    "task. Make the minimum changes needed to satisfy the task; then call the "
    "`done` tool. Do not run shell commands. Do not modify files outside the "
    "working directory. Always inspect files with `view_file` before editing.\n\n"
    "Budget: you have at most ~10 tool-using turns. Prefer batching independent "
    "edits into one assistant turn rather than issuing them one-per-turn.\n\n"
    "If the tools you've been given are fundamentally insufficient for the "
    "requested edit (e.g. you can only edit named functions but need to change "
    "a module-level statement), STOP after at most two attempts and call `done` "
    "with a summary explaining what you couldn't do. Do not thrash."
)


SYSTEM_BASE_SINGLE_SHOT = (
    "You are a code-editing assistant. You receive a task description and the "
    "FULL CONTENTS of every file in the project. You have ONE response to emit "
    "all edits as tool calls. You will NOT be invoked again — there is no view, "
    "verify, or iterate step. `view_file`, `list_files`, `done` are not "
    "available.\n\n"
    "## Required workflow\n"
    "1. In your text response, write a NUMBERED PLAN of every distinct edit "
    "the task requires. Be thorough — re-read the task description and list "
    "EVERY file that must change and what changes in each.\n"
    "2. Then emit tool calls — one tool call (or more) for each plan item.\n"
    "3. CRITICAL: the number of tool calls you emit must be ≥ the number of "
    "items in your plan. Do not stop after the first call. Multi-file tasks "
    "REQUIRE multi-file tool calls.\n\n"
    "Common mistakes to avoid:\n"
    "  - Planning 2 edits but emitting 1 tool call (the most common failure).\n"
    "  - Forgetting to update imports / callers / tests when you change a "
    "definition.\n"
    "  - Assuming a single big str_replace covers edits across multiple files."
)


def run_trial(
    task: TaskSpec,
    model: ModelClient,
    fmt: EditFormat,
    workdir: Path,
    max_turns: int = 12,
    transcripts_dir: Path | None = None,
    max_consecutive_errors: int = 3,
    max_no_progress_turns: int = 3,
    handle: ModelHandle | None = None,
) -> RunRecord:
    """Run one (task, model, format) agent trial.

    `handle`, when supplied, drives the model calls through its bundled
    `ToolBackend` (so the choice of tool-use protocol — native / schema /
    prompt-JSON — is configurable) and lets OTEL spans nest under the
    sweep's trial span. When None, the legacy `model.step()` path is
    used — preserves direct CLI / notebook usage.
    """
    materialize(task, workdir)
    # Canonicalize once so symlink-bearing roots (e.g. macOS /var -> /private/var)
    # don't trip path comparisons inside the formats.
    workdir = workdir.resolve()

    client, backend, backend_name = _resolve_client_and_backend(model, handle)

    system = SYSTEM_BASE + "\n\n" + fmt.system_prompt()
    # Backend may want to slot a tool description into the prompt
    # (PromptJSON does; Native/Schema return "").
    tool_dicts = fmt.tools()
    tool_specs = _tools_to_specs(tool_dicts) if backend is not None else []
    if backend is not None:
        addendum = backend.system_prompt_addendum(tool_specs)
        if addendum:
            system = system + "\n\n" + addendum
    client.reset(system)
    transcript = Transcript(system=system)

    # Initial user message: instructions + (optional) starter file contents
    user_text = _initial_user_message(task, workdir)
    client.add_user_text(user_text)
    transcript.add_user_text(user_text)

    total_usage = TurnUsage()
    turns = 0
    tool_calls = 0
    invalid_tool_calls = 0
    write_attempts = 0  # subset of tool_calls that targeted file mutation
    consecutive_error_turns = 0
    no_progress_turns = 0
    last_workdir_state: tuple[tuple[str, int, float], ...] | None = None
    # Step-level metrics: aggregated at trial end. See DIMENSIONS.md.
    # `wasted_turns` here = turns that attempted writes but didn't change
    # the workdir (model re-edited the same lines, or every call errored).
    wasted_turns = 0
    actions_per_active_turn: list[int] = []  # for batch_efficiency
    # Context-engineering observation: input_tokens per turn. See HARNESS.md.
    input_tokens_per_turn: list[int] = []
    done = False
    error: str | None = None

    t0 = time.monotonic()
    while turns < max_turns and not done:
        turns += 1
        with span_turn(turn_idx=turns, backend=backend_name) as turn_sp:
            try:
                with span_llm_request(model=client.name, backend=backend_name) as llm_sp:
                    if backend is not None:
                        resp = backend.request(client, tool_specs)
                        msg_text = resp.raw_text
                        msg_calls = resp.actions
                        msg_usage = resp.usage
                    else:
                        msg = model.step(tool_dicts)
                        msg_text = msg.text
                        msg_calls = msg.tool_calls
                        msg_usage = msg.usage
                    record_llm_usage(
                        llm_sp,
                        input_tokens=msg_usage.input_tokens,
                        output_tokens=msg_usage.output_tokens,
                        cache_read_tokens=msg_usage.cache_read_tokens,
                        cache_creation_tokens=msg_usage.cache_creation_tokens,
                    )
            except Exception as e:  # noqa: BLE001
                error = f"model_error: {type(e).__name__}: {e}"
                turn_sp.set_attribute("agent_eval.turn.error", error)
                break

            # Build a synthetic AssistantMessage for the transcript so the
            # serialization format stays stable across backend / legacy paths.
            from agent_eval.types import AssistantMessage as _AM

            transcript.add_assistant(
                _AM(text=msg_text, tool_calls=msg_calls, usage=msg_usage, raw={"backend": backend_name})
            )
            total_usage.input_tokens += msg_usage.input_tokens
            total_usage.output_tokens += msg_usage.output_tokens
            total_usage.cache_read_tokens += msg_usage.cache_read_tokens
            total_usage.cache_creation_tokens += msg_usage.cache_creation_tokens
            input_tokens_per_turn.append(msg_usage.input_tokens)
            turn_sp.set_attribute("agent_eval.turn.n_actions", len(msg_calls))
            turn_sp.set_attribute(
                "agent_eval.turn.tool_names",
                json.dumps([a.name for a in msg_calls]),
            )

            if not msg_calls:
                # Nudge once if model went silent.
                client.add_user_text(
                    "You did not call any tools. Use the available tools to make edits, "
                    "or call `done` if you are finished."
                )
                transcript.add_user_text("(nudge: no tool calls)")
                turn_sp.set_attribute("agent_eval.turn.outcome", "no_actions")
                continue

            results: list[ToolResult] = []
            turn_had_only_errors = True
            turn_had_write_attempt = False
            for call in msg_calls:
                tool_calls += 1
                if call.name not in _READ_ONLY_TOOLS:
                    turn_had_write_attempt = True
                    write_attempts += 1
                with span_tool_call(call.name, call.arguments) as call_sp:
                    res = fmt.apply(call, workdir)
                    call_sp.set_attribute("agent_eval.tool.status", res.status)
                    call_sp.set_attribute("agent_eval.tool.result_chars", len(res.content or ""))
                if res.status == "error":
                    invalid_tool_calls += 1
                else:
                    turn_had_only_errors = False
                results.append(res)
                if call.name == "done":
                    done = True
            client.add_tool_results(results)
            transcript.add_tool_results(results)
            turn_sp.set_attribute(
                "agent_eval.turn.outcome",
                "done" if done else ("dispatched" if not turn_had_only_errors else "all_errors"),
            )
            # Step-level: batch efficiency counts non-`done` actions per
            # active turn (turns that dispatched anything).
            non_done = sum(1 for c in msg_calls if c.name != "done")
            if non_done > 0:
                actions_per_active_turn.append(non_done)

        # --- escape valves to prevent runaway loops ---
        # (a) consecutive turns where every tool call errored
        if turn_had_only_errors:
            consecutive_error_turns += 1
        else:
            consecutive_error_turns = 0
        if consecutive_error_turns >= max_consecutive_errors:
            error = (
                f"aborted: {consecutive_error_turns} consecutive turns where every tool "
                f"call returned an error. The format probably can't perform the requested "
                f"edit, or the model is thrashing."
            )
            break

        # (b) workdir unchanged across N consecutive WRITE-attempting turns
        # (view-only turns are legitimate context gathering; don't count them).
        state = _snapshot(workdir)
        if turn_had_write_attempt and state == last_workdir_state:
            no_progress_turns += 1
            wasted_turns += 1
        elif turn_had_write_attempt:
            no_progress_turns = 0
        last_workdir_state = state
        if no_progress_turns >= max_no_progress_turns:
            error = (
                f"aborted: {no_progress_turns} consecutive write-attempt turns with no "
                f"change to the working directory."
            )
            break

    latency = time.monotonic() - t0

    oracle = run_oracle(task.oracle_cmd, workdir)

    transcript_path = None
    if transcripts_dir:
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        tp = transcripts_dir / f"{task.task_id}__{client.name}__{fmt.name}.json"
        tp.write_text(
            json.dumps(
                {
                    "task_id": task.task_id,
                    "model": client.name,
                    "format": fmt.name,
                    "system": transcript.system,
                    "entries": transcript.entries,
                    "oracle": {
                        "passed": oracle.passed,
                        "returncode": oracle.returncode,
                        "stdout": oracle.stdout[-4000:],
                        "stderr": oracle.stderr[-4000:],
                    },
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        transcript_path = str(tp)

    failure_mode = classify_code_editing(
        oracle_passed=bool(oracle.passed),
        tool_calls=tool_calls,
        invalid_tool_calls=invalid_tool_calls,
        write_attempts=write_attempts,
        error=error,
    )

    return RunRecord(
        task_id=task.task_id,
        model=client.name,
        condition=fmt.name,
        passed=oracle.passed,
        turns=turns,
        tool_calls=tool_calls,
        invalid_tool_calls=invalid_tool_calls,
        usage=total_usage,
        latency_seconds=latency,
        cost_usd=cost_usd(client.name, total_usage),
        stdout=oracle.stdout[-2000:],
        stderr=oracle.stderr[-2000:],
        error=error,
        transcript_path=transcript_path,
        extra={
            "failure_mode": failure_mode,
            "write_attempts": write_attempts,
            # Step-level metrics (see DIMENSIONS.md). For code-editing:
            # `wasted_turn_fraction` = turns where the model wrote but
            # the workdir didn't actually change (re-edited the same
            # lines / every call errored).
            "wasted_turn_fraction": (
                wasted_turns / turns if turns > 0 else 0.0
            ),
            "batch_efficiency": (
                sum(actions_per_active_turn) / len(actions_per_active_turn)
                if actions_per_active_turn else 0.0
            ),
            "active_turns": len(actions_per_active_turn),
            # Context-engineering observation (see HARNESS.md). With
            # our keep-everything policy these grow monotonically.
            "peak_input_tokens": (
                max(input_tokens_per_turn) if input_tokens_per_turn else 0
            ),
            "input_tokens_at_done": (
                input_tokens_per_turn[-1] if input_tokens_per_turn else 0
            ),
            "context_growth_per_turn": (
                (input_tokens_per_turn[-1] - input_tokens_per_turn[0])
                / max(1, len(input_tokens_per_turn) - 1)
                if len(input_tokens_per_turn) >= 2 else 0.0
            ),
        },
    )


SYSTEM_BASE_STRUCTURED = (
    "You are a code-editing assistant. You receive a task description and the "
    "FULL CONTENTS of every file in the project. Your job is to output a single "
    "JSON object describing ALL the edits to make. NO tools, NO multiple turns.\n\n"
    "## Output format\n"
    "Respond with ONE fenced JSON block (and nothing else outside it):\n\n"
    "```json\n"
    "{\n"
    "  \"plan\": \"<brief sentence per planned edit>\",\n"
    "  \"changes\": [\n"
    "    {\"op\": \"<operation_name>\", \"args\": {...}},\n"
    "    {\"op\": \"<operation_name>\", \"args\": {...}}\n"
    "  ]\n"
    "}\n"
    "```\n\n"
    "`changes` must contain EVERY edit needed. Multi-file tasks need multiple "
    "entries — one entry per edit. The available operations and their `args` "
    "schemas are listed below. Each entry is applied in order by deterministic "
    "code; you are NOT calling tools, you are emitting a change-set.\n\n"
    "Common mistakes:\n"
    "  - Listing edits in the `plan` text but not in `changes`. Every plan item "
    "must have a corresponding `changes` entry.\n"
    "  - Wrapping the JSON in extra prose. Output the fenced block, period."
)


def run_structured(
    task: TaskSpec,
    model: ModelClient,
    fmt: EditFormat,
    workdir: Path,
    transcripts_dir: Path | None = None,
    handle: ModelHandle | None = None,
) -> RunRecord:
    """One LLM call. Model outputs JSON change-set as text. No tool_use API."""

    import json as _json
    import re as _re

    materialize(task, workdir)
    workdir = workdir.resolve()

    client, _backend, backend_name = _resolve_client_and_backend(model, handle)

    # Serialize the format's tool schemas into the system prompt so the model
    # knows what ops are available.
    edit_tools = [t for t in fmt.tools() if t["name"] not in _READ_ONLY_TOOLS]
    ops_doc = _ops_documentation(edit_tools)

    system = "\n\n".join([
        SYSTEM_BASE_STRUCTURED,
        _language_guidance(task.language),
        "## Available operations\n" + ops_doc,
    ])
    user_text = _full_context_message(task, workdir)

    client.reset(system)
    client.add_user_text(user_text)
    transcript = Transcript(system=system)
    transcript.add_user_text(user_text)

    t0 = time.monotonic()
    try:
        with span_llm_request(model=client.name, backend=backend_name) as llm_sp:
            msg = client.step([])  # empty tools list — model must output text
            record_llm_usage(
                llm_sp,
                input_tokens=msg.usage.input_tokens,
                output_tokens=msg.usage.output_tokens,
                cache_read_tokens=msg.usage.cache_read_tokens,
                cache_creation_tokens=msg.usage.cache_creation_tokens,
            )
    except Exception as e:  # noqa: BLE001
        latency = time.monotonic() - t0
        return RunRecord(
            task_id=task.task_id, model=client.name, condition=fmt.name,
            passed=False, turns=1, tool_calls=0, invalid_tool_calls=0,
            usage=TurnUsage(), latency_seconds=latency,
            error=f"model_error: {type(e).__name__}: {e}",
        )
    transcript.add_assistant(msg)

    # Parse the JSON block from the model's text
    text = msg.text or ""
    parsed = _extract_json_changeset(text)
    error: str | None = None
    tool_calls = 0
    invalid = 0
    results: list[ToolResult] = []

    if isinstance(parsed, str):
        error = f"json parse error: {parsed}"
    else:
        for i, change in enumerate(parsed.get("changes") or []):
            op = change.get("op") or change.get("tool") or change.get("name")
            if not op:
                invalid += 1
                tool_calls += 1
                results.append(ToolResult(f"c{i}", "error", "missing `op`"))
                continue
            # Accept both shapes: nested {op, args:{...}} OR flat {op, path, ...}
            args = change.get("args")
            if not isinstance(args, dict):
                args = {k: v for k, v in change.items() if k not in {"op", "tool", "name"}}
            tool_calls += 1
            tc = ToolCall(name=op, arguments=args, call_id=f"c{i}")
            res = fmt.apply(tc, workdir)
            if res.status == "error":
                invalid += 1
            results.append(res)
        if tool_calls == 0:
            error = "model emitted JSON with empty `changes` list"
    transcript.add_tool_results(results)
    latency = time.monotonic() - t0

    oracle = run_oracle(task.oracle_cmd, workdir)

    transcript_path = None
    if transcripts_dir:
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        tp = transcripts_dir / f"{task.task_id}__{client.name}__{fmt.name}.json"
        tp.write_text(
            _json.dumps(
                {
                    "task_id": task.task_id, "model": client.name, "format": fmt.name,
                    "mode": "structured",
                    "system": transcript.system, "entries": transcript.entries,
                    "oracle": {
                        "passed": oracle.passed, "returncode": oracle.returncode,
                        "stdout": oracle.stdout[-4000:], "stderr": oracle.stderr[-4000:],
                    },
                },
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
        transcript_path = str(tp)

    failure_mode = classify_code_editing(
        oracle_passed=bool(oracle.passed),
        tool_calls=tool_calls,
        invalid_tool_calls=invalid,
        write_attempts=tool_calls,  # structured mode has no read-only tools
        error=error,
    )
    return RunRecord(
        task_id=task.task_id, model=client.name, condition=fmt.name,
        passed=oracle.passed, turns=1,
        tool_calls=tool_calls, invalid_tool_calls=invalid,
        usage=msg.usage, latency_seconds=latency,
        cost_usd=cost_usd(client.name, msg.usage),
        stdout=oracle.stdout[-2000:], stderr=oracle.stderr[-2000:],
        error=error, transcript_path=transcript_path,
        extra={"failure_mode": failure_mode},
    )


def _ops_documentation(tools: list[dict[str, Any]]) -> str:
    """Render tool schemas as a compact text spec for the structured-mode prompt."""
    out: list[str] = []
    for t in tools:
        name = t["name"]
        desc = t.get("description", "").strip()
        schema = t.get("input_schema", {})
        props = schema.get("properties", {})
        required = set(schema.get("required") or [])
        args_lines = []
        for arg_name, arg_schema in props.items():
            req = " (required)" if arg_name in required else ""
            arg_type = arg_schema.get("type", "")
            arg_desc = arg_schema.get("description", "")
            args_lines.append(f"    - {arg_name}: {arg_type}{req} — {arg_desc}")
        args_block = "\n".join(args_lines) if args_lines else "    (no args)"
        out.append(f"### `{name}`\n{desc}\n\n  args:\n{args_block}")
    return "\n\n".join(out)


def _extract_json_changeset(text: str) -> dict[str, Any] | str:
    """Extract the JSON object from a model response. Returns dict or error string.

    If the model emits multiple JSON blocks (a self-correction pattern), use
    the LAST one — it's the model's final answer.
    """
    import json as _json
    import re as _re

    # Find every ```json ... ``` block. Take the last with non-empty `changes`.
    blocks = _re.findall(r"```(?:json)?\s*\n(.*?)\n\s*```", text, _re.DOTALL)
    candidates = list(reversed(blocks)) if blocks else [text.strip()]
    last_err: str | None = None
    for candidate in candidates:
        try:
            obj = _json.loads(candidate)
        except _json.JSONDecodeError as e:
            last_err = f"{e}"
            continue
        if not isinstance(obj, dict):
            last_err = f"expected JSON object, got {type(obj).__name__}"
            continue
        if obj.get("changes"):
            return obj
        # Keep last_err in case nothing has changes
        last_err = "JSON block has no `changes` field"
    if last_err is None:
        return "no JSON found in response"
    return last_err


def _language_guidance(language: str) -> str:
    """Language-specific guidance injected into the system prompt.

    The apply tools are language-aware (e.g. semantic ops use libcst for
    Python). Telling the model explicitly which language it's editing helps
    it produce syntactically correct `new_source` / patches.
    """
    if language == "python":
        return (
            "## Language\n"
            "You are editing PYTHON code. Apply tools use Python-aware "
            "implementations (libcst for AST-based ops). Any `new_source`, "
            "patch body, or `new_value` you emit must be valid Python — "
            "respect indentation, identifier rules, and Python operator "
            "syntax. For semantic ops, `name` arguments address Python "
            "definitions: top-level `def`, `class`, and `NAME = ...` "
            "assignments; methods are addressed as `ClassName.method`."
        )
    if language == "typescript":
        return (
            "## Language\n"
            "You are editing TYPESCRIPT code. Apply tools are TypeScript-"
            "aware. `new_source` must be valid TS — respect braces, "
            "semicolons, type annotations."
        )
    return f"## Language\nYou are editing {language} code."


def _snapshot(workdir: Path) -> tuple[tuple[str, int, float], ...]:
    """Cheap fingerprint of the workdir: (relpath, size, mtime) per file.

    Used to detect "no progress" turns. Skips `_overlay/` (oracle tests),
    `__pycache__/`, and dotfiles.
    """
    items: list[tuple[str, int, float]] = []
    for p in sorted(workdir.rglob("*")):
        if not p.is_file():
            continue
        parts = p.relative_to(workdir).parts
        if any(seg.startswith(".") for seg in parts):
            continue
        if "_overlay" in parts or "__pycache__" in parts:
            continue
        st = p.stat()
        items.append((str(p.relative_to(workdir)), st.st_size, st.st_mtime))
    return tuple(items)


def run_single_shot(
    task: TaskSpec,
    model: ModelClient,
    fmt: EditFormat,
    workdir: Path,
    transcripts_dir: Path | None = None,
    handle: ModelHandle | None = None,
) -> RunRecord:
    """One LLM call. Full project context up front. All edits in one response.

    This isolates "format quality" from "agent navigation" — every model gets
    the same context, and we measure whether the format lets it express the
    correct edit in a single turn.
    """
    import json as _json

    materialize(task, workdir)
    workdir = workdir.resolve()

    client, _backend, backend_name = _resolve_client_and_backend(model, handle)

    edit_tools = [t for t in fmt.tools() if t["name"] not in _READ_ONLY_TOOLS]
    system = "\n\n".join([
        SYSTEM_BASE_SINGLE_SHOT,
        _language_guidance(task.language),
        fmt.system_prompt(),
    ])
    user_text = _full_context_message(task, workdir)

    client.reset(system)
    client.add_user_text(user_text)
    transcript = Transcript(system=system)
    transcript.add_user_text(user_text)

    error: str | None = None
    t0 = time.monotonic()
    try:
        with span_llm_request(model=client.name, backend=backend_name) as llm_sp:
            msg = client.step(edit_tools)
            record_llm_usage(
                llm_sp,
                input_tokens=msg.usage.input_tokens,
                output_tokens=msg.usage.output_tokens,
                cache_read_tokens=msg.usage.cache_read_tokens,
                cache_creation_tokens=msg.usage.cache_creation_tokens,
            )
    except Exception as e:  # noqa: BLE001
        latency = time.monotonic() - t0
        return RunRecord(
            task_id=task.task_id,
            model=client.name,
            condition=fmt.name,
            passed=False,
            turns=1,
            tool_calls=0,
            invalid_tool_calls=0,
            usage=TurnUsage(),
            latency_seconds=latency,
            error=f"model_error: {type(e).__name__}: {e}",
        )
    transcript.add_assistant(msg)

    tool_calls = 0
    invalid = 0
    results: list[ToolResult] = []
    for call in msg.tool_calls:
        if call.name in _READ_ONLY_TOOLS:
            # Disallowed in single-shot — count as invalid but skip.
            invalid += 1
            tool_calls += 1
            results.append(
                ToolResult(call.call_id, "error", f"{call.name} not available in single-shot mode")
            )
            continue
        tool_calls += 1
        res = fmt.apply(call, workdir)
        if res.status == "error":
            invalid += 1
        results.append(res)
    transcript.add_tool_results(results)
    latency = time.monotonic() - t0

    if tool_calls == 0:
        error = "model emitted zero tool calls"

    oracle = run_oracle(task.oracle_cmd, workdir)

    transcript_path = None
    if transcripts_dir:
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        tp = transcripts_dir / f"{task.task_id}__{client.name}__{fmt.name}.json"
        tp.write_text(
            _json.dumps(
                {
                    "task_id": task.task_id,
                    "model": client.name,
                    "format": fmt.name,
                    "mode": "single_shot",
                    "system": transcript.system,
                    "entries": transcript.entries,
                    "oracle": {
                        "passed": oracle.passed,
                        "returncode": oracle.returncode,
                        "stdout": oracle.stdout[-4000:],
                        "stderr": oracle.stderr[-4000:],
                    },
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        transcript_path = str(tp)

    failure_mode = classify_code_editing(
        oracle_passed=bool(oracle.passed),
        tool_calls=tool_calls,
        invalid_tool_calls=invalid,
        write_attempts=tool_calls,  # single_shot uses only edit tools
        error=error,
    )
    return RunRecord(
        task_id=task.task_id,
        model=client.name,
        condition=fmt.name,
        passed=oracle.passed,
        turns=1,
        tool_calls=tool_calls,
        invalid_tool_calls=invalid,
        usage=msg.usage,
        latency_seconds=latency,
        cost_usd=cost_usd(client.name, msg.usage),
        stdout=oracle.stdout[-2000:],
        stderr=oracle.stderr[-2000:],
        error=error,
        transcript_path=transcript_path,
        extra={"failure_mode": failure_mode},
    )


def _full_context_message(task: TaskSpec, workdir: Path) -> str:
    """Build the single-shot user message: task + every file's full contents."""
    parts: list[str] = [f"# Task\n", task.instructions.strip(), ""]
    parts.append("# Project files (full contents — no view tool available)\n")
    files = _enumerate_workdir(workdir)
    for rel, text in files:
        parts.append(f"## `{rel}`\n```python\n{text}\n```\n")
    parts.append(
        "\n# Now emit your edits as tool calls. ONE response only — no follow-up "
        "turn. Apply every change you need in this single message."
    )
    return "\n".join(parts)


def _enumerate_workdir(workdir: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for p in sorted(workdir.rglob("*")):
        if not p.is_file():
            continue
        parts = p.relative_to(workdir).parts
        if "_overlay" in parts or "__pycache__" in parts:
            continue
        if any(seg.startswith(".") for seg in parts):
            continue
        rel = str(p.relative_to(workdir))
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        out.append((rel, text))
    return out


def _initial_user_message(task: TaskSpec, workdir: Path) -> str:
    parts = [f"# Task: {task.task_id}", "", task.instructions, ""]
    if task.files_in_context:
        parts.append("## Starting files (also available via `view_file`):\n")
        for rel in task.files_in_context:
            p = workdir / rel
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8")
            parts.append(f"### {rel}\n```\n{text}\n```\n")
    parts.append(
        "Make the edits, then call `done`. The oracle test will run automatically "
        "after you call `done`."
    )
    return "\n".join(parts)


# =====================================================================
# Patch Cascade — cheap model drafts a full answer, stronger models each
# emit only a *correction* against the current state, climbing a model
# tier ladder (haiku -> sonnet -> opus). Hypothesis: the correction is a
# short diff, so the expensive tier's output-token bill (the dominant
# cost + latency driver) drops vs solving from scratch. See the design
# discussion in the experiment notes. STRATEGY.md frames this as a
# context/cost study, not part of the phased-agent platform.
# =====================================================================

# Used only by the `rewrite` correction style (the ablation that isolates
# diff-output savings): the model rewrites whole files instead of diffing.
WRITE_FILE_TOOL: dict[str, Any] = {
    "name": "write_file",
    "description": (
        "Overwrite the ENTIRE contents of a file (creating it if needed). "
        "Provide the complete new file content — not a diff."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the working directory."},
            "content": {"type": "string", "description": "Complete new file content."},
        },
        "required": ["path", "content"],
    },
}


def _clear_pycache(workdir: Path) -> None:
    """Remove every __pycache__ under workdir.

    The cascade runs the oracle once per tier (the silent `first_passing_tier`
    probe). The probe imports the task's modules, writing .pyc files. When the
    NEXT tier edits a .py whose mtime lands in the same filesystem-resolution
    tick as the cached .pyc, CPython loads the STALE bytecode and the oracle
    scores the previous tier's code. Clearing __pycache__ before each oracle
    run makes every run hermetic.
    """
    import shutil as _shutil

    for pc in workdir.rglob("__pycache__"):
        if pc.is_dir():
            _shutil.rmtree(pc, ignore_errors=True)


def _oracle_hermetic(cmd: list[str], workdir: Path):
    """Run the oracle after clearing stale bytecode caches."""
    _clear_pycache(workdir)
    return run_oracle(cmd, workdir)


def _apply_write_file(call: ToolCall, workdir: Path) -> ToolResult:
    path = call.arguments.get("path")
    content = call.arguments.get("content")
    if not path or content is None:
        return ToolResult(call.call_id, "error", "missing path/content")
    try:
        target = EditFormat.resolve(workdir, path)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    if target.is_dir():
        return ToolResult(call.call_id, "error", f"is a directory: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return ToolResult(call.call_id, "ok", f"wrote {path} ({len(content)} bytes)")


SYSTEM_CASCADE_CORRECTION = (
    "You are a senior code-editing assistant reviewing a PREVIOUS attempt at a "
    "task. The system context below shows the ORIGINAL project files; the user "
    "message shows the diff the previous attempt applied to them.\n\n"
    "Your job: emit ONLY the minimal corrections needed to make the solution "
    "correct and complete. Critical rules:\n"
    "  - If the current code already satisfies the task, emit ZERO tool calls. "
    "Do not restyle or rewrite correct code.\n"
    "  - Change as little as possible. Prefer the smallest edit that fixes the "
    "problem. You are correcting, not rewriting from scratch.\n"
    "  - `str_replace`/`write_file` operate on the CURRENT files (original + the "
    "previous diff), not the original.\n"
    "  - You have ONE response. There is no follow-up turn and no test feedback."
)

# Strict reviewer used by the early-stop confidence gate. Prod-honest: it never
# sees the oracle, only the task + code, and decides whether to escalate.
#
# Deliberately CONSERVATIVE / asymmetric. The cost of the two errors is not
# symmetric: a false CONFIDENT halts the ladder and SHIPS BROKEN CODE; a false
# NOT_CONFIDENT merely spends one more (cheap-relative) review tier. So the gate
# is told to escalate on any doubt — CONFIDENT is reserved for cases it would
# stake correctness on.
SYSTEM_CASCADE_GATE = (
    "You are a STRICT, SKEPTICAL code reviewer. A cheaper model attempted a task; "
    "you decide whether it is so clearly correct that no stronger model needs to "
    "look. This is a high bar.\n\n"
    "Method — work through it before answering:\n"
    "  1. List EVERY explicit and implicit requirement in the task.\n"
    "  2. For each, point to the exact code that satisfies it. If you cannot, or "
    "the code is plausible-but-unverified, that requirement is NOT satisfied.\n"
    "  3. Consider edge cases and whether a thorough test suite would pass.\n\n"
    "Decision rule (ASYMMETRIC — obey strictly):\n"
    "  - Answer CONFIDENT only if you would stake correctness on it: every "
    "requirement is provably met and you see no plausible failure.\n"
    "  - If you have ANY doubt — a requirement you can't fully verify, an edge "
    "case, an unfamiliar API — answer NOT_CONFIDENT. Escalating costs little; "
    "wrongly approving a broken solution is the worst outcome. When unsure, escalate.\n\n"
    "First line: exactly CONFIDENT or NOT_CONFIDENT. Then a one-line reason."
)


def _files_block(files: list[tuple[str, str]]) -> str:
    """Render (relpath, contents) pairs as a fenced block. This is the large,
    STABLE chunk that lives in the cached system prefix."""
    out: list[str] = []
    for rel, text in files:
        out.append(f"## `{rel}`\n```python\n{text}\n```\n")
    return "\n".join(out)


def _prior_attempt_diff(original: dict[str, str], workdir: Path) -> str:
    """Unified diff of original files -> current workdir state.

    This is the small, VARIABLE suffix appended after the cached prefix: the
    correction tier reconstructs the current state as (original + this diff),
    so the big original-files block stays byte-identical (cacheable) across
    every correction call for the task."""
    import difflib

    current = dict(_enumerate_workdir(workdir))
    rels = sorted(set(original) | set(current))
    chunks: list[str] = []
    for rel in rels:
        a = original.get(rel, "").splitlines(keepends=True)
        b = current.get(rel, "").splitlines(keepends=True)
        if a == b:
            continue
        diff = difflib.unified_diff(a, b, fromfile=f"a/{rel}", tofile=f"b/{rel}")
        chunks.append("".join(diff))
    return "\n".join(chunks) if chunks else "(no changes — files identical to original)"


def _locality(original: dict[str, str], workdir: Path) -> dict[str, float]:
    """Model-INDEPENDENT locality features of the change so far (original ->
    current). The diff-vs-rewrite crossover is predicted by these: a large
    `changed_file_chars` with a small `edit_fraction` is where a diff is far
    shorter than a full rewrite (so the diff wins on cost AND latency)."""
    import difflib

    current = dict(_enumerate_workdir(workdir))
    changed = [r for r in (set(original) | set(current)) if original.get(r) != current.get(r)]
    changed_file_chars = sum(len(current.get(r, "")) for r in changed)
    diff_chars = 0
    for r in changed:
        a = original.get(r, "").splitlines(keepends=True)
        b = current.get(r, "").splitlines(keepends=True)
        diff_chars += sum(len(x) for x in difflib.unified_diff(a, b, n=3))
    return {
        "n_changed_files": float(len(changed)),
        "changed_file_chars": float(changed_file_chars),
        "diff_chars": float(diff_chars),
        # < 1 => the patch is smaller than the files it touches (diff should win);
        # >= 1 => diff representation as big as / bigger than a rewrite (rewrite wins).
        "edit_fraction": (diff_chars / changed_file_chars) if changed_file_chars else 0.0,
    }


def _count_failures(stdout: str) -> int | None:
    """Pull a failing-test count out of a pytest tail, e.g. '3 failed, 5 passed'.
    A coarse `draft_distance`: how far the cheap draft was from correct."""
    import re

    m = re.search(r"(\d+)\s+failed", stdout or "")
    if m:
        return int(m.group(1))
    if stdout and re.search(r"\d+\s+passed", stdout) and "failed" not in stdout:
        return 0
    return None


def _confidence_gate(
    judge: ModelClient, gate_system: str, diff_text: str,
) -> tuple[bool, TurnUsage, float, str]:
    """Ask a cheap judge whether the current attempt fully solves the task.

    Returns (confident, usage, latency_s, raw_text). The judge never sees the
    oracle — this is the deploy-time-honest stop signal."""
    user = (
        "The previous attempt applied this diff to the original files:\n"
        f"```diff\n{diff_text}\n```\n\n"
        "Does the resulting code FULLY and CORRECTLY satisfy the task? "
        "First line: CONFIDENT or NOT_CONFIDENT."
    )
    judge.reset(gate_system)
    judge.add_user_text(user)
    t0 = time.monotonic()
    with span_llm_request(model=judge.name, backend="cascade-gate") as sp:
        msg = judge.step([])
        record_llm_usage(
            sp, input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens,
            cache_read_tokens=msg.usage.cache_read_tokens,
            cache_creation_tokens=msg.usage.cache_creation_tokens,
        )
    latency = time.monotonic() - t0
    first = (msg.text or "").strip().splitlines()[0].upper() if (msg.text or "").strip() else ""
    confident = "CONFIDENT" in first and "NOT" not in first
    return confident, msg.usage, latency, (msg.text or "")


def _run_one_llm_pass(
    client: ModelClient,
    system: str,
    user_text: str,
    tools: list[dict[str, Any]],
    apply_fn,
    workdir: Path,
) -> tuple[TurnUsage, int, int, float, str]:
    """One stateless LLM call: reset -> ask -> apply every tool call.

    Returns (usage, n_edits, n_invalid, latency_s, assistant_text). Raises on
    a model/transport error so the caller can record it.
    """
    client.reset(system)
    client.add_user_text(user_text)
    t0 = time.monotonic()
    with span_llm_request(model=client.name, backend="cascade") as llm_sp:
        msg = client.step(tools)
        record_llm_usage(
            llm_sp,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            cache_read_tokens=msg.usage.cache_read_tokens,
            cache_creation_tokens=msg.usage.cache_creation_tokens,
        )
    latency = time.monotonic() - t0
    n_edits = 0
    n_invalid = 0
    for call in msg.tool_calls:
        if call.name == "done":
            continue
        n_edits += 1
        res = apply_fn(call, workdir)
        if res.status == "error":
            n_invalid += 1
    return msg.usage, n_edits, n_invalid, latency, msg.text or ""


def run_cascade(
    task: TaskSpec,
    tiers: list[ModelClient],
    fmt: EditFormat,
    workdir: Path,
    *,
    correction_style: str = "diff",  # "diff" (search_replace) | "rewrite" (write_file)
    gate_client: ModelClient | None = None,
    condition_name: str | None = None,
    transcripts_dir: Path | None = None,
) -> RunRecord:
    """Patch Cascade: tier 0 drafts a full single-shot patch; each later tier
    emits only a correction. The oracle runs once at the end (and silently after
    each tier, recorded as `first_passing_tier`).

    Caching / append-only: the large STABLE chunk (task + ORIGINAL files) lives
    in the `system` block, which the Anthropic client marks `cache_control:
    ephemeral`. Correction tiers append only a small unified DIFF of the prior
    attempt, so the cached prefix stays byte-identical across same-model calls
    (e.g. Opus recurring across conditions, or re-runs). NOTE: caches are keyed
    per-model, so the three different tiers of one cascade never share a cache —
    the win is cross-condition / cross-run reuse, not intra-cascade.

    `gate_client`, when given, is a cheap judge that decides after each non-final
    tier whether the current attempt is good enough to STOP (deploy-honest: it
    never sees the oracle). The silent oracle probe is kept only as an analysis
    ceiling and to score the gate's accuracy.

    `tiers` is ordered cheap -> expensive (built clients). Cost is summed PER
    TIER at each tier's own model price.
    """
    if not tiers:
        raise ValueError("run_cascade needs at least one tier")
    rewrite = correction_style == "rewrite"
    materialize(task, workdir)
    workdir = workdir.resolve()

    # Snapshot the ORIGINAL files now (before any tier edits) — this is the
    # stable, cacheable context shared by every correction call.
    original_files = dict(_enumerate_workdir(workdir))
    original_block = _files_block(list(original_files.items()))
    task_block = f"# Task\n\n{task.instructions.strip()}\n"

    diff_edit_tools = [t for t in fmt.tools() if t["name"] not in _READ_ONLY_TOOLS]
    correction_tools = [WRITE_FILE_TOOL] if rewrite else diff_edit_tools
    correction_apply = _apply_write_file if rewrite else fmt.apply

    # Stable system prefixes (cached). Identical across all same-role calls for
    # this task, so repeated same-model calls hit the prompt cache.
    draft_system = "\n\n".join([
        SYSTEM_BASE_SINGLE_SHOT, _language_guidance(task.language),
        fmt.system_prompt(), task_block,
        "# Project files (full contents — no view tool available)\n" + original_block,
    ])
    correction_system = "\n\n".join([
        SYSTEM_CASCADE_CORRECTION, _language_guidance(task.language),
        (fmt.system_prompt() if not rewrite else ""), task_block,
        "# Original project files (before any attempt)\n" + original_block,
    ]).strip()
    gate_system = "\n\n".join([
        SYSTEM_CASCADE_GATE, _language_guidance(task.language), task_block,
        "# Original project files (before any attempt)\n" + original_block,
    ])

    draft_user = (
        "Emit ALL edits now as tool calls — one response only, no follow-up turn."
    )

    total_usage = TurnUsage()
    total_cost = 0.0
    total_latency = 0.0
    total_edits = 0
    total_invalid = 0
    per_tier: list[dict[str, Any]] = []
    first_passing_tier: int | None = None
    stopped_early_at_tier: int | None = None
    draft_failing_tests: int | None = None
    error: str | None = None

    for i, client in enumerate(tiers):
        is_draft = i == 0
        if is_draft:
            system, user_text = draft_system, draft_user
            tools, apply_fn = diff_edit_tools, fmt.apply
        else:
            diff_text = _prior_attempt_diff(original_files, workdir)
            verb = ("`write_file` (full new contents of changed files)"
                    if rewrite else "`str_replace` / `create_file` / `delete_file`")
            system = correction_system
            user_text = (
                "The previous attempt applied this diff to the original files:\n"
                f"```diff\n{diff_text}\n```\n\n"
                f"Review against the task. Emit ONLY minimal corrections via {verb}. "
                "If the current code already satisfies the task, emit NO tool calls."
            )
            tools, apply_fn = correction_tools, correction_apply

        try:
            usage, n_edits, n_invalid, latency, _text = _run_one_llm_pass(
                client, system, user_text, tools, apply_fn, workdir
            )
        except Exception as e:  # noqa: BLE001
            error = f"model_error@tier{i}({client.name}): {type(e).__name__}: {e}"
            break

        tier_cost = cost_usd(client.name, usage)
        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        total_usage.cache_read_tokens += usage.cache_read_tokens
        total_usage.cache_creation_tokens += usage.cache_creation_tokens
        total_usage.ttft_seconds += usage.ttft_seconds
        total_usage.generate_seconds += usage.generate_seconds
        total_cost += tier_cost
        total_latency += latency
        total_edits += n_edits
        total_invalid += n_invalid

        # Silent oracle probe: analysis-only ceiling + ground truth for the gate.
        probe = _oracle_hermetic(task.oracle_cmd, workdir)
        if probe.passed and first_passing_tier is None:
            first_passing_tier = i
        if is_draft:
            draft_failing_tests = _count_failures(probe.stdout)

        entry = {
            "tier": i,
            "role": "draft" if is_draft else "correction",
            "model": client.name,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_creation_tokens": usage.cache_creation_tokens,
            "cost_usd": round(tier_cost, 6),
            "latency_s": round(latency, 3),
            "ttft_s": round(usage.ttft_seconds, 3),
            "generate_s": round(usage.generate_seconds, 3),
            "n_edits": n_edits,
            "n_invalid": n_invalid,
            "passed_after": probe.passed,
        }

        # Early-stop gate: after a non-final tier, a cheap judge decides whether
        # to escalate. Deploy-honest (no oracle). Its cost counts; its accuracy
        # is scored against the (hidden) probe.
        if gate_client is not None and i < len(tiers) - 1:
            diff_for_gate = _prior_attempt_diff(original_files, workdir)
            confident, g_usage, g_latency, _g_text = _confidence_gate(
                gate_client, gate_system, diff_for_gate
            )
            g_cost = cost_usd(gate_client.name, g_usage)
            total_cost += g_cost
            total_latency += g_latency
            total_usage.input_tokens += g_usage.input_tokens
            total_usage.output_tokens += g_usage.output_tokens
            total_usage.cache_read_tokens += g_usage.cache_read_tokens
            total_usage.cache_creation_tokens += g_usage.cache_creation_tokens
            total_usage.ttft_seconds += g_usage.ttft_seconds
            total_usage.generate_seconds += g_usage.generate_seconds
            entry.update({
                "gate_model": gate_client.name,
                "gate_confident": confident,
                "gate_correct": (confident == probe.passed),  # vs hidden oracle
                "gate_cost_usd": round(g_cost, 6),
                "gate_latency_s": round(g_latency, 3),
            })
            per_tier.append(entry)
            if confident:
                stopped_early_at_tier = i
                break
        else:
            per_tier.append(entry)

    oracle = _oracle_hermetic(task.oracle_cmd, workdir)
    locality = _locality(original_files, workdir)  # final change vs original
    cond = condition_name or ("cascade_" + correction_style + "_" + ">".join(c.name for c in tiers))

    transcript_path = None
    if transcripts_dir:
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        tp = transcripts_dir / f"{task.task_id}__{cond}.json"
        tp.write_text(
            json.dumps(
                {
                    "task_id": task.task_id, "condition": cond,
                    "correction_style": correction_style,
                    "tiers": [c.name for c in tiers],
                    "per_tier": per_tier,
                    "first_passing_tier": first_passing_tier,
                    "stopped_early_at_tier": stopped_early_at_tier,
                    "oracle": {
                        "passed": oracle.passed, "returncode": oracle.returncode,
                        "stdout": oracle.stdout[-4000:], "stderr": oracle.stderr[-4000:],
                    },
                },
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
        transcript_path = str(tp)

    top = per_tier[-1] if per_tier else {}
    return RunRecord(
        task_id=task.task_id,
        model=cond,  # the cascade identity; per-tier models live in extra
        condition=cond,
        passed=oracle.passed,
        turns=len(per_tier),
        tool_calls=total_edits,
        invalid_tool_calls=total_invalid,
        usage=total_usage,
        latency_seconds=total_latency,
        cost_usd=total_cost,
        stdout=oracle.stdout[-2000:],
        stderr=oracle.stderr[-2000:],
        error=error,
        transcript_path=transcript_path,
        extra={
            "correction_style": correction_style,
            "tiers": [c.name for c in tiers],
            "per_tier": per_tier,
            "first_passing_tier": first_passing_tier,
            "stopped_early_at_tier": stopped_early_at_tier,
            "tiers_run": len(per_tier),
            "draft_passed": (per_tier[0]["passed_after"] if per_tier else False),
            "draft_failing_tests": draft_failing_tests,
            # Model-independent locality of the final change — the predictor of
            # the diff-vs-rewrite crossover (big files + small edit_fraction => diff wins).
            "changed_file_chars": locality["changed_file_chars"],
            "diff_chars": locality["diff_chars"],
            "edit_fraction": locality["edit_fraction"],
            "n_changed_files": locality["n_changed_files"],
            "gate_model": (gate_client.name if gate_client is not None else None),
            # Gate accuracy vs the hidden oracle, across the gated decisions.
            "gate_decisions": [
                {"tier": e["tier"], "confident": e.get("gate_confident"),
                 "correct": e.get("gate_correct")}
                for e in per_tier if "gate_confident" in e
            ],
            # The mechanism knob: top-tier output tokens. Compare across
            # conditions to get diff-vs-rewrite-vs-scratch output savings.
            "top_tier_output_tokens": top.get("output_tokens", 0),
            "top_tier_cost_usd": top.get("cost_usd", 0.0),
        },
    )
