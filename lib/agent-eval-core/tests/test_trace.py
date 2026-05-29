"""SessionTrace / PhaseNode — the control-substrate interface (see TRACE.md).

These tests prove the interface end-to-end on the localization phase WITHOUT
calling a model: localization is read-only, so a phase's state is just its
conversation + an oracle reward, which we construct directly. That's the whole
point of starting with localization (STRATEGY.md Step 1) — the fork + per-phase
reward + serialize loop validates with zero snapshot infra and zero API spend.
"""

from __future__ import annotations

from agent_eval import (
    PhaseConfig,
    PhaseReward,
    SessionTrace,
    Snapshot,
    Transcript,
)


def _localize_transcript(model: str, submitted: list[str]) -> Transcript:
    """A minimal but real conversation for one localization run."""
    t = Transcript(system="You localize the files an issue needs edited.")
    t.add_user_text("Issue: AltAz frame transform raises on empty input.")
    # We don't need a full AssistantMessage to exercise the trace; the
    # conversation just has to round-trip. A submitted-files marker is enough.
    t.entries.append({"role": "assistant", "text": f"[{model}] done(files={submitted})"})
    return t


def _hit_reward(submitted: list[str], gold: list[str]) -> PhaseReward:
    """Localization reward = Hit@1-ish. ORACLE: needs the gold patch, so it
    exists on SWE-bench but not in production (TRACE.md / STRATEGY.md)."""
    hit = 1.0 if submitted and submitted[0] in gold else 0.0
    return PhaseReward(value=hit, kind="oracle", detail={"hit@1": hit, "submitted": submitted})


GOLD = ["astropy/coordinates/builtin_frames/altaz.py"]


def _build_forked_session() -> SessionTrace:
    """Run localization under two config bundles from the same start state,
    as siblings — the Step-2 bandit-arm comparison in miniature."""
    trace = SessionTrace(task_id="astropy-12907")
    root = trace.start(Snapshot())  # initial task state, before any phase

    # Arm A: cheap model, gets it wrong.
    cfg_a = PhaseConfig(model="claude-haiku-4-5", prompt_id="terse", context_strategy="keep_everything")
    sub_a = ["astropy/coordinates/sky_coordinate.py"]
    trace.add(
        phase="localize", config=cfg_a, parent=root,
        snapshot=Snapshot.from_transcript(_localize_transcript("haiku", sub_a), env_ref=None),
        reward=_hit_reward(sub_a, GOLD),
        span_id="aaaa0001", trace_id="trace0001",
    )

    # FORK from the same root: arm B, stronger model, gets it right.
    snap = trace.fork_from(root.id)
    assert snap.env_ref is None  # localization is read-only — no env to restore
    cfg_b = PhaseConfig(model="claude-sonnet-4-6", prompt_id="cot", context_strategy="tool_result_elision")
    sub_b = ["astropy/coordinates/builtin_frames/altaz.py"]
    trace.add(
        phase="localize", config=cfg_b, parent=root,
        snapshot=Snapshot.from_transcript(_localize_transcript("sonnet", sub_b), env_ref=None),
        reward=_hit_reward(sub_b, GOLD),
        span_id="bbbb0001", trace_id="trace0001",
    )
    return trace


def test_fork_creates_siblings_under_one_parent():
    trace = _build_forked_session()
    root_id = trace.root_id
    children = trace.children_of(root_id)
    assert len(children) == 2
    assert all(c.parent_id == root_id for c in children)
    # Two localization arms, two leaves, no chaining.
    assert len(trace.leaves()) == 2
    assert len(trace.phase_nodes("localize")) == 2


def test_per_phase_reward_picks_the_winning_arm():
    trace = _build_forked_session()
    best = trace.best_leaf("localize")
    assert best is not None
    assert best.config.model == "claude-sonnet-4-6"
    assert best.reward.value == 1.0
    assert best.reward.kind == "oracle"  # the train/deploy split is in the type
    # And the arm identity is what a bandit would key on.
    assert best.config.as_arm() == ("claude-sonnet-4-6", "cot", "tool_result_elision")


def test_localization_env_ref_is_none():
    """Read-only phase => no environment snapshot. The cheap-first claim."""
    trace = _build_forked_session()
    for n in trace.phase_nodes("localize"):
        assert n.snapshot.env_ref is None
        assert n.snapshot.conversation is not None  # but conversation IS captured


def test_jsonl_roundtrip_preserves_tree_and_rewards(tmp_path):
    trace = _build_forked_session()
    path = trace.to_jsonl(tmp_path / "session.jsonl")
    loaded = SessionTrace.from_jsonl(path)

    assert loaded.task_id == trace.task_id
    assert loaded.root_id == trace.root_id
    assert len(loaded) == len(trace)
    # Tree shape survives.
    assert len(loaded.children_of(loaded.root_id)) == 2
    # Reward + config + conversation survive.
    best = loaded.best_leaf("localize")
    assert best.reward.value == 1.0
    assert best.reward.detail["hit@1"] == 1.0
    assert best.config.context_strategy == "tool_result_elision"
    assert best.snapshot.conversation.entries[-1]["text"].startswith("[sonnet]")
    assert best.span_id == "bbbb0001"


def test_append_only_jsonl_shape(tmp_path):
    """Line 0 is the session header; each subsequent line is one node — so a
    fork is an appended line (the Claude-Code / OTEL-exporter shape)."""
    trace = _build_forked_session()
    path = trace.to_jsonl(tmp_path / "s.jsonl")
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    import json

    header = json.loads(lines[0])
    assert header["_session"] is True
    assert header["task_id"] == "astropy-12907"
    # root + 2 localize nodes = 3 node lines after the header.
    assert len(lines) == 1 + 3


def test_fork_from_unknown_node_raises():
    trace = SessionTrace(task_id="t")
    root = trace.start()
    import pytest

    with pytest.raises(KeyError):
        trace.add(phase="localize", config=PhaseConfig(model="m"), parent="nonexistent")
    # forking the real root is fine
    assert trace.fork_from(root.id) is not None
