"""LessonStore: cross-episode persistence of distilled tool-failure lessons.

Two indexes:
  - per_tool_lessons   keyed by tool name (e.g. 'git_push') — injected in phase 2
  - per_task_lessons   keyed by task pattern signature — injected in phase 1
                       (or in 1phase as part of the system prompt)

Lessons are stored as a JSONL file so they persist across runs of the
experiment script. The store also tracks utility (fires / prevented) so
future consolidation passes can evict low-value lessons.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Lesson:
    """One learned rule, distilled from a past failure."""

    id: str
    text: str
    """Concise rule the model can act on, e.g. 'When pushing a new branch for "
    "the first time, set set_upstream=True.'"""

    category: str
    """schema-invalid | wrong-state | wrong-content | transient (from FailureTrigger)."""

    scope: str  # 'tool' or 'task'
    """Where this lesson is indexed. 'tool' → per_tool_lessons, 'task' → per_task_lessons."""

    key: str
    """The index key — tool name for scope='tool', task_signature for scope='task'."""

    created_at: float = field(default_factory=time.time)
    fires: int = 0
    """How many times this lesson has been injected into a prompt."""

    prevented_failure: int = 0
    """How many times this lesson was injected AND the corresponding failure mode
    did NOT recur on that attempt. Used for utility-based eviction."""

    source_error: str = ""
    """The original error text that triggered the lesson — for debugging."""

    @property
    def utility(self) -> float:
        """Smoothed prevented/fires ratio. New lessons get neutral priors."""
        # Laplace smoothing: 1 success + 1 failure prior
        return (self.prevented_failure + 1) / (self.fires + 2)


@dataclass
class LessonStore:
    """Append-only persistent store with per-tool and per-task indices.

    Persistence is via JSONL: one Lesson per line. Each store instance is
    pinned to one path; calling save() flushes the current state.

    NOT thread-safe; meant for single-process experiment runs.
    """

    path: Path
    lessons: list[Lesson] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "LessonStore":
        store = cls(path=Path(path))
        if store.path.exists():
            with store.path.open() as f:
                for line in f:
                    raw = json.loads(line)
                    store.lessons.append(Lesson(**raw))
        return store

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w") as f:
            for l in self.lessons:
                f.write(json.dumps(asdict(l)) + "\n")

    def add(self, lesson: Lesson) -> None:
        # Dedupe by text within the same (scope, key). Skip if already present.
        for existing in self.lessons:
            if (
                existing.scope == lesson.scope
                and existing.key == lesson.key
                and existing.text == lesson.text
            ):
                return
        self.lessons.append(lesson)

    def for_tool(self, tool_name: str, top_k: int = 3) -> list[Lesson]:
        """Lessons indexed against a specific tool name, ordered by utility."""
        matched = [l for l in self.lessons if l.scope == "tool" and l.key == tool_name]
        matched.sort(key=lambda l: -l.utility)
        return matched[:top_k]

    def for_task(self, task_signature: str, top_k: int = 5) -> list[Lesson]:
        matched = [l for l in self.lessons if l.scope == "task" and l.key == task_signature]
        matched.sort(key=lambda l: -l.utility)
        return matched[:top_k]

    def all_for_tools(self, tool_names: list[str], top_k_per_tool: int = 3) -> list[Lesson]:
        """All lessons for any of the given tool names. Used by 1phase variants
        that want all relevant tool-level lessons in one prompt."""
        out: list[Lesson] = []
        for name in tool_names:
            out.extend(self.for_tool(name, top_k=top_k_per_tool))
        return out

    def __len__(self) -> int:
        return len(self.lessons)


def task_signature(task) -> str:
    """A coarse signature for a task — used as key for per-task lessons.

    Uses the first few words of the prompt as a proxy for 'task family'.
    This is intentionally lossy: a lesson learned on M2 should apply to
    other 'create branch and push' tasks like H1/H3, not only M2.

    For a stronger signature you'd embed the prompt; v1 keeps it cheap.
    """
    words = task.prompt.lower().split()[:6]
    return " ".join(words)
