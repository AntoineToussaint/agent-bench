"""Oracle tests for c01_localized_bug / small."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def test_is_adult_at_threshold() -> None:
    import age

    assert age.is_adult(18) is True


def test_is_adult_below_threshold() -> None:
    import age

    assert age.is_adult(17) is False


def test_is_adult_above_threshold() -> None:
    import age

    assert age.is_adult(40) is True


def test_unrelated_functions_untouched() -> None:
    src = (ROOT / "age.py").read_text(encoding="utf-8")
    # The senior and minor predicates must remain byte-for-byte unchanged.
    assert "def is_senior(age):\n    return age >= 65\n" in src
    assert "def is_minor(age):\n    return age < LEGAL_AGE\n" in src


def test_legal_age_constant_unchanged() -> None:
    import age

    assert age.LEGAL_AGE == 18
