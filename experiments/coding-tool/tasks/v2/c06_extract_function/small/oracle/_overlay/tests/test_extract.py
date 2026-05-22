"""Oracle for c06_extract_function / small."""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


RAISE_LITERAL = re.compile(r'raise\s+ValueError\(\s*"values must not be empty"\s*\)')
CALL_HELPER = re.compile(r"\b_validate_and_coerce\s*\(")


def _read() -> str:
    return (ROOT / "stats.py").read_text(encoding="utf-8")


def _source_of(func_name: str) -> str:
    import ast

    tree = ast.parse(_read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return ast.unparse(node)
    raise AssertionError(f"function {func_name} not found in stats.py")


def test_helper_exists_and_callable() -> None:
    import stats

    assert hasattr(stats, "_validate_and_coerce")
    assert callable(stats._validate_and_coerce)


def test_helper_validates_empty() -> None:
    import stats

    with pytest.raises(ValueError):
        stats._validate_and_coerce([])


def test_helper_coerces_to_floats() -> None:
    import stats

    out = stats._validate_and_coerce([1, "2", 3.0])
    assert out == [1.0, 2.0, 3.0]
    assert all(isinstance(v, float) for v in out)


def test_each_caller_uses_helper_and_drops_literal() -> None:
    for func in ("mean", "median", "range_"):
        body = _source_of(func)
        assert CALL_HELPER.search(body), (
            f"`{func}` must call _validate_and_coerce; got:\n{body}"
        )
        assert not RAISE_LITERAL.search(body), (
            f"`{func}` must no longer contain the inlined raise; got:\n{body}"
        )


def test_module_defines_helper_only_once() -> None:
    src = _read()
    assert src.count("def _validate_and_coerce") == 1
