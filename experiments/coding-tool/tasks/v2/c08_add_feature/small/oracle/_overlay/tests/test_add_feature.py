"""Oracle tests for c08_add_feature / small."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def test_category_minor() -> None:
    import ages

    assert ages.category(10) == "minor"
    assert ages.category(0) == "minor"
    assert ages.category(17) == "minor"


def test_category_adult() -> None:
    import ages

    assert ages.category(18) == "adult"
    assert ages.category(40) == "adult"
    assert ages.category(64) == "adult"


def test_category_senior() -> None:
    import ages

    assert ages.category(65) == "senior"
    assert ages.category(70) == "senior"


def test_discount_pct_values() -> None:
    import ages

    assert ages.discount_pct(10) == 0.5
    assert ages.discount_pct(30) == 0.0
    assert ages.discount_pct(80) == 0.3


def test_existing_helpers_untouched() -> None:
    import ages

    assert ages.is_adult(17) is False
    assert ages.is_adult(18) is True
    assert ages.is_senior(64) is False
    assert ages.is_senior(65) is True
