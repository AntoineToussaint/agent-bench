"""Unit-style sanity check for the scorer using synthetic CallTraces.

Runs three scenarios per task: perfect / wrong-tool / forbidden-confusable.
Prints pass/fail per scenario. No API calls.
"""

from __future__ import annotations

from tool_selection.catalogs import fat_catalog, narrow_catalog
from tool_selection.operations import op as get_op
from tool_selection.scorer import score
from tool_selection.tasks import by_id
from tool_selection.types import CallTrace


def _make_trace(task_id: str, approach_id: str, calls, surfaced, granularity, model="test"):
    return CallTrace(
        task_id=task_id,
        approach_id=approach_id,
        granularity=granularity,
        final_model=model,
        surfaced_tools=list(surfaced),
        final_calls=list(calls),
    )


def _perfect_calls(task, catalog):
    """Construct the minimal set of correct tool calls for this task."""
    calls = []
    for rc in task.required_calls:
        tool_name, extra_args = get_op(rc.op).resolve(catalog.granularity)
        input_dict = dict(extra_args)
        for k, m in rc.args.items():
            # Pick a concrete value that satisfies the matcher
            from tool_selection.matchers import Contains, Eq, OneOf, Present, Regex

            actual = m if hasattr(m, "matches") else None
            if isinstance(m, Eq):
                input_dict[k] = m.value
            elif isinstance(m, Contains):
                needle = m.needle
                if k == "paths":
                    input_dict[k] = [needle]
                else:
                    input_dict[k] = f"prefix {needle} suffix"
            elif isinstance(m, Regex):
                # A trivial string that the regex would likely match - we cheat by giving the pattern
                import re as _re

                pat = m.pattern
                input_dict[k] = "release: v0.4.0 update with content that mentions feat(themes): add dark mode stylesheet and feat(themes): wire dark mode into theme loader and test(themes) and rename helpers fix typo receive and handle missing config 0.4.0"
            elif isinstance(m, Present):
                input_dict[k] = "value"
            elif isinstance(m, OneOf):
                input_dict[k] = m.options[0]
            else:
                # bare value -> Eq behavior
                input_dict[k] = m
        calls.append({"name": tool_name, "input": input_dict})
    return calls


def main():
    task_ids = ["E1-stage-and-commit-typo", "E4-pr-conversation-comment", "M3-inline-review-comment"]
    for catalog in [narrow_catalog, fat_catalog]:
        print(f"\n========== catalog: {catalog.granularity} ==========")
        for tid in task_ids:
            task = by_id(tid)
            surfaced = [t.name for t in catalog.all_tools]

            # SCENARIO 1: perfect
            calls = _perfect_calls(task, catalog)
            trace = _make_trace(task.id, "perfect", calls, surfaced, catalog.granularity)
            sc = score(trace, task, catalog)
            ok = sc.task_success and not sc.missing_required
            print(f"  {tid:42s} perfect      : success={sc.task_success} matched={sc.required_matched}/{sc.required_total} missing={sc.missing_required} {'OK' if ok else 'FAIL'}")
            if not ok:
                print(f"     hallucinated={sc.hallucinated_calls} extras={sc.extra_calls} schema_invalid={sc.schema_invalid_calls} forbidden={sc.forbidden_called}")

            # SCENARIO 2: wrong tool — call a totally unrelated tool
            wrong = [{"name": "git_status", "input": {}}]
            trace = _make_trace(task.id, "wrong", wrong, surfaced, catalog.granularity)
            sc = score(trace, task, catalog)
            ok = not sc.task_success and sc.required_matched < sc.required_total
            print(f"  {tid:42s} wrong-tool   : success={sc.task_success} matched={sc.required_matched}/{sc.required_total} {'OK (failed as expected)' if ok else 'BAD'}")

            # SCENARIO 3: forbidden confusable (only meaningful for tasks with forbidden_ops)
            if task.forbidden_ops:
                fop = task.forbidden_ops[0]
                fname, fargs = get_op(fop).resolve(catalog.granularity)
                bad_call = {"name": fname, "input": dict(fargs)}
                # Add the bare minimum to make it a valid-looking call - just toss in 'number' / 'body' if needed
                tool = catalog.get_tool(fname)
                if tool:
                    for req_key in tool.json_schema.get("required", []):
                        if req_key not in bad_call["input"]:
                            ptype = tool.json_schema["properties"][req_key].get("type", "string")
                            bad_call["input"][req_key] = (
                                0 if ptype == "integer" else "x" if ptype == "string" else False
                            )
                trace = _make_trace(task.id, "forbidden", [bad_call], surfaced, catalog.granularity)
                sc = score(trace, task, catalog)
                ok = not sc.task_success and fname in sc.forbidden_called
                print(f"  {tid:42s} forbidden    : success={sc.task_success} forbidden_called={sc.forbidden_called} {'OK (failed as expected)' if ok else 'BAD'}")


if __name__ == "__main__":
    main()
