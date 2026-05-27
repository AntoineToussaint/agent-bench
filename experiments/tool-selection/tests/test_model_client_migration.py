"""Offline smoke tests for the ModelClient migration.

Each refactored callsite (`OnePhase`, `TwoPhase`, `LLMSelector`,
`synthesize_patch`, `synthesize_from_cluster`) is verified to route through
`agent_eval.make_client(...)` rather than instantiating a provider SDK
directly. We monkeypatch `make_client` to return a stub `ModelClient` that
records what was sent and returns a canned `AssistantMessage`, then assert
both the call happened and that the surrounding code propagated the stub's
usage into `PipelineStep` / cost / token fields.

The point: catch any future regression where someone re-introduces a direct
`anthropic.Anthropic()` / `OpenAI()` construction inside a phase/selector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_eval.types import AssistantMessage, ModelClient, ToolCall, ToolResult, TurnUsage

from tool_selection.adapters import all_tasks
from tool_selection.execution.lessons import Lesson
from tool_selection.types import Tool


# --- stub ---


@dataclass
class _StubClient(ModelClient):
    """Records `step` calls and returns whatever AssistantMessage we queued."""

    name: str = "stub-model"
    canned: AssistantMessage = field(
        default_factory=lambda: AssistantMessage(
            text="", tool_calls=[], usage=TurnUsage(input_tokens=12, output_tokens=4)
        )
    )
    max_tokens: int = 8192

    system: str = ""
    user_texts: list[str] = field(default_factory=list)
    tool_results: list[list[ToolResult]] = field(default_factory=list)
    step_calls: list[list[dict[str, Any]]] = field(default_factory=list)

    def reset(self, system: str) -> None:
        self.system = system
        self.user_texts = []
        self.tool_results = []
        self.step_calls = []

    def add_user_text(self, text: str) -> None:
        self.user_texts.append(text)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        self.tool_results.append(list(results))

    def step(
        self,
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
    ) -> AssistantMessage:
        self.step_calls.append(list(tools))
        return self.canned


def _tiny_tool() -> Tool:
    return Tool(
        name="dummy_tool",
        description="A no-op tool used only to satisfy the surfaced-tools list.",
        json_schema={"type": "object", "properties": {}, "required": []},
        toolbox="dummy",
    )


# Each refactored module does `from agent_eval import make_client`, which binds
# the name into that module's namespace. Patching `agent_eval.make_client`
# alone wouldn't affect those callers — we patch the module-local symbol
# (e.g. `tool_selection.phases.one_phase.make_client`).


# --- tests ---


def test_one_phase_uses_make_client(monkeypatch) -> None:
    from tool_selection.phases import one_phase

    canned = AssistantMessage(
        text="ok",
        tool_calls=[ToolCall(name="dummy_tool", arguments={"k": 1}, call_id="c1")],
        usage=TurnUsage(input_tokens=100, output_tokens=20),
    )
    stub = _StubClient(canned=canned)
    monkeypatch.setattr(one_phase, "make_client", lambda model: stub)

    task = all_tasks()[0]
    result = one_phase.OnePhase().execute(task, [_tiny_tool()], "claude-sonnet-4-6")

    assert result.error is None
    assert stub.step_calls, "expected exactly one step() invocation"
    # Tool schemas reach the client in Anthropic shape.
    sent = stub.step_calls[0]
    assert sent and "input_schema" in sent[0]
    # The model's tool_use was propagated.
    assert result.final_calls == [{"name": "dummy_tool", "input": {"k": 1}}]
    assert result.final_text == "ok"
    # Token counts flowed into the PipelineStep.
    assert result.steps[0].input_tokens == 100
    assert result.steps[0].output_tokens == 20
    assert result.steps[0].cost_usd >= 0.0
    assert result.steps[0].kind == "final_shot"


def test_two_phase_routes_both_phases_through_make_client(monkeypatch) -> None:
    """Phase 1 (text-only) and phase 2 (per-tool) must both go through make_client."""
    from tool_selection.phases import two_phase

    # Phase 1 returns a one-line plan; phase 2 returns the arg dict.
    phase1_canned = AssistantMessage(
        text='[{"name": "dummy_tool", "intent": "do it"}]',
        tool_calls=[],
        usage=TurnUsage(input_tokens=50, output_tokens=15),
    )
    phase2_canned = AssistantMessage(
        text="",
        tool_calls=[ToolCall(name="dummy_tool", arguments={"x": 1}, call_id="c1")],
        usage=TurnUsage(input_tokens=80, output_tokens=8),
    )

    call_log: list[_StubClient] = []

    def factory(model: str) -> ModelClient:
        # Return phase1 stub first, phase2 stub for the next call.
        canned = phase1_canned if len(call_log) == 0 else phase2_canned
        c = _StubClient(canned=canned)
        call_log.append(c)
        return c

    monkeypatch.setattr(two_phase, "make_client", factory)

    task = all_tasks()[0]
    result = two_phase.TwoPhase().execute(task, [_tiny_tool()], "claude-sonnet-4-6")

    assert result.error is None
    assert len(call_log) == 2, f"expected 1 phase1 + 1 phase2 call, got {len(call_log)}"
    assert result.final_calls == [{"name": "dummy_tool", "input": {"x": 1}}]
    # Each step recorded its own tokens.
    assert result.steps[0].input_tokens == 50  # phase 1
    assert result.steps[1].input_tokens == 80  # phase 2


def test_llm_selector_uses_make_client(monkeypatch) -> None:
    from tool_selection.selectors import llm as llm_mod

    canned = AssistantMessage(
        text='["alpha", "beta"]',
        tool_calls=[],
        usage=TurnUsage(input_tokens=30, output_tokens=5),
    )
    stub = _StubClient(canned=canned)
    monkeypatch.setattr(llm_mod, "make_client", lambda model: stub)

    @dataclass
    class _Cand:
        name: str
        description: str

    cands = [_Cand("alpha", "first"), _Cand("beta", "second"), _Cand("gamma", "third")]
    selection = llm_mod.LLMSelector("claude-haiku-4-5").select("pick two", cands, k=2)

    assert stub.step_calls == [[]]  # text-only call, no tools
    assert selection.selected_ids == ["alpha", "beta"]
    assert selection.steps[0].input_tokens == 30
    assert selection.steps[0].output_tokens == 5
    assert selection.steps[0].cost_usd >= 0.0


def test_augmenter_uses_make_client(monkeypatch) -> None:
    from tool_selection.execution import augmenter

    canned = AssistantMessage(
        text="Known gotchas: this is the addendum body.",
        tool_calls=[],
        usage=TurnUsage(input_tokens=200, output_tokens=40),
    )
    stub = _StubClient(canned=canned)
    monkeypatch.setattr(augmenter, "make_client", lambda model: stub)

    lessons = [
        Lesson(
            id="L1",
            text="always prefix with verify/",
            category="path",
            key="bash",
            scope="tool",
            source_error="collected 0 items",
        )
    ]
    src = Tool(
        name="bash",
        description="run a shell command",
        json_schema={"type": "object", "properties": {"command": {"type": "string"}}},
        toolbox="shell",
    )
    out = augmenter.synthesize_patch(lessons, src, model="claude-sonnet-4-6")

    assert out.patch is not None
    assert out.patch.target_tool == "bash"
    assert "addendum body" in out.patch.addendum
    assert out.input_tokens == 200
    assert out.output_tokens == 40
    assert out.cost_usd >= 0.0


def test_synthesizer_uses_make_client(monkeypatch) -> None:
    from tool_selection.execution import synthesizer

    canned = AssistantMessage(
        text='{"name": "derived_x", "description": "d", "json_schema": {"type":"object","properties":{}}, "source_tool": "bash", "wrap": {"command": "echo hi"}, "conditionals": {}}',
        tool_calls=[],
        usage=TurnUsage(input_tokens=300, output_tokens=60),
    )
    stub = _StubClient(canned=canned)
    monkeypatch.setattr(synthesizer, "make_client", lambda model: stub)

    lessons = [
        Lesson(
            id="L1",
            text="some rule",
            category="path",
            key="bash",
            scope="tool",
            source_error="boom",
        )
    ]
    src = Tool(
        name="bash",
        description="run a shell command",
        json_schema={"type": "object", "properties": {"command": {"type": "string"}}},
        toolbox="shell",
    )
    res = synthesizer.synthesize_from_cluster(lessons, src, model="claude-sonnet-4-6")

    assert res.derived is not None
    assert res.derived.tool.name == "derived_x"
    assert res.input_tokens == 300
    assert res.output_tokens == 60
    assert res.cost_usd >= 0.0
