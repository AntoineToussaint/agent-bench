"""Canonical solution for c07_inline_function / small."""

from __future__ import annotations

from pathlib import Path


NEW_SOURCE = '''"""A handful of geometry utilities.

`_square` is a tiny one-line helper. It is overkill: every call site would
read just as clearly with `x * x` inlined.
"""

from __future__ import annotations


def circle_area(r):
    return 3.14159 * (r * r)


def rectangle_diagonal(w, h):
    from math import sqrt
    return sqrt((w * w) + (h * h))


def cube_volume(s):
    return (s * s) * s


def cube_surface_area(s):
    return 6 * (s * s)
'''


def apply(workdir: Path) -> None:
    (workdir / "geometry.py").write_text(NEW_SOURCE, encoding="utf-8")
