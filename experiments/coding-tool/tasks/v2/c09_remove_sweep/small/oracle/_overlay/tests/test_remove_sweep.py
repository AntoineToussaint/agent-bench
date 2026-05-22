"""Oracle tests for c09_remove_sweep / small."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))

OLD = re.compile(r"\bdeprecated_double\b")


def test_deprecated_double_removed_from_module() -> None:
    import math_utils

    assert not hasattr(math_utils, "deprecated_double")


def test_no_references_in_sources() -> None:
    for rel in ("math_utils.py", "app.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert not OLD.search(src), f"{rel} still references deprecated_double"


def test_total_behaviour_preserved() -> None:
    import app

    assert app.total([1, 2, 3]) == 12
    assert app.total([]) == 0
    assert app.total([5]) == 10


def test_squares_unchanged() -> None:
    import app

    assert app.squares([2, 3]) == [4, 9]


def test_square_and_cube_unchanged() -> None:
    import math_utils

    assert math_utils.square(4) == 16
    assert math_utils.cube(3) == 27
