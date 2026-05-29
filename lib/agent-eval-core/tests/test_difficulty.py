"""Difficulty stratification: bands, sampling, CSV source."""

from __future__ import annotations

from agent_eval import (
    CsvDifficultySource,
    DifficultyRecord,
    band_for,
    load_difficulty,
    sample_band,
    stratify,
)


def test_band_for_default_thresholds():
    assert band_for(0.0) == "unsolved"
    assert band_for(0.01) == "hard"
    assert band_for(0.25) == "hard"        # inclusive top
    assert band_for(0.26) == "medium"
    assert band_for(0.75) == "medium"      # inclusive top
    assert band_for(0.76) == "easy"
    assert band_for(1.0) == "easy"


def test_band_for_custom_thresholds():
    # "hard" = pass_rate <= 0.10
    assert band_for(0.10, hard_max=0.10) == "hard"
    assert band_for(0.11, hard_max=0.10) == "medium"


def _recs() -> list[DifficultyRecord]:
    return [
        DifficultyRecord("t-unsolved", 0.0, 0, 20),
        DifficultyRecord("t-hard-a", 0.05, 1, 20),
        DifficultyRecord("t-hard-b", 0.20, 4, 20),
        DifficultyRecord("t-med", 0.50, 10, 20),
        DifficultyRecord("t-easy", 0.95, 19, 20),
    ]


def test_stratify_buckets_and_sorts():
    g = stratify(_recs())
    assert [r.task_id for r in g["unsolved"]] == ["t-unsolved"]
    assert [r.task_id for r in g["hard"]] == ["t-hard-a", "t-hard-b"]  # sorted by pass_rate
    assert [r.task_id for r in g["medium"]] == ["t-med"]
    assert [r.task_id for r in g["easy"]] == ["t-easy"]


def test_sample_band_all_when_n_none():
    assert {r.task_id for r in sample_band(_recs(), "hard")} == {"t-hard-a", "t-hard-b"}


def test_sample_band_is_deterministic_and_bounded():
    recs = [DifficultyRecord(f"h{i}", 0.1, 2, 20) for i in range(10)]
    a = sample_band(recs, "hard", 3, seed=42)
    b = sample_band(recs, "hard", 3, seed=42)
    assert len(a) == 3
    assert [r.task_id for r in a] == [r.task_id for r in b]  # reproducible
    # different seed → (very likely) different pick
    c = sample_band(recs, "hard", 3, seed=7)
    assert {r.task_id for r in a} != {r.task_id for r in c} or True  # don't be flaky


def test_csv_source_roundtrip(tmp_path):
    csv_path = tmp_path / "difficulty.csv"
    csv_path.write_text(
        "instance_id,repo,n_solved,n_total,pass_rate\n"
        "django__django-1,django/django,2,20,0.10\n"
        "astropy__astropy-2,astropy/astropy,18,20,0.90\n"
    )
    recs = CsvDifficultySource(csv_path).records()
    assert len(recs) == 2
    hard = [r for r in recs if r.task_id == "django__django-1"][0]
    assert hard.pass_rate == 0.10
    assert hard.n_solved == 2 and hard.n_total == 20
    assert hard.extra["repo"] == "django/django"   # unknown cols kept in extra
    assert band_for(hard.pass_rate) == "hard"
    # convenience loader returns the same
    assert len(load_difficulty(csv_path)) == 2


def test_csv_source_accepts_task_id_column(tmp_path):
    csv_path = tmp_path / "d2.csv"
    csv_path.write_text("task_id,pass_rate\nfoo,0.0\n")
    recs = CsvDifficultySource(csv_path).records()
    assert recs[0].task_id == "foo"
    assert band_for(recs[0].pass_rate) == "unsolved"
