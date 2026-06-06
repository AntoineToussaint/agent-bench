"""Load SWE-bench tasks by difficulty band (focus: SWE-bench Verified).

Glue between the generic difficulty interface (`agent_eval.difficulty`) and the
SWE-bench adapter. For Verified the difficulty signal comes from a CSV produced
by `scripts/build_verified_difficulty.py` (model-solvability: fraction of 4
strong reference models that solved each task, tie-broken by cost/calls/human
time — see SOURCES.md for why the old leaderboard pass-rate was dropped). This
module turns "give me N hard Verified tasks" into a list of LocalizationTask.

Typical use (STRATEGY.md Decision D — get off the saturated easy band):

    from file_localization.difficulty import load_swebench_band
    tasks = load_swebench_band(
        "hard", n=20,
        csv_path="lib/agent-eval-core/data/swebench_verified_difficulty.csv",
    )

Generate the CSV first (one-time, no network — derives from the enrichment CSV):

    uv run --package file-localization python \\
        experiments/file-localization/scripts/build_verified_difficulty.py
"""

from __future__ import annotations

from pathlib import Path

from agent_eval.difficulty import Band, CsvDifficultySource, sample_band

from file_localization.adapters import load_swebench, to_localization_tasks
from file_localization.contract import LocalizationTask


def band_instance_ids(
    csv_path: Path | str,
    band: Band,
    n: int | None = None,
    *,
    seed: int = 0,
    hard_max: float = 0.25,
    medium_max: float = 0.75,
) -> list[str]:
    """Instance ids in `band` from the difficulty CSV (pure; no dataset load)."""
    recs = CsvDifficultySource(csv_path).records()
    picked = sample_band(recs, band, n, seed=seed, hard_max=hard_max, medium_max=medium_max)
    return [r.task_id for r in picked]


def load_swebench_band(
    band: Band,
    *,
    csv_path: Path | str,
    dataset: str = "verified",
    split: str = "test",
    n: int | None = None,
    seed: int = 0,
    hard_max: float = 0.25,
    medium_max: float = 0.75,
) -> list[LocalizationTask]:
    """Return LocalizationTasks for `dataset` whose difficulty falls in `band`.

    `band` ∈ {"unsolved","hard","medium","easy"}. The difficulty CSV's ids must
    match the dataset's `instance_id`s (they do for SWE-bench Verified). Tasks
    are returned in the dataset's order, restricted to the sampled ids.
    """
    wanted = set(
        band_instance_ids(
            csv_path, band, n, seed=seed, hard_max=hard_max, medium_max=medium_max
        )
    )
    raw = [r for r in load_swebench(dataset, split=split) if r.instance_id in wanted]
    return to_localization_tasks(raw)


def load_verified_enrichment(
    csv_path: Path | str,
) -> dict[str, dict]:
    """Read the SWE-bench Verified enrichment CSV (built by
    `scripts/build_verified_enrichment.py`) into instance_id -> row.

    Numeric cells are parsed to float/int where possible; blanks become None.
    Columns: difficulty (str bucket), underspecified / false_negative /
    other_major_issues (0-3 severity), ref_solve_rate, ref_cost_avg, and per
    reference model cost_/calls_/resolved_.
    """
    import csv as _csv

    def _coerce(v: str):
        if v == "" or v is None:
            return None
        try:
            f = float(v)
            return int(f) if f.is_integer() else f
        except ValueError:
            return v

    out: dict[str, dict] = {}
    with open(csv_path, newline="") as fh:
        for row in _csv.DictReader(fh):
            iid = row.pop("instance_id")
            # difficulty stays a string bucket; everything else coerces.
            parsed = {"difficulty": row.get("difficulty", "")}
            for k, v in row.items():
                if k == "difficulty":
                    continue
                parsed[k] = _coerce(v)
            out[iid] = parsed
    return out


# Annotation flags that make a task's resolved/pass signal untrustworthy.
# `underspecified` is intentionally NOT here — see is_clean docstring.
_CONTAMINATION_FLAGS = ("false_negative", "other_major_issues")


def is_clean(enrichment_row: dict, *, flag_threshold: float = 1.0) -> bool:
    """True if a task's pass/fail signal is NOT suspect.

    The enrichment copies OpenAI's ensembled annotations verbatim, and those
    columns are **binary 0/1 majority votes** (not 0-3 severities — every value
    in the committed CSV is 0.0 or 1.0). Drops instances flagged
    `false_negative` (gold tests fail incorrectly) or `other_major_issues` —
    these corrupt the resolved/pass signal. `underspecified` is left clean on
    purpose: an ambiguous spec is intrinsic *difficulty* (a model that can't
    infer the intended fix is legitimately harder), not contamination.

    NOTE: the previous default threshold of 2.0 never fired against the binary
    data, so is_clean silently passed every task — this fixes that.
    """
    for flag in _CONTAMINATION_FLAGS:
        v = enrichment_row.get(flag)
        if isinstance(v, (int, float)) and v >= flag_threshold:
            return False
    return True


__all__ = [
    "band_instance_ids",
    "is_clean",
    "load_swebench_band",
    "load_verified_enrichment",
]
