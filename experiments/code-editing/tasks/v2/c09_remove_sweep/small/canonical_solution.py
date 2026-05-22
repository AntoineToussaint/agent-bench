"""Canonical solution for c09_remove_sweep / small."""

from __future__ import annotations

from pathlib import Path


NEW_MATH_UTILS = '''"""Tiny math helpers — toy size."""

from __future__ import annotations


def square(x):
    return x * x


def cube(x):
    return x * x * x
'''


NEW_APP = '''from math_utils import square


def total(values):
    return sum(2 * v for v in values)


def squares(values):
    return [square(v) for v in values]
'''


def apply(workdir: Path) -> None:
    (workdir / "math_utils.py").write_text(NEW_MATH_UTILS, encoding="utf-8")
    (workdir / "app.py").write_text(NEW_APP, encoding="utf-8")
