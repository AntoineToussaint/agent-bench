"""Oracle for c12_hygiene / small."""

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _fresh_divider():
    # Re-import in case earlier tests cached state
    if "divider" in sys.modules:
        del sys.modules["divider"]
    import divider
    return divider


def test_logger_is_defined() -> None:
    divider = _fresh_divider()
    assert hasattr(divider, "logger"), "module-level `logger` must be defined"
    assert isinstance(divider.logger, logging.Logger)


def test_divide_happy_path_unchanged() -> None:
    divider = _fresh_divider()
    assert divider.divide(10, 2) == 5.0


def test_divide_by_zero_returns_infinity() -> None:
    divider = _fresh_divider()
    assert divider.divide(10, 0) == float("inf")


def test_safe_divide_all_zero_denominator_returns_none_and_logs(caplog) -> None:
    divider = _fresh_divider()
    with caplog.at_level(logging.ERROR, logger="divider"):
        result = divider.safe_divide_all([1, 2], 0)
    assert result is None
    assert any(rec.levelno == logging.ERROR for rec in caplog.records), (
        "safe_divide_all must emit an ERROR-level log record on zero denominator"
    )


def test_safe_divide_all_happy_path_unchanged() -> None:
    divider = _fresh_divider()
    assert divider.safe_divide_all([2, 4, 6], 2) == [1.0, 2.0, 3.0]


def test_average_empty_returns_none() -> None:
    divider = _fresh_divider()
    assert divider.average([]) is None


def test_average_happy_path_unchanged() -> None:
    divider = _fresh_divider()
    assert divider.average([2, 4, 6]) == 4.0
