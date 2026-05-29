"""Failure taxonomy tree + localization sub-classifier."""

from __future__ import annotations

from agent_eval import TAXONOMY, category_of, classify_localization, taxonomy_path
from agent_eval.failure_modes import FailureMode
import typing


def test_every_taxonomy_leaf_is_a_declared_failure_mode():
    declared = set(typing.get_args(FailureMode))
    for cat, leaves in TAXONOMY.items():
        for mode in leaves:
            assert mode in declared, f"{mode} in TAXONOMY[{cat}] but not in FailureMode"


def test_category_lookups():
    assert category_of("localization_missing") == "localization"
    assert category_of("format_anchoring") == "protocol"
    assert category_of("oracle_failed") == "code_editing"
    assert category_of("context_amnesia") == "memory"
    assert category_of("does_not_exist") is None
    assert taxonomy_path("step_repetition") == ("process", "step_repetition")
    assert taxonomy_path("nope") is None


def test_no_mode_in_two_categories():
    seen: dict[str, str] = {}
    for cat, leaves in TAXONOMY.items():
        for mode in leaves:
            assert mode not in seen, f"{mode} in both {seen.get(mode)} and {cat}"
            seen[mode] = cat


GOLD = {"src/a.py", "src/b.py"}


def test_localization_clean_returns_none():
    assert classify_localization(["src/a.py", "src/b.py"], GOLD) is None


def test_localization_irrelevant_zero_hits():
    assert classify_localization(["src/x.py", "src/y.py"], GOLD) == "localization_irrelevant"


def test_localization_missing_partial_hits():
    # found a.py, missed b.py
    assert classify_localization(["src/a.py"], GOLD) == "localization_missing"
    # a hit plus a wrong one, still missing b.py → missing (not irrelevant)
    assert classify_localization(["src/a.py", "src/z.py"], GOLD) == "localization_missing"


def test_localization_too_many_precision_failure():
    # all gold found (recall=1) but 3 false positives > 1.0 * |gold|(=2) → too_many
    preds = ["src/a.py", "src/b.py", "fp1.py", "fp2.py", "fp3.py"]
    assert classify_localization(preds, GOLD) == "localization_too_many"
    # found all gold with 2 FPs (== |gold|), not over the ratio → clean
    assert classify_localization(["src/a.py", "src/b.py", "fp1.py", "fp2.py"], GOLD) is None


def test_localization_too_many_threshold_is_tunable():
    preds = ["src/a.py", "src/b.py", "fp1.py"]   # 1 FP, ratio 0.5
    assert classify_localization(preds, GOLD) is None
    assert classify_localization(preds, GOLD, too_many_fp_ratio=0.4) == "localization_too_many"
