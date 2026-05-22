"""Trial runner — one (task, model, format) combination end-to-end."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agent_eval import ModelClient, RunRecord, ToolCall, ToolResult, Transcript, TurnUsage

from coding_tool.bench.oracle import run_oracle
from coding_tool.bench.task import materialize
from coding_tool.formats.base import EditFormat
from coding_tool.types import TaskSpec


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
) -> RunRecord:
    materialize(task, workdir)
    # Canonicalize once so symlink-bearing roots (e.g. macOS /var -> /private/var)
    # don't trip path comparisons inside the formats.
    workdir = workdir.resolve()

    system = SYSTEM_BASE + "\n\n" + fmt.system_prompt()
    model.reset(system)
    transcript = Transcript(system=system)

    # Initial user message: instructions + (optional) starter file contents
    user_text = _initial_user_message(task, workdir)
    model.add_user_text(user_text)
    transcript.add_user_text(user_text)

    total_usage = TurnUsage()
    turns = 0
    tool_calls = 0
    invalid_tool_calls = 0
    consecutive_error_turns = 0
    no_progress_turns = 0
    last_workdir_state: tuple[tuple[str, int, float], ...] | None = None
    done = False
    error: str | None = None

    t0 = time.monotonic()
    while turns < max_turns and not done:
        turns += 1
        try:
            msg = model.step(fmt.tools())
        except Exception as e:  # noqa: BLE001
            error = f"model_error: {type(e).__name__}: {e}"
            break
        transcript.add_assistant(msg)
        total_usage.input_tokens += msg.usage.input_tokens
        total_usage.output_tokens += msg.usage.output_tokens
        total_usage.cache_read_tokens += msg.usage.cache_read_tokens
        total_usage.cache_creation_tokens += msg.usage.cache_creation_tokens

        if not msg.tool_calls:
            # Nudge once if model went silent.
            model.add_user_text(
                "You did not call any tools. Use the available tools to make edits, "
                "or call `done` if you are finished."
            )
            transcript.add_user_text("(nudge: no tool calls)")
            continue

        results: list[ToolResult] = []
        turn_had_only_errors = True
        turn_had_write_attempt = False
        for call in msg.tool_calls:
            tool_calls += 1
            if call.name not in _READ_ONLY_TOOLS:
                turn_had_write_attempt = True
            res = fmt.apply(call, workdir)
            if res.status == "error":
                invalid_tool_calls += 1
            else:
                turn_had_only_errors = False
            results.append(res)
            if call.name == "done":
                done = True
        model.add_tool_results(results)
        transcript.add_tool_results(results)

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
        tp = transcripts_dir / f"{task.task_id}__{model.name}__{fmt.name}.json"
        tp.write_text(
            json.dumps(
                {
                    "task_id": task.task_id,
                    "model": model.name,
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

    return RunRecord(
        task_id=task.task_id,
        model=model.name,
        condition=fmt.name,
        passed=oracle.passed,
        turns=turns,
        tool_calls=tool_calls,
        invalid_tool_calls=invalid_tool_calls,
        usage=total_usage,
        latency_seconds=latency,
        stdout=oracle.stdout[-2000:],
        stderr=oracle.stderr[-2000:],
        error=error,
        transcript_path=transcript_path,
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
) -> RunRecord:
    """One LLM call. Model outputs JSON change-set as text. No tool_use API."""

    import json as _json
    import re as _re

    materialize(task, workdir)
    workdir = workdir.resolve()

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

    model.reset(system)
    model.add_user_text(user_text)
    transcript = Transcript(system=system)
    transcript.add_user_text(user_text)

    t0 = time.monotonic()
    try:
        msg = model.step([])  # empty tools list — model must output text
    except Exception as e:  # noqa: BLE001
        latency = time.monotonic() - t0
        return RunRecord(
            task_id=task.task_id, model=model.name, condition=fmt.name,
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
        tp = transcripts_dir / f"{task.task_id}__{model.name}__{fmt.name}.json"
        tp.write_text(
            _json.dumps(
                {
                    "task_id": task.task_id, "model": model.name, "format": fmt.name,
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

    return RunRecord(
        task_id=task.task_id, model=model.name, condition=fmt.name,
        passed=oracle.passed, turns=1,
        tool_calls=tool_calls, invalid_tool_calls=invalid,
        usage=msg.usage, latency_seconds=latency,
        stdout=oracle.stdout[-2000:], stderr=oracle.stderr[-2000:],
        error=error, transcript_path=transcript_path,
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
) -> RunRecord:
    """One LLM call. Full project context up front. All edits in one response.

    This isolates "format quality" from "agent navigation" — every model gets
    the same context, and we measure whether the format lets it express the
    correct edit in a single turn.
    """
    import json as _json

    materialize(task, workdir)
    workdir = workdir.resolve()

    edit_tools = [t for t in fmt.tools() if t["name"] not in _READ_ONLY_TOOLS]
    system = "\n\n".join([
        SYSTEM_BASE_SINGLE_SHOT,
        _language_guidance(task.language),
        fmt.system_prompt(),
    ])
    user_text = _full_context_message(task, workdir)

    model.reset(system)
    model.add_user_text(user_text)
    transcript = Transcript(system=system)
    transcript.add_user_text(user_text)

    error: str | None = None
    t0 = time.monotonic()
    try:
        msg = model.step(edit_tools)
    except Exception as e:  # noqa: BLE001
        latency = time.monotonic() - t0
        return RunRecord(
            task_id=task.task_id,
            model=model.name,
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
        tp = transcripts_dir / f"{task.task_id}__{model.name}__{fmt.name}.json"
        tp.write_text(
            _json.dumps(
                {
                    "task_id": task.task_id,
                    "model": model.name,
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

    return RunRecord(
        task_id=task.task_id,
        model=model.name,
        condition=fmt.name,
        passed=oracle.passed,
        turns=1,
        tool_calls=tool_calls,
        invalid_tool_calls=invalid,
        usage=msg.usage,
        latency_seconds=latency,
        stdout=oracle.stdout[-2000:],
        stderr=oracle.stderr[-2000:],
        error=error,
        transcript_path=transcript_path,
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
