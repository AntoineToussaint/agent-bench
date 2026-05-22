"""Unit tests for the three edit formats — pure-Python, no API calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_editing.formats.search_replace import SearchReplaceFormat
from code_editing.formats.semantic import SemanticFormat
from code_editing.formats.unified_diff import UnifiedDiffFormat
from code_editing.types import ToolCall


def _write(workdir: Path, rel: str, content: str) -> Path:
    p = workdir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------- search_replace ----------


def test_search_replace_happy(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def foo():\n    return 1\n")
    fmt = SearchReplaceFormat()
    res = fmt.apply(
        ToolCall(
            name="str_replace",
            arguments={"path": "a.py", "old_str": "return 1", "new_str": "return 2"},
            call_id="1",
        ),
        tmp_path,
    )
    assert res.status == "ok"
    assert (tmp_path / "a.py").read_text() == "def foo():\n    return 2\n"


def test_search_replace_ambiguous(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "x = 1\ny = 1\n")
    fmt = SearchReplaceFormat()
    res = fmt.apply(
        ToolCall(
            name="str_replace",
            arguments={"path": "a.py", "old_str": "1", "new_str": "2"},
            call_id="1",
        ),
        tmp_path,
    )
    assert res.status == "error"
    assert "matches 2 locations" in res.content


# ---------- unified_diff ----------


def test_unified_diff_modify(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def foo():\n    return 1\n")
    fmt = UnifiedDiffFormat()
    patch = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def foo():\n"
        "-    return 1\n"
        "+    return 2\n"
    )
    res = fmt.apply(
        ToolCall(name="apply_patch", arguments={"patch": patch}, call_id="1"),
        tmp_path,
    )
    assert res.status == "ok", res.content
    assert (tmp_path / "a.py").read_text() == "def foo():\n    return 2\n"


def test_unified_diff_codex_envelope_rejected(tmp_path: Path) -> None:
    fmt = UnifiedDiffFormat()
    patch = "*** Begin Patch\n*** Update File: a.py\n+x = 1\n*** End Patch\n"
    res = fmt.apply(
        ToolCall(name="apply_patch", arguments={"patch": patch}, call_id="1"),
        tmp_path,
    )
    assert res.status == "error"
    assert "Codex" in res.content


# ---------- semantic ----------


def test_semantic_replace_function(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n")
    fmt = SemanticFormat()
    res = fmt.apply(
        ToolCall(
            name="replace",
            arguments={
                "path": "a.py",
                "name": "foo",
                "new_source": "def foo():\n    return 42\n",
            },
            call_id="1",
        ),
        tmp_path,
    )
    assert res.status == "ok", res.content
    text = (tmp_path / "a.py").read_text()
    assert "return 42" in text
    assert "return 2" in text


def test_semantic_replace_method(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.py",
        "class Foo:\n    def bar(self):\n        return 1\n\n    def baz(self):\n        return 2\n",
    )
    fmt = SemanticFormat()
    res = fmt.apply(
        ToolCall(
            name="replace",
            arguments={
                "path": "a.py",
                "name": "Foo.bar",
                "new_source": "def bar(self):\n    return 99\n",
            },
            call_id="1",
        ),
        tmp_path,
    )
    assert res.status == "ok", res.content
    text = (tmp_path / "a.py").read_text()
    assert "return 99" in text
    assert "return 2" in text


def test_semantic_change_value_of(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", 'INDENT = "    "\n\ndef foo():\n    return INDENT\n')
    fmt = SemanticFormat()
    res = fmt.apply(
        ToolCall(
            name="change_value_of",
            arguments={"path": "a.py", "target": "INDENT", "new_value": '"  "'},
            call_id="1",
        ),
        tmp_path,
    )
    assert res.status == "ok", res.content
    text = (tmp_path / "a.py").read_text()
    assert 'INDENT = "  "' in text


def test_semantic_rename_includes_docstring(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.py",
        '"""Module that uses helper.\n\n`helper` is the main entry point.\n"""\n\n'
        "def helper(x):\n    return x * 2\n",
    )
    fmt = SemanticFormat()
    res = fmt.apply(
        ToolCall(
            name="rename",
            arguments={"paths": ["a.py"], "old_name": "helper", "new_name": "double_value"},
            call_id="1",
        ),
        tmp_path,
    )
    assert res.status == "ok", res.content
    text = (tmp_path / "a.py").read_text()
    assert "helper" not in text  # docstring updated too
    assert "double_value" in text
    assert "def double_value" in text


def test_semantic_add_parameter(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def f(x):\n    return x\n")
    fmt = SemanticFormat()
    res = fmt.apply(
        ToolCall(
            name="add_parameter",
            arguments={
                "path": "a.py",
                "callable": "f",
                "param_name": "y",
                "default": "0",
                "annotation": "int",
            },
            call_id="1",
        ),
        tmp_path,
    )
    assert res.status == "ok", res.content
    text = (tmp_path / "a.py").read_text()
    assert "y: int = 0" in text


def test_semantic_add_import(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", '"""mod."""\n\nimport os\n\n\ndef f():\n    return os.name\n')
    fmt = SemanticFormat()
    res = fmt.apply(
        ToolCall(
            name="add_import",
            arguments={"path": "a.py", "source": "pathlib", "names": ["Path"]},
            call_id="1",
        ),
        tmp_path,
    )
    assert res.status == "ok", res.content
    text = (tmp_path / "a.py").read_text()
    assert "from pathlib import Path" in text
    # placed after existing imports
    assert text.index("from pathlib") > text.index("import os")


def test_semantic_remove(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def keep():\n    return 1\n\n\ndef gone():\n    return 2\n")
    fmt = SemanticFormat()
    res = fmt.apply(
        ToolCall(
            name="remove",
            arguments={"path": "a.py", "name": "gone"},
            call_id="1",
        ),
        tmp_path,
    )
    assert res.status == "ok", res.content
    text = (tmp_path / "a.py").read_text()
    assert "def keep" in text
    assert "def gone" not in text


def test_semantic_move(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def keep():\n    return 0\n\n\ndef mover():\n    return 1\n")
    fmt = SemanticFormat()
    res = fmt.apply(
        ToolCall(
            name="move",
            arguments={"from_path": "a.py", "to_path": "b.py", "name": "mover"},
            call_id="1",
        ),
        tmp_path,
    )
    assert res.status == "ok", res.content
    assert "def mover" not in (tmp_path / "a.py").read_text()
    assert "def mover" in (tmp_path / "b.py").read_text()
