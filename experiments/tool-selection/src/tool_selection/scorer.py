"""Score a CallTrace against a Task's required_calls + forbidden_ops.

Scoring is structural (no execution). For each required_call:
  1. Resolve op against the catalog granularity -> (expected_tool, extra_args)
  2. Walk the trace's tool_use blocks for one whose .name == expected_tool
     AND whose .input satisfies extra_args (exact match) AND the task-level
     arg matchers (Eq/Regex/Contains/Present/OneOf).
  3. Each tool_use can satisfy at most one required_call (left-to-right
     greedy when multiple required calls share the same op).

Schema validity is checked against the surfaced tools' JSON schemas:
  - all required schema keys are present in input
  - no unknown keys (additionalProperties=False everywhere)
  - basic primitive-type check
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .matchers import Matcher, to_matcher
from .operations import op as get_op
from .types import Catalog, CallTrace, RequiredCall, ScoreCard, Task


@dataclass
class _ResolvedRequired:
    rc: RequiredCall
    expected_tool: str
    extra_args: dict[str, Any]
    matchers: dict[str, Matcher]

    def matches_call(self, call: dict[str, Any]) -> bool:
        """Strict match: name + op discriminator args + task-level matchers."""
        if not self.matches_selection(call):
            return False
        inp = call.get("input", {}) or {}
        for k, m in self.matchers.items():
            if not m.matches(inp.get(k)):
                return False
        return True

    def matches_selection(self, call: dict[str, Any]) -> bool:
        """Loose match: name + op discriminator args only. Used to compute
        selection_accuracy independently of args correctness."""
        if call.get("name") != self.expected_tool:
            return False
        inp = call.get("input", {}) or {}
        for k, v in self.extra_args.items():
            if inp.get(k) != v:
                return False
        return True


def _resolve_required(rc: RequiredCall, catalog: Catalog) -> _ResolvedRequired:
    spec = get_op(rc.op)
    tool_name, extra_args = spec.resolve(catalog.granularity)
    matchers = {k: to_matcher(v) for k, v in rc.args.items()}
    return _ResolvedRequired(rc=rc, expected_tool=tool_name, extra_args=extra_args, matchers=matchers)


def _validate_schema(tool, call_input: dict[str, Any]) -> list[str]:
    """Return a list of schema-violation reasons (empty if valid)."""
    schema = tool.json_schema
    props = schema.get("properties", {})
    required = schema.get("required", [])
    additional = schema.get("additionalProperties", True)
    errs: list[str] = []

    for key in required:
        if key not in call_input:
            errs.append(f"missing required arg '{key}'")

    if additional is False:
        for key in call_input:
            if key not in props:
                errs.append(f"unknown arg '{key}'")

    for key, val in call_input.items():
        if key not in props:
            continue
        expected = props[key].get("type")
        if expected is None:
            continue
        if expected == "string" and not isinstance(val, str):
            errs.append(f"arg '{key}' should be string, got {type(val).__name__}")
        elif expected == "integer" and not isinstance(val, int) or isinstance(val, bool) and expected == "integer":
            # bools are ints in python; reject them
            if not (isinstance(val, int) and not isinstance(val, bool)):
                errs.append(f"arg '{key}' should be integer, got {type(val).__name__}")
        elif expected == "boolean" and not isinstance(val, bool):
            errs.append(f"arg '{key}' should be boolean, got {type(val).__name__}")
        elif expected == "array" and not isinstance(val, list):
            errs.append(f"arg '{key}' should be array, got {type(val).__name__}")
        elif expected == "object" and not isinstance(val, dict):
            errs.append(f"arg '{key}' should be object, got {type(val).__name__}")

        enum = props[key].get("enum")
        if enum is not None and val not in enum:
            errs.append(f"arg '{key}'={val!r} not in {enum}")

    return errs


def _greedy_match(
    resolved: list[_ResolvedRequired],
    calls: list[dict[str, Any]],
    strict_order: bool,
    predicate_name: str,
) -> tuple[dict[int, int], set[int]]:
    """Run the greedy claiming algorithm with either 'matches_call' (strict)
    or 'matches_selection' (loose) as the predicate. Each emitted call is
    claimed by at most one required call.

    Returns (matched_by_req_idx, consumed_call_indices).
    """
    matched: dict[int, int] = {}
    consumed: set[int] = set()

    def get_pred(req: _ResolvedRequired):
        return getattr(req, predicate_name)

    if strict_order:
        cursor = 0
        for req_idx, req in enumerate(resolved):
            pred = get_pred(req)
            for call_idx in range(cursor, len(calls)):
                if call_idx in consumed:
                    continue
                if pred(calls[call_idx]):
                    matched[req_idx] = call_idx
                    consumed.add(call_idx)
                    cursor = call_idx + 1
                    break
    else:
        for req_idx, req in enumerate(resolved):
            pred = get_pred(req)
            for call_idx, call in enumerate(calls):
                if call_idx in consumed:
                    continue
                if pred(call):
                    matched[req_idx] = call_idx
                    consumed.add(call_idx)
                    break
    return matched, consumed


def score(trace: CallTrace, task: Task, catalog: Catalog) -> ScoreCard:
    resolved = [_resolve_required(rc, catalog) for rc in task.required_calls]

    # Pass A: strict match (name + discriminator + task-level matchers)
    matched_by_idx, consumed_call_indices = _greedy_match(
        resolved, trace.final_calls, task.strict_order, "matches_call"
    )

    # Pass B: loose match for selection accuracy (name + discriminator only).
    # Independent from pass A — different greedy claim, since the loose
    # predicate accepts more calls.
    selection_matched_by_idx, _ = _greedy_match(
        resolved, trace.final_calls, task.strict_order, "matches_selection"
    )

    missing = [resolved[i].rc.op for i in range(len(resolved)) if i not in matched_by_idx]

    surfaced = set(trace.surfaced_tools)
    hallucinated: list[str] = []
    extra: list[str] = []
    forbidden_called: list[str] = []
    schema_invalid: list[str] = []

    # Forbidden ops are resolved to (tool_name, extra_args). A call is forbidden
    # iff it matches BOTH the tool name AND all the discriminating extra args
    # (e.g. action="conversation" inside a fat-granularity gh_pr_feedback call).
    forbidden_resolved: list[tuple[str, dict[str, Any]]] = []
    for fop in task.forbidden_ops:
        tn, extra_args = get_op(fop).resolve(catalog.granularity)
        forbidden_resolved.append((tn, extra_args))

    def _call_matches_forbidden(call: dict[str, Any]) -> bool:
        name = call.get("name")
        inp = call.get("input", {}) or {}
        for tn, extra_args in forbidden_resolved:
            if name != tn:
                continue
            if all(inp.get(k) == v for k, v in extra_args.items()):
                return True
        return False

    for call_idx, call in enumerate(trace.final_calls):
        name = call.get("name")
        if not name:
            continue
        if name not in surfaced:
            hallucinated.append(name)
            continue

        tool = catalog.get_tool(name)
        if tool is not None:
            errs = _validate_schema(tool, call.get("input", {}) or {})
            if errs:
                schema_invalid.append(name)

        if _call_matches_forbidden(call):
            forbidden_called.append(name)
            continue

        if call_idx not in consumed_call_indices:
            extra.append(name)

    return ScoreCard(
        task_id=task.id,
        approach_id=trace.approach_id,
        granularity=catalog.granularity,
        final_model=trace.final_model,
        required_total=len(resolved),
        required_matched=len(matched_by_idx),
        missing_required=missing,
        hallucinated_calls=hallucinated,
        extra_calls=extra,
        forbidden_called=forbidden_called,
        schema_invalid_calls=schema_invalid,
        selection_matched=len(selection_matched_by_idx),
    )
