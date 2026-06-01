"""SessionTrace -> OpenInference OTLP projection (the interchange layer)."""

from __future__ import annotations

import json

from agent_eval import (
    PhaseConfig,
    PhaseReward,
    SessionTrace,
    Snapshot,
    session_to_otlp,
    write_otlp,
)


def _forked_session() -> SessionTrace:
    t = SessionTrace(task_id="astropy-12907")
    root = t.start(Snapshot())
    t.add(
        phase="localize",
        config=PhaseConfig(model="claude-haiku-4-5", prompt_id="terse"),
        parent=root,
        reward=PhaseReward(value=0.0, kind="oracle", detail={}),
    )
    t.add(
        phase="localize",
        config=PhaseConfig(model="claude-sonnet-4-6", prompt_id="cot"),
        parent=root,
        reward=PhaseReward(value=1.0, kind="oracle", detail={}),
        span_id="bbbb0001",
    )
    return t


def _spans(doc) -> list[dict]:
    return doc[0]["resourceSpans"][0]["scopeSpans"][0]["spans"]


def _attrs(span) -> dict:
    out = {}
    for a in span["attributes"]:
        v = a["value"]
        out[a["key"]] = next(iter(v.values()))
    return out


def test_doc_shape_is_otlp():
    doc = session_to_otlp(_forked_session())
    assert isinstance(doc, list)
    rs = doc[0]["resourceSpans"][0]
    assert "resource" in rs and "scopeSpans" in rs
    assert rs["scopeSpans"][0]["scope"]["name"] == "agent-bench"
    # round-trips as JSON (viewer ingests JSON)
    json.loads(json.dumps(doc))


def test_root_is_chain_phases_are_agents_rewards_are_evaluators():
    spans = _spans(session_to_otlp(_forked_session()))
    kinds = [_attrs(s)["openinference.span.kind"] for s in spans]
    assert kinds.count("CHAIN") == 1        # the session root
    assert kinds.count("AGENT") == 2        # two localize phases
    assert kinds.count("EVALUATOR") == 2    # one reward per phase

    root = next(s for s in spans if _attrs(s)["openinference.span.kind"] == "CHAIN")
    assert _attrs(root)["container.type"] == "task"
    assert "parentSpanId" not in root


def test_phase_spans_carry_config_and_link_to_root():
    spans = _spans(session_to_otlp(_forked_session()))
    root = next(s for s in spans if _attrs(s)["openinference.span.kind"] == "CHAIN")
    agents = [s for s in spans if _attrs(s)["openinference.span.kind"] == "AGENT"]
    for a in agents:
        at = _attrs(a)
        assert at["container.type"] == "objective"
        assert at["objective.type"] == "localize"
        assert "llm.model_name" in at
        assert a["parentSpanId"] == root["spanId"]   # fork = siblings under root
    models = {_attrs(a)["llm.model_name"] for a in agents}
    assert models == {"claude-haiku-4-5", "claude-sonnet-4-6"}


def test_reward_evaluator_carries_score_and_links_to_its_phase():
    spans = _spans(session_to_otlp(_forked_session()))
    evals = [s for s in spans if _attrs(s)["openinference.span.kind"] == "EVALUATOR"]
    by_score = {_attrs(e)["eval.score"]: e for e in evals}
    assert set(by_score) == {0.0, 1.0}
    agent_ids = {s["spanId"] for s in spans if _attrs(s)["openinference.span.kind"] == "AGENT"}
    for e in evals:
        assert _attrs(e)["reward.kind"] == "oracle"
        assert e["parentSpanId"] in agent_ids     # evaluator hangs off its phase

    # the winning phase preserved the real OTEL span id for cross-ref
    winner_eval = by_score[1.0]
    winner_phase = next(s for s in spans if s["spanId"] == winner_eval["parentSpanId"])
    assert _attrs(winner_phase)["agent_eval.otel.span_id"] == "bbbb0001"


def test_write_otlp_roundtrips(tmp_path):
    p = write_otlp(_forked_session(), tmp_path / "astropy-12907.json")
    doc = json.loads(p.read_text())
    assert _spans(doc)  # non-empty
