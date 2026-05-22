"""Oracle for c07_inline_function / small."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def _read() -> str:
    return (ROOT / "geometry.py").read_text(encoding="utf-8")


def test_square_helper_is_gone() -> None:
    import geometry

    assert not hasattr(geometry, "_square"), "_square must be removed from the module"


def test_no_square_call_text_remains() -> None:
    src = _read()
    assert "_square(" not in src, "no call to _square should remain in geometry.py"


def test_no_square_def_remains() -> None:
    src = _read()
    assert "def _square" not in src, "_square definition must be deleted"


def test_circle_area_unchanged() -> None:
    import geometry

    assert geometry.circle_area(2) == 3.14159 * 4


def test_rectangle_diagonal_unchanged() -> None:
    import geometry

    assert geometry.rectangle_diagonal(3, 4) == 5.0


def test_cube_volume_unchanged() -> None:
    import geometry

    assert geometry.cube_volume(3) == 27


def test_cube_surface_area_unchanged() -> None:
    import geometry

    assert geometry.cube_surface_area(2) == 24
