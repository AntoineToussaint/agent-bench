"""Canonical solution for c12_hygiene / small."""

from __future__ import annotations

from pathlib import Path


NEW_SOURCE = '''"""Small numeric helpers — post-hygiene."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return float("inf")


def safe_divide_all(numbers, denom):
    try:
        if denom == 0:
            logger.error("safe_divide_all: zero denominator")
            return None
        return [divide(n, denom) for n in numbers]
    except Exception as exc:
        logger.error(f"safe_divide_all failed: {exc}")
        return None


def average(values):
    try:
        if len(values) == 0:
            logger.error("average: empty input")
            return None
        return divide(sum(values), len(values))
    except Exception as exc:
        logger.error(f"average failed: {exc}")
        return None
'''


def apply(workdir: Path) -> None:
    (workdir / "divider.py").write_text(NEW_SOURCE, encoding="utf-8")
