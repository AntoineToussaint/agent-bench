"""LLM agent failure-mode classification.

See `lib/agent-eval-core/FAILURE_MODES.md` for the taxonomy and citations.

Two public entry points:

  - `classify_output(...)` — given just an agent's final outputs
    (predicted_files, raw_response_text, turn_count, etc.), return the
    most specific failure mode that applies, or `None` if the trial
    passed or no mode matches.

  - `classify_trace(spans, trial_span_id)` — given a list of OTEL JSONL
    spans (as produced by `agent_eval.tracing.JsonlSpanExporter`), do a
    richer diagnosis using per-turn tool-call signatures, observed
    paths, etc.

Both classifiers are conservative: when evidence is ambiguous, they
return `None` rather than mislabeling. Concrete detectors:

  - `format_anchoring`: `<function_calls>` or `<invoke>` tags in raw text
  - `path_fabrication`: predicted_files contains paths not in observed_paths
  - `premature_termination`: turn_count <= 2 AND tool_call_count < 2 (and failed)
  - `harness_blocked_exploration`: one-shot protocol AND failed
  - `harness_blocked_termination`: turn_cap reached AND no `done` call AND tool_choice forced
  - `step_repetition`: 2+ consecutive turns with no new (tool, args) signature
  - `superficial_information_matching`: predicted basename overlaps issue token,
    not in gold (heuristic)

`reasoning_action_mismatch`, `blind_strategy_switching`, and
`context_amnesia` are documented in FAILURE_MODES.md but not yet
implemented — they need richer signals than the current trace shape
carries.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal


FailureMode = Literal[
    # Tier 1: Information failures
    "path_fabrication",
    "superficial_information_matching",
    "context_amnesia",
    # Tier 2: Process failures
    "step_repetition",
    "premature_termination",
    "reasoning_action_mismatch",
    "blind_strategy_switching",
    # Tier 3: Protocol failures
    "format_anchoring",
    "harness_blocked_termination",
    "harness_blocked_exploration",
    # Tier 4: Tool-selection-specific
    "hallucinated_tool",          # called a tool not in the surfaced catalog
    "wrong_tool_selected",         # called a real tool but not the gold one
    "missing_required_call",       # never made one of the required calls
    "forbidden_tool_called",       # called a tool the task explicitly forbids
    # Tier 5: Code-editing-specific
    "oracle_failed",               # edits applied, tests didn't pass
    "read_only_loop",              # agent only viewed files, never edited
    "edit_apply_error",            # format.apply() returned errors on all attempts
]


_MIMICRY_RE = re.compile(r"<function_calls>|<invoke\b", re.IGNORECASE)


# ============ output-only classifier ============


def classify_output(
    *,
    predicted_files: list[str],
    gold_files: set[str] | frozenset[str],
    observed_paths: list[str] | None = None,
    issue_text: str = "",
    raw_response_text: str = "",
    turn_count: int = 1,
    tool_call_count: int = 0,
    has_tool_channel: bool = True,
) -> FailureMode | None:
    """Classify a trial from output-only signals.

    Args:
        predicted_files: the agent's final ranked file list.
        gold_files: ground-truth files (source files, per the
            localization contract — test files are excluded).
        observed_paths: paths the agent actually viewed/listed/grepped.
            Required to detect `path_fabrication`.
        issue_text: the original issue text. Used for
            `superficial_information_matching` heuristic.
        raw_response_text: full raw model output (across all turns).
            Used to detect `format_anchoring`.
        turn_count: total turns in the trial.
        tool_call_count: total tool calls (excluding `done`).
        has_tool_channel: True if the protocol provided any tool channel
            (turn-loop), False for one-shot.

    Returns the most specific FailureMode that applies, or None if the
    trial passed or no mode matches.

    Detection precedence: format > path fabrication > harness-blocked >
    premature termination > superficial match. Earlier wins when
    multiple apply.
    """
    pred_set = {_norm(p) for p in predicted_files}
    gold_set = {_norm(g) for g in gold_files}

    # Trial passed — nothing to classify.
    if gold_set and gold_set.issubset(pred_set):
        return None

    # 1. harness_blocked_exploration — one-shot trial with no tools.
    # Checked first because in one-shot mode there's no protocol-format
    # to anchor against; any `<function_calls>` tags are collateral
    # (Haiku one-shot frequently emits them anyway). The operational
    # failure is the missing tool channel, not the format.
    if not has_tool_channel:
        return "harness_blocked_exploration"

    # 2. format_anchoring — protocol-level red flag in turn-loop trials.
    # We're past the no-tool-channel gate, so this means the model emitted
    # provider-native tool_use syntax inside a non-tool_use protocol.
    if raw_response_text and _MIMICRY_RE.search(raw_response_text):
        return "format_anchoring"

    # 3. path_fabrication — submitted a path the agent never observed.
    if observed_paths is not None:
        observed_set = {_norm(p) for p in observed_paths}
        if any(p not in observed_set for p in pred_set):
            return "path_fabrication"

    # 4. premature_termination — ended with insufficient exploration.
    if turn_count <= 2 and tool_call_count < 2:
        return "premature_termination"

    # 5. superficial_information_matching — heuristic. A predicted file's
    # basename contains a ≥4-char substring also in the issue text, and
    # the file isn't in gold. We only flag this when the GOLD basename
    # does NOT also appear in the issue (otherwise the agent would have
    # had the right signal and gotten it right).
    if issue_text and pred_set and gold_set:
        issue_lower = issue_text.lower()
        gold_names = {p.rsplit("/", 1)[-1].lower() for p in gold_set}
        # The agent had a fair chance if the gold name is in the issue.
        gold_hinted = any(_basename_in_text(n, issue_lower) for n in gold_names)
        if not gold_hinted:
            wrong_preds = pred_set - gold_set
            for wp in wrong_preds:
                basename = wp.rsplit("/", 1)[-1].lower()
                if _basename_in_text(basename, issue_lower):
                    return "superficial_information_matching"

    return None


def _norm(p: str) -> str:
    """Path normalization matching the localization contract."""
    return p.replace("\\", "/").lstrip("./")


def _basename_in_text(basename: str, text: str) -> bool:
    """Did this basename's stem appear in the text? (heuristic)

    Looks for the basename minus its `.py` extension as a substring of
    length >= 4. Avoids false positives on tiny matches like 'io.py'.
    """
    stem = basename.rsplit(".", 1)[0]
    return len(stem) >= 4 and stem in text


# ============ trace-based classifier ============


def classify_trace(
    spans: list[dict[str, Any]],
    trial_span_id: str | None = None,
) -> FailureMode | None:
    """Classify a trial from its OTEL trace spans.

    Args:
        spans: JSONL-decoded list of span dicts (as written by
            `agent_eval.tracing.JsonlSpanExporter`).
        trial_span_id: which trial span to classify. If None, picks the
            single `trial` span in `spans` (raises if there are 0 or >1).

    Returns the most specific FailureMode that applies, or None.

    Compared to `classify_output`, this can additionally detect:
      - `step_repetition` (per-turn `(tool, args)` signatures)
      - `harness_blocked_termination` (forced terminal didn't fire, or
        the loop aborted due to thrashing under a `tool_choice=any`
        constraint)
    """
    trial = _select_trial(spans, trial_span_id)
    if trial is None:
        return None

    t_attrs = trial.get("attrs", {})
    passed = bool(t_attrs.get("agent_eval.trial.passed"))
    if passed:
        return None

    condition = str(t_attrs.get("agent_eval.condition") or "")
    has_tool_channel = "one-shot" not in condition

    # Gather child spans.
    children = _children_of(spans, trial["span_id"])
    turns = sorted(
        (c for c in children if c["name"] == "turn"),
        key=lambda s: s.get("start_unix_ns", 0),
    )

    # The trial-level `agent_eval.backend` is set by the sweep runner
    # from `handle.backend` BEFORE the trial runs — which can be stale
    # when a research factory hardcodes a different backend. The per-turn
    # `agent_eval.backend` attribute is set by the trial itself from the
    # backend it actually used, so we prefer that.
    backend = ""
    if turns:
        backend = str(turns[0].get("attrs", {}).get("agent_eval.backend") or "")
    if not backend:
        backend = str(t_attrs.get("agent_eval.backend") or "")

    # Aggregate per-turn signal.
    raw_text = ""
    tool_call_signatures: list[tuple[str, str]] = []
    new_sig_per_turn: list[bool] = []
    n_done_calls = 0
    turn_count = len(turns)
    tool_call_count = 0
    observed_paths: list[str] = []
    forced_terminal_seen = False

    for turn_sp in turns:
        ta = turn_sp.get("attrs", {})
        # tool_names is a JSON-stringified list
        names_json = ta.get("agent_eval.turn.tool_names", "[]")
        try:
            names = json.loads(names_json) if isinstance(names_json, str) else names_json
        except Exception:  # noqa: BLE001
            names = []
        for n in names:
            if n == "done":
                n_done_calls += 1
            else:
                tool_call_count += 1
        if ta.get("agent_eval.turn.forced_terminal"):
            forced_terminal_seen = True
        if "agent_eval.turn.added_new_signature" in ta:
            new_sig_per_turn.append(bool(ta["agent_eval.turn.added_new_signature"]))

        # tool_call children of this turn
        for tc in _children_of(spans, turn_sp["span_id"]):
            if tc["name"] != "tool_call":
                continue
            args_json = tc.get("attrs", {}).get("agent_eval.tool.args", "{}")
            tool_name = tc.get("attrs", {}).get("agent_eval.tool.name", "")
            tool_call_signatures.append((tool_name, args_json))
            # Extract a `path` if present for observed-path tracking.
            try:
                args = json.loads(args_json) if isinstance(args_json, str) else args_json
                if isinstance(args, dict) and isinstance(args.get("path"), str):
                    observed_paths.append(args["path"])
            except Exception:  # noqa: BLE001
                pass

    # 1. harness_blocked_exploration — one-shot failure (checked first
    # for the same reason as in classify_output: in one-shot mode mimicry
    # is collateral, not the actual failure).
    if not has_tool_channel:
        return "harness_blocked_exploration"

    # 2. format_anchoring — prompt-based JSON protocol with rejected
    # mimicry. We catch it via per-turn `invalid_attempts` + the backend
    # name as a proxy for "model emitted bad-format actions."
    if backend == "prompt_json":
        total_invalid = sum(
            int(t.get("attrs", {}).get("agent_eval.turn.invalid_attempts", 0))
            for t in turns
        )
        if total_invalid > 0 and tool_call_count == 0:
            return "format_anchoring"

    # 3. step_repetition — 2+ consecutive turns with new_sig False.
    if len(new_sig_per_turn) >= 2:
        consec_no_new = 0
        for flag in new_sig_per_turn:
            if not flag:
                consec_no_new += 1
                if consec_no_new >= 2:
                    return "step_repetition"
            else:
                consec_no_new = 0

    # 4. harness_blocked_termination — the loop exhausted turns under a
    # tool_choice=any backend without ever calling `done` voluntarily.
    # The `request_terminal` escape valve forces a `done` on the final
    # turn, but if the loop aborted via the no-progress escape valve
    # first, no `done` call ever happens.
    if backend in {"schema_enforced"} and n_done_calls == 0:
        return "harness_blocked_termination"

    # 5. premature_termination — too few turns / too little exploration.
    if turn_count <= 2 and tool_call_count < 2:
        return "premature_termination"

    return None


def _select_trial(
    spans: list[dict[str, Any]],
    trial_span_id: str | None,
) -> dict[str, Any] | None:
    """Pick the trial span to classify."""
    trials = [s for s in spans if s["name"] == "trial"]
    if not trials:
        return None
    if trial_span_id is None:
        if len(trials) != 1:
            raise ValueError(
                f"Multiple trial spans in input; specify trial_span_id "
                f"(got {len(trials)})"
            )
        return trials[0]
    for t in trials:
        if t["span_id"] == trial_span_id:
            return t
    return None


def _children_of(spans: list[dict[str, Any]], parent_id: str) -> list[dict[str, Any]]:
    """Return spans whose parent_span_id == parent_id."""
    return [s for s in spans if s.get("parent_span_id") == parent_id]


# ============ experiment-specific classifiers ============
#
# These take experiment-native ScoreCard / oracle / trace data and
# return one of the Tier 4/5 failure modes. They're optional add-ons on
# top of `classify_output` — call this AFTER the generic one to upgrade
# a generic diagnosis with experiment-specific signal.


def classify_tool_selection(
    *,
    hallucinated_calls: list[str] | None,
    missing_required: list[str] | None,
    forbidden_called: list[str] | None,
    schema_invalid_calls: list[str] | None,
    selection_matched: bool,
    passed: bool,
) -> FailureMode | None:
    """Diagnose a tool-selection trial.

    Inputs come straight off `tool_selection.types.ScoreCard`. Order of
    precedence below reflects severity — hallucination is worse than
    "called the wrong real tool" is worse than "missed one of several
    required calls".
    """
    if passed:
        return None
    if hallucinated_calls:
        return "hallucinated_tool"
    if forbidden_called:
        return "forbidden_tool_called"
    if not selection_matched:
        return "wrong_tool_selected"
    if missing_required:
        return "missing_required_call"
    if schema_invalid_calls:
        return "edit_apply_error"  # closest generic mode
    return None


def classify_code_editing(
    *,
    oracle_passed: bool,
    tool_calls: int,
    invalid_tool_calls: int,
    write_attempts: int,
    error: str | None,
) -> FailureMode | None:
    """Diagnose a code-editing trial.

    Args:
        oracle_passed: did the oracle command return 0?
        tool_calls: total tool calls dispatched
        invalid_tool_calls: subset that returned ToolResult.status == "error"
        write_attempts: tool calls that were NOT view_file/list_files/done
        error: the runner-set error string (e.g. "aborted: 3 consecutive...")

    Order of precedence: edit_apply_error (write_attempts but all failed)
    > read_only_loop (no write attempts) > oracle_failed (writes happened
    but tests still failed).
    """
    if oracle_passed:
        return None
    if write_attempts > 0 and invalid_tool_calls >= write_attempts:
        return "edit_apply_error"
    if write_attempts == 0 and tool_calls > 0:
        return "read_only_loop"
    if write_attempts > 0:
        return "oracle_failed"
    return None
