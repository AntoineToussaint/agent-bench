"""load_verified_enrichment + is_clean (quality-flag filter). No network.

Also a light schema check against the committed real CSV when it's present, so
a malformed regeneration is caught."""

from __future__ import annotations

from pathlib import Path

from file_localization.difficulty import is_clean, load_verified_enrichment

_REAL_CSV = (
    Path(__file__).resolve().parents[3]
    / "lib/agent-eval-core/data/swebench_verified_enrichment.csv"
)


def test_load_and_coerce(tmp_path):
    p = tmp_path / "enr.csv"
    p.write_text(
        "instance_id,difficulty,underspecified,false_negative,other_major_issues,"
        "ref_solve_rate,ref_cost_avg,cost_gpt5,calls_gpt5,resolved_gpt5\n"
        "a__a-1,1-4 hours,0.0,2.0,0.0,0.25,0.83,0.85,25,0\n"
        "a__a-2,<15 min fix,1.0,0.0,0.0,1.0,0.10,,,\n"
    )
    enr = load_verified_enrichment(p)
    assert set(enr) == {"a__a-1", "a__a-2"}
    r1 = enr["a__a-1"]
    assert r1["difficulty"] == "1-4 hours"          # bucket stays a string
    assert r1["false_negative"] == 2                # int-coerced
    assert r1["ref_cost_avg"] == 0.83               # float-coerced
    assert r1["calls_gpt5"] == 25
    assert enr["a__a-2"]["cost_gpt5"] is None        # blank -> None


def test_is_clean_filters_contamination_flags(tmp_path):
    # Annotation columns are binary 0/1 majority votes (matches the real CSV).
    p = tmp_path / "enr.csv"
    p.write_text(
        "instance_id,difficulty,underspecified,false_negative,other_major_issues\n"
        "clean,1-4 hours,0.0,0.0,0.0\n"          # no flags -> clean
        "fn_flagged,1-4 hours,0.0,1.0,0.0\n"     # false_negative -> drop
        "omi_flagged,1-4 hours,0.0,0.0,1.0\n"    # other_major_issues -> drop
        "us_only,1-4 hours,1.0,0.0,0.0\n"        # underspecified is NOT contamination -> clean
    )
    enr = load_verified_enrichment(p)
    assert is_clean(enr["clean"]) is True
    assert is_clean(enr["fn_flagged"]) is False
    assert is_clean(enr["omi_flagged"]) is False
    assert is_clean(enr["us_only"]) is True


def test_committed_csv_schema_if_present():
    if not _REAL_CSV.exists():
        return  # generated artifact; skip when absent
    enr = load_verified_enrichment(_REAL_CSV)
    assert len(enr) == 500
    buckets = {row["difficulty"] for row in enr.values()}
    assert buckets <= {"<15 min fix", "15 min - 1 hour", "1-4 hours", ">4 hours"}
    # every row has the ref cost columns
    sample = next(iter(enr.values()))
    for col in ("ref_solve_rate", "ref_cost_avg", "cost_sonnet45"):
        assert col in sample
