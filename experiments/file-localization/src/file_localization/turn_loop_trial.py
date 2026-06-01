"""Backend-driven turn-loop trial for file localization.

ONE loop, three protocol backends:

    NativeToolUseBackend    — provider tool_use API, tool_choice=auto
                              (the current default; what real agents do)
    SchemaEnforcedBackend   — provider tool_use API, tool_choice=any
                              (forces the model to emit a tool call,
                              defeats `<function_calls>` mimicry)
    PromptJSONBackend       — text-only fenced JSON + mimicry detection
                              (what works when no tool_use API is available)

The trial doesn't know which one is active. It declares its tool surface
(from `file_localization.tools`), drives a turn loop with escape valves,
scores the result.

This file replaces both the old `turn_loop_trial` (native-only) and
`turn_loop_structured_trial` (prompt-JSON-only) implementations. The two
factory functions remain so existing callers don't break:

    make_turn_loop_trial(...)              → NativeToolUseBackend
    make_structured_turn_loop_trial(...)   → PromptJSONBackend
    make_turn_loop_trial_with_backend(...) → explicit
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent_eval.failure_modes import classify_output
from agent_eval.pricing import cost_usd
from agent_eval.protocols import (
    NativeToolUseBackend,
    PromptJSONBackend,
    SchemaEnforcedBackend,
    ToolBackend,
)
from agent_eval.tracing import (
    record_llm_usage,
    span_llm_request,
    span_tool_call,
    span_turn,
)
from agent_eval.types import (
    ModelHandle,
    RunRecord,
    ToolCall,
    ToolResult,
    Transcript,
    TurnUsage,
)

from file_localization.contract import LocalizationTask, score
from file_localization.prompts import system_prompt_for, user_message
from file_localization.repo_view import LocalRepoView, RepoView
from file_localization.tools import (
    TOOL_SCHEMAS,
    TOOL_SPECS,
    WORKFLOW_HINT,
    apply_tool_call,
)

# Re-exports so existing imports keep working after the refactor.
__all__ = [
    "LocalRepoView",
    "RepoView",
    "TOOL_SCHEMAS",
    "TOOL_SPECS",
    "apply_tool_call",
    "make_turn_loop_trial",
    "make_structured_turn_loop_trial",
    "make_turn_loop_trial_with_backend",
    "_Limits",
    "_signature",
]

# Legacy aliases.
TOOLS = TOOL_SCHEMAS
_apply = apply_tool_call


# ============ limits ============


@dataclass
class _Limits:
    max_turns: int = 15
    max_consecutive_errors: int = 3
    max_no_progress_turns: int = 4


def _provider_of(model_name: str) -> str:
    """Map a model id to the provider tag a ContextPolicy expects.

    Keep in sync with `agent_eval.context.types.Provider`.
    """
    n = model_name.lower()
    if "claude" in n or "anthropic" in n:
        return "anthropic"
    if "gpt" in n or n.startswith("o1") or n.startswith("o3") or "openai" in n:
        return "openai"
    if "gemini" in n or "google" in n:
        return "google"
    return "unknown"


def _signature(call: ToolCall) -> tuple[str, str]:
    """Hashable key for one tool call: (name, json-args).

    Used to detect a turn that emitted only signatures the model has
    already used — i.e. a turn that made no exploration progress.
    """
    import json as _json

    try:
        args = _json.dumps(call.arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        args = str(call.arguments)
    return (call.name, args)


# ============ unified trial loop ============


def make_turn_loop_trial_with_backend(
    backend: ToolBackend | None,
    repo_view_for: Callable[[LocalizationTask], RepoView],
    *,
    limits: _Limits | None = None,
    fp_penalty: float = 0.05,
    top_k: int | None = None,
    transcripts_dir: "Path | None" = None,
    emit_session_dir: "Path | None" = None,
    debugger_dir: "Path | None" = None,
):
    """Factory: build a Trial that drives a turn loop.

    Args:
        backend: explicit ToolBackend (for research, e.g. testing
            "schema-enforced on Sonnet"). If None, defer to whatever
            backend the ModelHandle was constructed with — i.e. the
            model's YAML-configured default. This is the "production"
            path: don't hard-code a protocol, let the model bring its
            preferred one.

    The backend controls everything wire-format-specific:
      - whether tools are conveyed via API or system prompt
      - whether the model has a tool_choice constraint
      - how results / hints go back to the model

    Everything else — loop structure, escape valves, scoring, transcript
    dumping — is shared.
    """
    limits = limits or _Limits()

    def trial(handle: ModelHandle, condition: str, task: LocalizationTask) -> RunRecord:
        # Resolve the effective backend: factory override wins, else
        # the handle's bundled backend. The trial body uses `bk` from
        # here on so the same variable name covers both paths.
        bk: ToolBackend = backend if backend is not None else handle.backend
        # Overwrite the trial-span's backend attribute with the actually
        # used one. The sweep runner sets a default from `handle.backend`
        # before knowing whether the factory will override it.
        from opentelemetry import trace as _otel_trace

        _trial_sp = _otel_trace.get_current_span()
        if _trial_sp is not None:
            _trial_sp.set_attribute("agent_eval.backend", bk.name)
        client = handle.client
        repo = repo_view_for(task)

        # Compose system prompt: shared task-class focus + backend's
        # tool-description addendum + workflow hint.
        addendum = bk.system_prompt_addendum(TOOL_SPECS)
        extras = "\n\n".join(p for p in (addendum, WORKFLOW_HINT) if p)
        system_prompt = system_prompt_for(task.task_class, extra_tools_block=extras)

        transcript = Transcript(system=system_prompt)
        client.reset(system_prompt)
        user_text = user_message(task.repo, task.base_commit, task.issue_text)
        client.add_user_text(user_text)
        transcript.add_user_text(user_text)

        submitted: list[str] = []
        seen_signatures: set[tuple[str, str]] = set()
        observed_paths: list[str] = []  # for failure-mode classification
        raw_text_chunks: list[str] = []  # ditto
        turns = 0
        tool_calls = 0
        invalid = 0
        consecutive_errors = 0
        no_progress_turns = 0
        mimicry_total = 0
        # Context-engineering signal: how many messages the context policy
        # elided across the run (0 for KeepEverything), and the peak context
        # size. These feed the native trace's context_frames (STRATEGY.md Step 2).
        ctx_omitted_total = 0
        ctx_frames_peak = 0
        # Step-level metrics: aggregated at trial end. See DIMENSIONS.md.
        turns_with_new_signature = 0    # for wasted_turn_fraction
        actions_per_active_turn: list[int] = []  # for batch_efficiency
        # Context-engineering observation: input_tokens per turn. With
        # our "keep everything" policy this grows monotonically; under
        # a future pruning policy it would plateau. See HARNESS.md.
        input_tokens_per_turn: list[int] = []
        error: str | None = None
        done_flag = False

        t0 = time.monotonic()
        in_tok = out_tok = cache_r = cache_w = 0

        while turns < limits.max_turns and not done_flag:
            turns += 1
            with span_turn(turn_idx=turns, backend=bk.name) as turn_sp:
                # On the final allowed turn (no margin for nudges left), force
                # the terminal tool. Without this, backends that suppress the
                # model's "I'm done" reasoning (SchemaEnforcedBackend) never
                # produce an answer at all.
                forced_terminal = turns == limits.max_turns
                turn_sp.set_attribute("agent_eval.turn.forced_terminal", forced_terminal)
                # Apply the context policy: replace client's history with
                # whatever the policy returns. KeepEverything is a no-op;
                # other policies prune / elide. See HARNESS.md.
                if handle.context_policy is not None and hasattr(client, "messages"):
                    provider = _provider_of(client.name)
                    _before = len(client.messages)
                    client.messages = handle.context_policy.prepare(
                        client.messages, provider=provider, turn_idx=turns
                    )
                    _omitted = max(0, _before - len(client.messages))
                    ctx_omitted_total += _omitted
                    ctx_frames_peak = max(ctx_frames_peak, len(client.messages))
                    turn_sp.set_attribute(
                        "agent_eval.context_policy", handle.context_policy.name
                    )
                    turn_sp.set_attribute("agent_eval.context.omitted_this_turn", _omitted)
                try:
                    with span_llm_request(model=client.name, backend=bk.name) as llm_sp:
                        if forced_terminal:
                            response = bk.request_terminal(client, TOOL_SPECS, "done")
                        else:
                            response = bk.request(client, TOOL_SPECS)
                        record_llm_usage(
                            llm_sp,
                            input_tokens=response.usage.input_tokens,
                            output_tokens=response.usage.output_tokens,
                            cache_read_tokens=response.usage.cache_read_tokens,
                            cache_creation_tokens=response.usage.cache_creation_tokens,
                        )
                        if response.error:
                            llm_sp.set_attribute("agent_eval.llm.error", response.error)
                except Exception as e:  # noqa: BLE001
                    error = f"model_error: {type(e).__name__}: {e}"
                    turn_sp.set_attribute("agent_eval.turn.error", error)
                    break

                in_tok += response.usage.input_tokens
                out_tok += response.usage.output_tokens
                cache_r += response.usage.cache_read_tokens
                cache_w += response.usage.cache_creation_tokens
                input_tokens_per_turn.append(response.usage.input_tokens)
                if response.raw_text:
                    raw_text_chunks.append(response.raw_text)
                turn_sp.set_attribute("gen_ai.usage.input_tokens", response.usage.input_tokens)
                turn_sp.set_attribute("gen_ai.usage.output_tokens", response.usage.output_tokens)
                turn_sp.set_attribute("agent_eval.turn.n_actions", len(response.actions))
                turn_sp.set_attribute("agent_eval.turn.invalid_attempts", response.invalid_attempts)
                turn_sp.set_attribute(
                    "agent_eval.turn.tool_names",
                    json.dumps([a.name for a in response.actions]),
                )

                # Log the assistant turn in the shared transcript shape.
                from agent_eval.types import AssistantMessage as _AM

                transcript.add_assistant(
                    _AM(
                        text=response.raw_text,
                        tool_calls=response.actions,
                        usage=response.usage,
                        raw={"backend": response.backend_name, "error": response.error},
                    )
                )

                invalid += response.invalid_attempts
                mimicry_total += response.invalid_attempts  # PromptJSON uses this for mimicry; harmless on native

                # Hard error from the backend: nudge and re-try (or abort).
                if response.error and not response.actions:
                    tool_calls += 1  # we DID make a model call, but got nothing usable
                    # Build the nudge — combine error + any hints.
                    parts = [response.error]
                    parts.extend(response.hints)
                    bk.send_hint(client, "\n".join(parts))
                    transcript.add_user_text("(hint) " + " | ".join(parts))
                    consecutive_errors += 1
                    no_progress_turns += 1
                    turn_sp.set_attribute("agent_eval.turn.outcome", "hint")
                    if consecutive_errors >= limits.max_consecutive_errors:
                        error = f"aborted: {consecutive_errors} consecutive error turns"
                        break
                    if not done_flag and no_progress_turns >= limits.max_no_progress_turns:
                        error = f"aborted: {no_progress_turns} no-progress turns"
                        break
                    continue

                # No actions AND no error: model just narrated. Nudge.
                if not response.actions:
                    tool_calls += 1
                    bk.send_hint(
                        client,
                        "You did not call any tools. Use the available ops to "
                        "explore, then call `done(files=[...])` when ready.",
                    )
                    transcript.add_user_text("(nudge: no actions)")
                    no_progress_turns += 1
                    turn_sp.set_attribute("agent_eval.turn.outcome", "no_actions")
                    if not done_flag and no_progress_turns >= limits.max_no_progress_turns:
                        error = f"aborted: {no_progress_turns} no-progress turns"
                        break
                    continue

                # Dispatch every action against the repo view.
                results: list[ToolResult] = []
                dispatched_calls: list[ToolCall] = []
                turn_all_errors = True
                turn_added_signature = False
                for tc in response.actions:
                    tool_calls += 1
                    sig = _signature(tc)
                    is_new = sig not in seen_signatures
                    if is_new:
                        seen_signatures.add(sig)
                        turn_added_signature = True
                    with span_tool_call(tc.name, tc.arguments) as call_sp:
                        call_sp.set_attribute("agent_eval.tool.new_signature", is_new)
                        res = apply_tool_call(tc, repo)
                        call_sp.set_attribute("agent_eval.tool.status", res.status)
                        call_sp.set_attribute("agent_eval.tool.result_chars", len(res.content or ""))
                    # Track which paths the agent actually visited — needed
                    # for `path_fabrication` detection. `path` is the arg
                    # name used by list_files / view_file; grep's `glob`
                    # isn't a real path so we skip it.
                    p = tc.arguments.get("path") if isinstance(tc.arguments, dict) else None
                    if isinstance(p, str) and p:
                        observed_paths.append(p)
                    if res.status == "ok":
                        turn_all_errors = False
                    else:
                        invalid += 1
                    results.append(res)
                    dispatched_calls.append(tc)
                    if tc.name == "done":
                        files = tc.arguments.get("files") or []
                        if isinstance(files, list):
                            submitted = [str(f) for f in files]
                        done_flag = True

                # Step-level accumulators: this turn made progress?
                if turn_added_signature:
                    turns_with_new_signature += 1
                # Batch efficiency tracks active turns (turns that actually
                # dispatched non-`done` actions) — `done`-only turns
                # shouldn't pollute the mean.
                non_done_actions = sum(1 for c in dispatched_calls if c.name != "done")
                if non_done_actions > 0:
                    actions_per_active_turn.append(non_done_actions)

                transcript.add_tool_results(results)
                turn_sp.set_attribute("agent_eval.turn.added_new_signature", turn_added_signature)
                turn_sp.set_attribute("agent_eval.turn.done_called", done_flag)
                turn_sp.set_attribute(
                    "agent_eval.turn.outcome",
                    "done" if done_flag else ("dispatched" if not turn_all_errors else "all_errors"),
                )

                if done_flag:
                    # Loop is exiting — don't bother sending the ack back to
                    # the model. The Native backend would normally REQUIRE
                    # matching tool_results, but since we're not making
                    # another API call, skipping is safe.
                    break

                bk.send_results(client, dispatched_calls, results)

                # Escape valves.
                if turn_all_errors:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                if consecutive_errors >= limits.max_consecutive_errors:
                    error = f"aborted: {consecutive_errors} consecutive error turns"
                    break

                if not turn_added_signature:
                    no_progress_turns += 1
                else:
                    no_progress_turns = 0
                if not done_flag and no_progress_turns >= limits.max_no_progress_turns:
                    error = (
                        f"aborted: {no_progress_turns} turns without trying a new "
                        f"(tool, args) signature"
                    )
                    break

        latency = time.monotonic() - t0
        s = score(submitted, task.gold_all, k=top_k, fp_penalty=fp_penalty)

        # Diagnose failures. Returns None when the trial passed.
        failure_mode = classify_output(
            predicted_files=submitted,
            gold_files=task.gold_all,
            observed_paths=observed_paths,
            issue_text=task.issue_text,
            raw_response_text="\n".join(raw_text_chunks),
            turn_count=turns,
            tool_call_count=tool_calls,
            has_tool_channel=True,
        )

        usage = TurnUsage(
            input_tokens=in_tok,
            output_tokens=out_tok,
            cache_read_tokens=cache_r,
            cache_creation_tokens=cache_w,
        )

        # Emit the phase-trace control object (TRACE.md). Localization is one
        # phase, read-only, so this is a single `localize` node under a root —
        # the unit a contextual bandit over PhaseConfig arms will compare
        # (STRATEGY.md Step 2). Built when either output is requested.
        session_path: str | None = None
        if emit_session_dir is not None or debugger_dir is not None:
            from opentelemetry import trace as _otel_trace2

            from file_localization.phase import localization_session

            _ctx = _otel_trace2.get_current_span().get_span_context()
            _span_id = format(_ctx.span_id, "016x") if _ctx and _ctx.span_id else None
            _trace_id = format(_ctx.trace_id, "032x") if _ctx and _ctx.trace_id else None
            sess = localization_session(
                task=task,
                model=client.name,
                prompt_id=bk.name,
                context_strategy=(
                    handle.context_policy.name if handle.context_policy else "none"
                ),
                backend=bk.name,
                transcript=transcript,
                score=s,
                submitted=submitted,
                span_id=_span_id,
                trace_id=_trace_id,
                context_frames=ctx_frames_peak,
                context_omissions=ctx_omitted_total,
            )
            if emit_session_dir is not None:
                _p = Path(emit_session_dir) / f"{task.task_id}__{client.name}__{condition}.jsonl"
                sess.to_jsonl(_p)
                session_path = str(_p)
            if debugger_dir is not None:
                from agent_eval.openinference import write_to_debugger

                write_to_debugger(sess, traces_dir=debugger_dir)

        rec = RunRecord(
            task_id=task.task_id,
            model=client.name,
            condition=condition,
            passed=s.passed,
            turns=turns,
            tool_calls=tool_calls,
            invalid_tool_calls=invalid,
            usage=usage,
            latency_seconds=latency,
            cost_usd=cost_usd(client.name, usage),
            error=error,
            extra={
                **s.as_extra(),
                "submitted": submitted,
                "done_called": done_flag,
                "unique_signatures": len(seen_signatures),
                "mimicry_attempts": mimicry_total,
                "backend": bk.name,
                "failure_mode": failure_mode,
                "observed_paths": observed_paths,
                # Step-level metrics (see DIMENSIONS.md).
                "wasted_turn_fraction": (
                    (turns - turns_with_new_signature) / turns if turns > 0 else 0.0
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
                "context_policy": (
                    handle.context_policy.name if handle.context_policy else "none"
                ),
                "cache_hit_rate": (
                    cache_r / (in_tok + cache_r) if (in_tok + cache_r) > 0 else 0.0
                ),
                "session_path": session_path,
                "context_omitted_total": ctx_omitted_total,
                "context_frames_peak": ctx_frames_peak,
            },
        )
        if transcripts_dir:
            from agent_eval import dump_transcript as _dump

            rec.transcript_path = str(_dump(transcripts_dir, rec, transcript))
        return rec

    return trial


def make_turn_loop_trial(
    repo_view_for: Callable[[LocalizationTask], RepoView],
    *,
    limits: _Limits | None = None,
    fp_penalty: float = 0.05,
    top_k: int | None = None,
    transcripts_dir: "Path | None" = None,
    emit_session_dir: "Path | None" = None,
    debugger_dir: "Path | None" = None,
):
    """Default factory: use whichever backend the ModelHandle carries.

    The handle's backend is configured in `data/model_backends.yaml`
    (currently `native` for all listed models). This is the "production"
    path: the experiment doesn't pick a backend; the model brings one.

    For research overrides, use `make_turn_loop_trial_with_backend(...)`
    with an explicit backend, or the `make_*_turn_loop_trial` sugar.
    """
    return make_turn_loop_trial_with_backend(
        None,  # defer to handle.backend
        repo_view_for,
        limits=limits,
        fp_penalty=fp_penalty,
        top_k=top_k,
        transcripts_dir=transcripts_dir,
        emit_session_dir=emit_session_dir,
        debugger_dir=debugger_dir,
    )


def make_structured_turn_loop_trial(
    repo_view_for: Callable[[LocalizationTask], RepoView],
    *,
    limits: _Limits | None = None,
    fp_penalty: float = 0.05,
    top_k: int | None = None,
    transcripts_dir: "Path | None" = None,
):
    """Compat factory: prompt-based JSON backend (text-only protocol).

    The model never sees the tool_use API. Tools are described in the
    system prompt; the model emits fenced JSON blocks; the harness
    detects `<function_calls>` mimicry and rejects affected turns.
    """
    return make_turn_loop_trial_with_backend(
        PromptJSONBackend(),
        repo_view_for,
        limits=limits,
        fp_penalty=fp_penalty,
        top_k=top_k,
        transcripts_dir=transcripts_dir,
    )


def make_schema_enforced_turn_loop_trial(
    repo_view_for: Callable[[LocalizationTask], RepoView],
    *,
    limits: _Limits | None = None,
    fp_penalty: float = 0.05,
    top_k: int | None = None,
    transcripts_dir: "Path | None" = None,
):
    """Factory: schema-enforced tool_use (tool_choice=any).

    Forces the model to emit a tool call every turn. Defeats
    `<function_calls>` mimicry by constraining the decoder rather than
    asking politely in the prompt.
    """
    return make_turn_loop_trial_with_backend(
        SchemaEnforcedBackend(),
        repo_view_for,
        limits=limits,
        fp_penalty=fp_penalty,
        top_k=top_k,
        transcripts_dir=transcripts_dir,
    )
