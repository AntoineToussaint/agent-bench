"""Session trace: the control substrate for phase-segmented agents.

See `TRACE.md` for the design + the SOTA that motivates it. Short version:
OpenTelemetry spans (see `tracing.py`) are the *observability* layer — great
for a timeline, but a span is immutable, point-in-time, and models one
execution's causality. They cannot carry a mutable post-hoc reward, a
restorable state snapshot, or a *branch* into alternative executions.

This module is the missing *control* object. It models a run as a tree of
`PhaseNode`s:

  - **Fork** = N children sharing one `parent_id`. That's the bandit/RL
    primitive (Step 2/3 of `STRATEGY.md`): snapshot after a phase, re-run the
    next phase under N different configs from the same state.
  - **Two state planes**, joined at the node and kept as separate refs because
    their cost/lifetime differ by orders of magnitude:
        conversation (cheap, JSON, fork-by-copy) — `Snapshot.conversation`
        environment  (expensive: git SHA / container snapshot) — `Snapshot.env_ref`
    Localization is read-only, so its `env_ref` is None: the whole loop
    validates on a serialized conversation with no snapshot infra.
  - **Reward** attaches at the node, tagged `oracle` (gold-label, benchmark
    only) vs `prod` (available at deploy time, e.g. tests pass). This is the
    train/deploy split from `STRATEGY.md` made part of the type.

It emits/links to OTEL: every node carries `span_id` / `trace_id`, so a row in
Honeycomb/Langfuse still points at the checkpoint that produced it.

Persistence is append-only JSONL (line 0 = session meta, then one line per
node) — the same shape as the OTEL exporter and Claude Code's session logs, so
a fork is literally an appended line.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from agent_eval.types import Transcript

# The canonical phase schema for a coding agent. Kept as plain strings (not an
# enum) on purpose — the schema is still a research question (`STRATEGY.md`
# Decision B), so callers may use other tags. These are the documented ones.
CANONICAL_PHASES = ("localize", "repair", "test", "verify")

RewardKind = Literal["oracle", "prod"]


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass
class PhaseConfig:
    """What produced a phase — the action space the bandit/RL learns over.

    The novelty (see `PLATFORM.md`) is that this is a *bundle*: model AND
    prompt AND context-strategy, varied together, because their interaction is
    the point. Do not factorize the axes away.
    """

    model: str
    prompt_id: str = "default"
    context_strategy: str = "keep_everything"

    def as_arm(self) -> tuple[str, str, str]:
        """Hashable identity for bandit bookkeeping."""
        return (self.model, self.prompt_id, self.context_strategy)


@dataclass
class PhaseReward:
    """A verifiable score for one phase.

    `kind` is load-bearing, not decoration:
      - "oracle": needs a gold label (localization Hit@k, test-quality-vs-gold).
        Exists on benchmarks, NOT at deploy time. Train-time signal only.
      - "prod": available in production (e.g. the tests actually pass).
    `detail` carries the breakdown, e.g. {"hit@1": .., "mrr": ..} or
    {"tests_passed": .., "tests_total": ..}.
    """

    value: float
    kind: RewardKind
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Snapshot:
    """Restorable state at a phase boundary — the two planes.

    conversation: the message log, inline (cheap; small for localization).
        Stored as `Transcript`-shaped data so it round-trips losslessly. Large
        conversations should move to by-reference storage later (the MLflow
        attachment pattern in `TRACE.md`); inline is the cheap-first choice.
    env_ref: opaque handle to environment state — a git SHA, stash ref, or
        container/VM snapshot id. None for read-only phases (localization).
    """

    conversation: Transcript | None = None
    env_ref: str | None = None

    @classmethod
    def from_transcript(cls, transcript: Transcript, env_ref: str | None = None) -> "Snapshot":
        return cls(conversation=transcript, env_ref=env_ref)

    def to_dict(self) -> dict[str, Any]:
        conv = None
        if self.conversation is not None:
            conv = {"system": self.conversation.system, "entries": self.conversation.entries}
        return {"conversation": conv, "env_ref": self.env_ref}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Snapshot":
        if not d:
            return cls()
        conv = None
        if d.get("conversation"):
            conv = Transcript(
                system=d["conversation"]["system"],
                entries=list(d["conversation"].get("entries", [])),
            )
        return cls(conversation=conv, env_ref=d.get("env_ref"))


@dataclass
class PhaseNode:
    """One completed phase. A node in the session tree.

    `parent_id` is the fork edge: siblings sharing a parent are alternative
    continuations from the same `snapshot`. The root node (parent_id=None)
    represents the task's initial state, before any phase runs.
    """

    phase: str
    config: PhaseConfig
    id: str = field(default_factory=_new_id)
    parent_id: str | None = None
    snapshot: Snapshot = field(default_factory=Snapshot)
    reward: PhaseReward | None = None
    # Links into the OTEL observability trace (see tracing.py).
    span_id: str | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "phase": self.phase,
            "config": asdict(self.config),
            "snapshot": self.snapshot.to_dict(),
            "reward": asdict(self.reward) if self.reward else None,
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PhaseNode":
        reward = None
        if d.get("reward"):
            reward = PhaseReward(
                value=d["reward"]["value"],
                kind=d["reward"]["kind"],
                detail=d["reward"].get("detail", {}),
            )
        return cls(
            id=d["id"],
            parent_id=d.get("parent_id"),
            phase=d["phase"],
            config=PhaseConfig(**d["config"]),
            snapshot=Snapshot.from_dict(d.get("snapshot")),
            reward=reward,
            span_id=d.get("span_id"),
            trace_id=d.get("trace_id"),
            metadata=d.get("metadata", {}),
        )


class SessionTrace:
    """A tree of PhaseNodes for one task.

    Usage (record-keeping is here; *execution* is the caller's job — that
    separation is the whole point, see TRACE.md):

        trace = SessionTrace(task_id="astropy-12907")
        root = trace.start(Snapshot())                       # initial task state
        # run localization under config A from root's snapshot ...
        a = trace.add(phase="localize", config=cfg_a, parent=root,
                      snapshot=snap_after_a, reward=reward_a)
        # FORK: re-run localization under config B from the SAME parent ...
        snap = trace.fork_from(root.id)                      # what to restore
        b = trace.add(phase="localize", config=cfg_b, parent=root,
                      snapshot=snap_after_b, reward=reward_b)
        trace.best_leaf("localize")                          # -> b if reward_b > reward_a
    """

    def __init__(self, task_id: str, root_id: str | None = None) -> None:
        self.task_id = task_id
        self._nodes: dict[str, PhaseNode] = {}
        self._order: list[str] = []
        self.root_id = root_id

    # ---- building ----

    def start(self, snapshot: Snapshot | None = None, *, config: PhaseConfig | None = None) -> PhaseNode:
        """Create the root node (initial task state, before any phase runs)."""
        if self.root_id is not None:
            raise ValueError("session already has a root")
        node = PhaseNode(
            phase="__root__",
            config=config or PhaseConfig(model="none"),
            snapshot=snapshot or Snapshot(),
        )
        self.root_id = node.id
        self._insert(node)
        return node

    def add(
        self,
        *,
        phase: str,
        config: PhaseConfig,
        parent: PhaseNode | str,
        snapshot: Snapshot | None = None,
        reward: PhaseReward | None = None,
        span_id: str | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PhaseNode:
        parent_id = parent.id if isinstance(parent, PhaseNode) else parent
        if parent_id not in self._nodes:
            raise KeyError(f"unknown parent {parent_id!r}")
        node = PhaseNode(
            phase=phase,
            config=config,
            parent_id=parent_id,
            snapshot=snapshot or Snapshot(),
            reward=reward,
            span_id=span_id,
            trace_id=trace_id,
            metadata=metadata or {},
        )
        self._insert(node)
        return node

    def fork_from(self, node_id: str) -> Snapshot:
        """The state to restore to branch from `node_id`.

        Returns the node's end-state snapshot; the caller restores it (the
        conversation, and the env via `env_ref`) and re-runs the next phase
        under a new config, then records the result with `add(parent=node_id)`.
        """
        return self._nodes[node_id].snapshot

    def _insert(self, node: PhaseNode) -> None:
        if node.id in self._nodes:
            raise ValueError(f"duplicate node id {node.id!r}")
        self._nodes[node.id] = node
        self._order.append(node.id)

    # ---- querying ----

    def __len__(self) -> int:
        return len(self._nodes)

    def __iter__(self) -> Iterator[PhaseNode]:
        return (self._nodes[i] for i in self._order)

    def get(self, node_id: str) -> PhaseNode:
        return self._nodes[node_id]

    def children_of(self, node_id: str) -> list[PhaseNode]:
        return [n for n in self if n.parent_id == node_id]

    def phase_nodes(self, phase: str) -> list[PhaseNode]:
        return [n for n in self if n.phase == phase]

    def leaves(self) -> list[PhaseNode]:
        parents = {n.parent_id for n in self if n.parent_id is not None}
        return [n for n in self if n.id not in parents and n.phase != "__root__"]

    def best_leaf(
        self, phase: str | None = None, *, key: Callable[[PhaseNode], float] | None = None
    ) -> PhaseNode | None:
        """Highest-reward node (optionally restricted to one phase).

        Default key is the reward value; nodes without a reward are skipped.
        This is the bandit's "which arm won" query in miniature.
        """
        if key is None:
            key = lambda n: n.reward.value if n.reward else float("-inf")  # noqa: E731
        candidates = [
            n for n in (self.phase_nodes(phase) if phase else list(self))
            if n.phase != "__root__" and (n.reward is not None or key is not None)
        ]
        scored = [n for n in candidates if key(n) != float("-inf")]
        return max(scored, key=key) if scored else None

    # ---- persistence (append-only JSONL) ----

    def to_jsonl(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as fh:
            fh.write(json.dumps({"_session": True, "task_id": self.task_id, "root_id": self.root_id}) + "\n")
            for node in self:
                fh.write(json.dumps(node.to_dict()) + "\n")
        return path

    @classmethod
    def from_jsonl(cls, path: Path | str) -> "SessionTrace":
        path = Path(path)
        with open(path) as fh:
            lines = [line for line in fh if line.strip()]
        meta = json.loads(lines[0])
        if not meta.get("_session"):
            raise ValueError(f"{path} is not a SessionTrace JSONL (missing _session header)")
        trace = cls(task_id=meta["task_id"], root_id=meta.get("root_id"))
        for line in lines[1:]:
            node = PhaseNode.from_dict(json.loads(line))
            trace._insert(node)
        return trace
