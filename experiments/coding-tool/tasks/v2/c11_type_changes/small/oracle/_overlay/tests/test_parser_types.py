"""Oracle for c11_type_changes / small — annotate every function in parsers.py."""

import sys
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_parse_int_annotations() -> None:
    import parsers

    hints = typing.get_type_hints(parsers.parse_int)
    assert hints.get("s") is str
    assert hints.get("return") is int


def test_parse_floats_annotations() -> None:
    import parsers

    hints = typing.get_type_hints(parsers.parse_floats)
    assert hints.get("items") == list[str]
    assert hints.get("return") == list[float]


def test_parse_pair_annotations() -> None:
    import parsers

    hints = typing.get_type_hints(parsers.parse_pair)
    assert hints.get("text") is str
    assert hints.get("sep") is str
    assert hints.get("return") == tuple[str, str]


def test_parse_kv_annotations() -> None:
    import parsers

    hints = typing.get_type_hints(parsers.parse_kv)
    assert hints.get("lines") == list[str]
    assert hints.get("return") == dict[str, str]


def test_behavior_preserved() -> None:
    import parsers

    assert parsers.parse_int(" 42 ") == 42
    assert parsers.parse_floats(["1", "2.5"]) == [1.0, 2.5]
    assert parsers.parse_pair("a = 1", "=") == ("a", "1")
    assert parsers.parse_kv(["a=1", "b=2"]) == {"a": "1", "b": "2"}
