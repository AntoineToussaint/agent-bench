"""Behavioral tests — must keep passing after the indent change."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import formatting


def test_indent_line_uses_constant():
    # Regardless of width, indent_line prefixes INDENT.
    assert formatting.indent_line("x") == formatting.INDENT + "x"


def test_indent_block_uses_constant():
    out = formatting.indent_block(["a", "b"])
    assert out == formatting.INDENT + "a" + "\n" + formatting.INDENT + "b"


def test_indent_twice_uses_constant():
    assert formatting.indent_twice("x") == formatting.INDENT * 2 + "x"


def test_bullet_uses_constant():
    assert formatting.bullet("hi") == formatting.INDENT + "- hi"


def test_section_uses_constant():
    out = formatting.section("Heading", ["a", "b"])
    assert out == "Heading" + "\n" + formatting.INDENT + "a" + "\n" + formatting.INDENT + "b"


def test_numbered_uses_indent_width():
    out = formatting.numbered(["a", "b"])
    expected = formatting.INDENT + "1. a" + "\n" + formatting.INDENT + "2. b"
    assert out == expected


def test_quoted_block_uses_indent_width():
    out = formatting.quoted_block(["a", "b"])
    expected = formatting.INDENT + "> a" + "\n" + formatting.INDENT + "> b"
    assert out == expected
