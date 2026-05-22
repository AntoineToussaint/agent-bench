"""A handful of geometry utilities.

`_square` is a tiny one-line helper. It is overkill: every call site would
read just as clearly with `x * x` inlined.
"""

from __future__ import annotations


def _square(x):
    return x * x


def circle_area(r):
    return 3.14159 * _square(r)


def rectangle_diagonal(w, h):
    from math import sqrt
    return sqrt(_square(w) + _square(h))


def cube_volume(s):
    return _square(s) * s


def cube_surface_area(s):
    return 6 * _square(s)
