"""Oracle for c02_multi_site / small."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def test_indent_constant_is_two_spaces() -> None:
    import formatting

    assert formatting.INDENT == "  "


def test_no_four_space_literal_remains() -> None:
    src = (ROOT / "formatting.py").read_text(encoding="utf-8")
    # The constant line and any hardcoded sites should both be gone.
    assert '"    "' not in src, "no `\"    \"` literal should remain in formatting.py"


def test_constant_still_used_in_helpers() -> None:
    import formatting

    # All five INDENT-using helpers must reflect the new two-space width.
    assert formatting.indent_line("x") == "  x"
    assert formatting.indent_block(["a", "b"]) == "  a\n  b"
    assert formatting.indent_twice("x") == "    x"
    assert formatting.bullet("hi") == "  - hi"
    assert formatting.section("H", ["a", "b"]) == "H\n  a\n  b"


def test_numbered_uses_new_indent() -> None:
    import formatting

    assert formatting.numbered(["a", "b"]) == "  1. a\n  2. b"


def test_quoted_block_uses_new_indent() -> None:
    import formatting

    assert formatting.quoted_block(["a", "b"]) == "  > a\n  > b"
