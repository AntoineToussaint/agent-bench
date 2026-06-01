"""SessionTrace -> partial Mind execution.json (native panels)."""

from __future__ import annotations

import json

from agent_eval import (
    AssistantMessage,
    PhaseConfig,
    PhaseReward,
    SessionTrace,
    Snapshot,
    ToolCall,
    Transcript,
    TurnUsage,
    session_to_native,
    write_native,
)


def _conversation(model: str, submitted: list[str]) -> Transcript:
    """A small but realistic localization conversation: 1 grep turn + 1 done."""
    t = Transcript(system="You localize the files an issue needs edited.")
    t.add_user_text("Issue: AltAz transform raises on empty input.")
    t.add_assistant(
        AssistantMessage(
            text="Let me search for AltAz.",
            tool_calls=[ToolCall(name="grep", arguments={"pattern": "AltAz"}, call_id="c1")],
            usage=TurnUsage(input_tokens=100, output_tokens=20),
        )
    )
    t.add_assistant(
        AssistantMessage(
            text="Found it.",
            tool_calls=[ToolCall(name="done", arguments={"files": submitted}, call_id="c2")],
            usage=TurnUsage(input_tokens=120, output_tokens=10),
        )
    )
    return t


def _session() -> SessionTrace:
    t = SessionTrace(task_id="astropy-12907")
    root = t.start(Snapshot())
    sub = ["astropy/coordinates/builtin_frames/altaz.py"]
    t.add(
        phase="localize",
        config=PhaseConfig(model="claude-sonnet-4-6", prompt_id="cot"),
        parent=root,
        snapshot=Snapshot.from_transcript(_conversation("sonnet", sub)),
        reward=PhaseReward(value=1.0, kind="oracle", detail={"passed": True}),
        span_id="bbbb0001",
    )
    return t


def test_task_and_objectives():
    doc = session_to_native(_session())
    assert doc["task"]["ID"] == "astropy-12907"
    assert doc["task"]["Status"] == "achieved"
    objs = doc["task"]["Plan"]["Objectives"]
    assert len(objs) == 1
    obj = next(iter(objs.values()))
    assert obj["Type"] == "localize"
    assert obj["Status"] == "achieved"


def test_llm_and_tool_calls_reconstructed_from_conversation():
    doc = session_to_native(_session())
    # two assistant turns -> two llm calls
    assert len(doc["audit"]["llm_calls"]) == 2
    first = doc["audit"]["llm_calls"][0]
    assert first["model"] == "claude-sonnet-4-6"
    assert first["prompt"]["system"].startswith("You localize")
    assert first["response"]["reasoning"] == "Let me search for AltAz."
    assert first["response"]["tool_call_count"] == 1
    # tool calls: grep + done
    names = [tc["name"] for tc in doc["audit"]["tool_calls"]]
    assert names == ["grep", "done"]
    assert doc["run"]["summary"]["llm_port_calls"] == 2
    assert doc["run"]["summary"]["tool_calls"] == 2


def test_object_index_links_native_to_span():
    doc = session_to_native(_session())
    idx = doc["object_index"]
    assert len(idx) == 1
    ref = idx[0]
    assert ref["kind"] == "objective"
    assert ref["display_name"] == "localize"
    # native objective id == the OpenInference span id we project (node.id)
    assert ref["span_id"] == ref["native_id"]
    assert ref["metadata"]["reward"] == 1.0


def test_absent_fields_not_fabricated():
    doc = session_to_native(_session())
    # We do not yet instrument context frames — report 0, don't invent frames.
    assert doc["run"]["summary"]["context_frames"] == 0
    assert "context_frames" not in doc or not doc.get("context_frames")


def test_context_signal_flows_from_metadata_to_native():
    """When a phase records context-engineering signal (frames/omissions), the
    native doc surfaces it instead of fabricating 0."""
    t = SessionTrace(task_id="t")
    root = t.start(Snapshot())
    t.add(
        phase="localize",
        config=PhaseConfig(model="m"),
        parent=root,
        snapshot=Snapshot.from_transcript(_conversation("m", ["src/a.py"])),
        reward=PhaseReward(value=1.0, kind="oracle", detail={"passed": True}),
        metadata={"context_frames": 5, "context_omissions": 3},
    )
    doc = session_to_native(t)
    obj = next(iter(doc["task"]["Plan"]["Objectives"].values()))
    assert obj["context_frames"] == 5
    assert obj["context_omissions"] == 3
    assert doc["run"]["summary"]["context_frames"] == 5  # summed, real


def test_write_native_roundtrips(tmp_path):
    p = write_native(_session(), tmp_path / "execution.json")
    doc = json.loads(p.read_text())
    assert doc["version"] == 1
    assert doc["task"]["ID"] == "astropy-12907"
