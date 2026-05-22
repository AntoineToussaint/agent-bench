"""Canonical solution for c02_multi_site / small."""

from __future__ import annotations

from pathlib import Path


def apply(workdir: Path) -> None:
    p = workdir / "formatting.py"
    text = p.read_text(encoding="utf-8")

    # 1. Change the INDENT constant from four spaces to two.
    text = text.replace('INDENT = "    "', 'INDENT = "  "')

    # 2. Replace the two hardcoded four-space literals with INDENT.
    text = text.replace(
        '        out.append("    " + f"{i}. " + line)',
        '        out.append(INDENT + f"{i}. " + line)',
    )
    text = text.replace(
        '    return "\\n".join("    " + "> " + line for line in lines)',
        '    return "\\n".join(INDENT + "> " + line for line in lines)',
    )

    p.write_text(text, encoding="utf-8")
