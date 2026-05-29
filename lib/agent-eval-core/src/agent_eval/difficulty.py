"""Dataset difficulty stratification — find the easy/medium/hard tasks.

Domain-agnostic. A difficulty signal is just a per-task `pass_rate` in [0, 1]
(the fraction of reference solvers that solved it) plus the raw counts. From
that we derive a `Band` and can sample a band for a sweep.

Why this exists: STRATEGY.md Decision D — our first ablations saturated at 100%
pass because the task set was too easy to differentiate configs. To get signal
we need the *hard* band (low pass-rate). This module turns "give me 20 hard
SWE-bench tasks" into one call, given a difficulty CSV.

The difficulty CSV is produced by an experiment-side scraper (for SWE-bench:
`scripts/swebench_difficulty.py`, which aggregates the leaderboard). This module
doesn't care where the numbers come from — any `DifficultySource` works.

Bands (default thresholds, on pass_rate):
    unsolved : pass_rate == 0        (no reference solver got it)
    hard     : 0 < pass_rate <= 0.25 (the band Decision D wants)
    medium   : 0.25 < pass_rate <= 0.75
    easy     : pass_rate > 0.75
Thresholds are parameters everywhere, so "hard = <=0.10" is a kwarg away.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Protocol

Band = Literal["unsolved", "hard", "medium", "easy"]
BANDS: tuple[Band, ...] = ("unsolved", "hard", "medium", "easy")


@dataclass(frozen=True)
class DifficultyRecord:
    """One task's difficulty signal."""

    task_id: str
    pass_rate: float           # fraction of reference solvers that solved it
    n_solved: int = 0
    n_total: int = 0
    extra: dict[str, Any] = field(default_factory=dict)  # e.g. {"repo": ...}


def band_for(
    pass_rate: float,
    *,
    hard_max: float = 0.25,
    medium_max: float = 0.75,
) -> Band:
    """Bucket a pass_rate into a difficulty band.

    Boundaries are inclusive at the top of each band:
    unsolved iff pass_rate <= 0, then hard <= hard_max, medium <= medium_max,
    else easy.
    """
    if pass_rate <= 0.0:
        return "unsolved"
    if pass_rate <= hard_max:
        return "hard"
    if pass_rate <= medium_max:
        return "medium"
    return "easy"


def stratify(
    records: Iterable[DifficultyRecord],
    *,
    hard_max: float = 0.25,
    medium_max: float = 0.75,
) -> dict[Band, list[DifficultyRecord]]:
    """Group records by band (each band's list sorted by pass_rate ascending)."""
    out: dict[Band, list[DifficultyRecord]] = {b: [] for b in BANDS}
    for r in records:
        out[band_for(r.pass_rate, hard_max=hard_max, medium_max=medium_max)].append(r)
    for b in out:
        out[b].sort(key=lambda r: (r.pass_rate, r.task_id))
    return out


def sample_band(
    records: Iterable[DifficultyRecord],
    band: Band,
    n: int | None = None,
    *,
    seed: int = 0,
    hard_max: float = 0.25,
    medium_max: float = 0.75,
) -> list[DifficultyRecord]:
    """Return up to `n` records in `band`, deterministically (seeded shuffle).

    n=None returns all of them (sorted by pass_rate ascending). With n set, the
    selection is a seeded random sample so repeated sweeps cover the band
    without always picking the same hardest few — but it's reproducible.
    """
    pool = stratify(records, hard_max=hard_max, medium_max=medium_max)[band]
    if n is None or n >= len(pool):
        return pool
    rng = random.Random(seed)
    picked = rng.sample(pool, n)
    picked.sort(key=lambda r: (r.pass_rate, r.task_id))
    return picked


class DifficultySource(Protocol):
    """Anything that can produce difficulty records for a dataset."""

    def records(self) -> list[DifficultyRecord]: ...


@dataclass
class CsvDifficultySource:
    """Difficulty records from a CSV (the shape `swebench_difficulty.py` writes).

    Expected columns: `task_id` (or `instance_id`), `pass_rate`, and optionally
    `n_solved` / `n_total`. Any other columns are kept in `extra`.
    """

    path: Path | str
    id_col: str = "instance_id"
    rate_col: str = "pass_rate"
    solved_col: str = "n_solved"
    total_col: str = "n_total"

    def records(self) -> list[DifficultyRecord]:
        out: list[DifficultyRecord] = []
        with open(self.path, newline="") as fh:
            reader = csv.DictReader(fh)
            # Tolerate either `task_id` or `instance_id` as the id column.
            fields = reader.fieldnames or []
            id_col = self.id_col if self.id_col in fields else (
                "task_id" if "task_id" in fields else self.id_col
            )
            known = {id_col, self.rate_col, self.solved_col, self.total_col}
            for row in reader:
                extra = {k: v for k, v in row.items() if k not in known}
                out.append(
                    DifficultyRecord(
                        task_id=row[id_col],
                        pass_rate=float(row[self.rate_col]),
                        n_solved=int(row.get(self.solved_col, 0) or 0),
                        n_total=int(row.get(self.total_col, 0) or 0),
                        extra=extra,
                    )
                )
        return out


def load_difficulty(path: Path | str, **kwargs: Any) -> list[DifficultyRecord]:
    """Convenience: read a difficulty CSV into records."""
    return CsvDifficultySource(path, **kwargs).records()


__all__ = [
    "BANDS",
    "Band",
    "CsvDifficultySource",
    "DifficultyRecord",
    "DifficultySource",
    "band_for",
    "load_difficulty",
    "sample_band",
    "stratify",
]
