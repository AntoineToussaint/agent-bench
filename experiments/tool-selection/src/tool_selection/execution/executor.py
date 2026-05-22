"""Mock tool executor: applies task failure triggers, returns realistic error
or success placeholder text.

We never actually run git / gh / fs commands. The success path returns a
generic "(success)" string — the model uses this as a positive signal but
gains no information from it (matches real production where most tool
results are large or noisy and the agent shouldn't depend on parsing them
to reason about correctness).
"""

from __future__ import annotations

from .state import Call, CallResult, FailureTrigger

# Module-level registry of DerivedTool wrappers. Populated by the experiment
# runner as lessons promote to derived tools; consumed here to translate
# derived-tool calls into their source-tool equivalents BEFORE the failure
# triggers see them. Result: the source-tool's failure triggers fire against
# the post-wrap args, which by construction are correct.
_DERIVED_WRAPPERS: dict[str, "object"] = {}


def register_derived_tool(derived) -> None:  # type: ignore[no-untyped-def]
    """Called when a DerivedTool is promoted; wires it into the executor."""
    _DERIVED_WRAPPERS[derived.tool.name] = derived


def clear_derived_tools() -> None:
    """Reset between experimental conditions."""
    _DERIVED_WRAPPERS.clear()


def execute_call(
    call: Call,
    prior_calls: list[Call],
    triggers: tuple[FailureTrigger, ...],
) -> CallResult:
    """Run one tool call through the failure-trigger predicates.

    If the called tool is a registered DerivedTool, args are translated to
    the source tool first — the failure trigger sees the post-wrap call,
    which by construction is correct, so no failure fires. This is the
    structural payoff of phase-3 lesson promotion.
    """
    # Derived-tool translation (phase 3)
    if call.tool in _DERIVED_WRAPPERS:
        derived = _DERIVED_WRAPPERS[call.tool]
        try:
            wrapped_args = derived.wrap_fn(call.args)
            translated = Call(tool=derived.source_tool_name, args=wrapped_args)
        except Exception as exc:  # noqa: BLE001
            return CallResult(
                ok=False,
                error=f"derived-tool wrapper error: {exc!r}",
                triggered_by=f"{call.tool} wrap_fn failed",
                category="schema-invalid",
            )
        # Run the translated call through the source tool's gauntlet
        return execute_call(translated, prior_calls, triggers)

    # Regular path: check failure triggers
    for trig in triggers:
        try:
            fires = trig.when(call, prior_calls)
        except Exception:
            fires = False
        if fires:
            return CallResult(
                ok=False,
                error=trig.error_message,
                triggered_by=trig.note,
                category=trig.category,
            )
    return CallResult(ok=True, output=_success_placeholder(call))


def _success_placeholder(call: Call) -> str:
    """Realistic success message keyed by tool + command shape.

    For `bash` we mimic shell output for common discovery commands so the
    model doesn't have to keep guessing about state. The intent: if the
    model is going to do discovery, give it something useful so it can
    proceed to the real work in the same turn.
    """
    name = call.tool
    if name == "bash":
        cmd = (call.args.get("command") or "").strip()
        if cmd == "pwd":
            return "/repo"
        if cmd.startswith("ls") or cmd == "ls":
            return "src/  verify/  pyproject.toml  README.md"
        if cmd.startswith("cat ") or cmd.startswith("head"):
            return "(file contents truncated)"
        if " pytest " in f" {cmd}" or cmd.startswith("pytest "):
            return (
                "============================= test session starts ==============================\n"
                "rootdir: /repo\ncollected 3 items\n\n"
                "verify/test_X.py ...                                              [100%]\n\n"
                "============================== 3 passed in 0.42s ==============================\n"
            )
        return "(command exited 0)"
    if name.startswith("read"):
        return "(file contents — pre-surfaced in task context)"
    if name.startswith("list_directory"):
        return "src/  verify/  pyproject.toml  README.md"
    if name.startswith("write") or name.startswith("create_file") or name.startswith("append"):
        return "ok"
    if name.startswith("git_") or name.startswith("git."):
        return "ok"
    if name.startswith("gh_") or name.startswith("gh.") or name.startswith("github"):
        return "ok (operation completed)"
    return "ok"
