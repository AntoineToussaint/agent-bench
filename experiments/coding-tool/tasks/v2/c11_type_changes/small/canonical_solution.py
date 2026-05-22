"""Canonical solution for c11_type_changes / small."""

from __future__ import annotations

from pathlib import Path


CONTENT = '''"""Tiny parsing utilities."""

from __future__ import annotations


def parse_int(s: str) -> int:
    return int(s.strip())


def parse_floats(items: list[str]) -> list[float]:
    return [float(x) for x in items]


def parse_pair(text: str, sep: str) -> tuple[str, str]:
    a, b = text.split(sep, 1)
    return a.strip(), b.strip()


def parse_kv(lines: list[str]) -> dict[str, str]:
    return dict(parse_pair(ln, "=") for ln in lines)
'''


def apply(workdir: Path) -> None:
    p = workdir / "parsers.py"
    p.write_text(CONTENT, encoding="utf-8")
