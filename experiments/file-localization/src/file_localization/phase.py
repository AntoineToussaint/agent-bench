"""Map a localization run onto the phase-trace control substrate.

This is the domain-specific glue between the localization trial and the
generic `SessionTrace` / `PhaseNode` types in `agent_eval.trace` (see
`lib/agent-eval-core/TRACE.md`). It does one thing: turn the result of one
localization run into a single-node `SessionTrace` (root = initial task state,
one `localize` child).

Why localization is the cheap first case (STRATEGY.md Step 1):
  - It is READ-ONLY — it reads files to find them, never mutates the repo. So
    the phase snapshot is just the conversation; `env_ref` is None and we need
    no container/git snapshot infra to checkpoint or fork it.
  - Its reward is verifiable but ORACLE-only: the localization score needs the
    gold patch, so it exists on SWE-bench, not in production. That's why
    `PhaseReward.kind="oracle"` here (the train/deploy split, made explicit).
"""

from __future__ import annotations

from agent_eval import PhaseConfig, PhaseReward, SessionTrace, Snapshot, Transcript

from file_localization.contract import LocalizationScore, LocalizationTask


def localization_session(
    *,
    task: LocalizationTask,
    model: str,
    prompt_id: str,
    context_strategy: str,
    backend: str,
    transcript: Transcript,
    score: LocalizationScore,
    submitted: list[str],
    span_id: str | None = None,
    trace_id: str | None = None,
    context_frames: int | None = None,
    context_omissions: int | None = None,
) -> SessionTrace:
    """Build a one-phase SessionTrace for a single localization run.

    The reward is `score.composite` — a continuous [0,1] signal (recall minus a
    false-positive penalty), which is what a contextual bandit over configs
    wants, rather than the binary `passed`. `passed` and the full breakdown ride
    along in `reward.detail`.
    """
    trace = SessionTrace(task_id=task.task_id)
    root = trace.start(Snapshot())  # initial task state, before localization

    config = PhaseConfig(
        model=model,
        # The protocol/backend is the closest thing we vary today to a
        # "prompt strategy" (the repo's headline finding is that protocol
        # dominates format/model), so it maps onto prompt_id; the raw name
        # is also kept in metadata. The literal prompt template is not yet a
        # varied axis.
        prompt_id=prompt_id,
        context_strategy=context_strategy,
    )
    reward = PhaseReward(
        value=score.composite,
        kind="oracle",
        detail={**score.as_extra(), "passed": score.passed, "submitted": list(submitted)},
    )
    trace.add(
        phase="localize",
        config=config,
        parent=root,
        snapshot=Snapshot.from_transcript(transcript, env_ref=None),  # read-only
        reward=reward,
        span_id=span_id,
        trace_id=trace_id,
        metadata={
            "backend": backend,
            "task_class": task.task_class,
            "condition": None,
            # Context-engineering signal (STRATEGY.md Step 2). None when the
            # caller didn't measure it; 0 means the policy elided nothing.
            "context_frames": context_frames,
            "context_omissions": context_omissions,
        },
    )
    return trace
