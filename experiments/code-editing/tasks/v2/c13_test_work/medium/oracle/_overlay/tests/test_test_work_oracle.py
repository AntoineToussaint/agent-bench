"""Oracle for c13_test_work / medium."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _src() -> str:
    return (ROOT / "tests" / "test_orders.py").read_text(encoding="utf-8")


def test_test_cancel_already_cancelled_defined() -> None:
    assert re.search(r"\bdef test_cancel_already_cancelled\b", _src())


def test_test_cancel_sends_cancellation_email_defined() -> None:
    assert re.search(r"\bdef test_cancel_sends_cancellation_email\b", _src())


def test_test_cancel_missing_order_raises_defined() -> None:
    assert re.search(r"\bdef test_cancel_missing_order_raises\b", _src())


def test_pytest_collects_at_least_seven_tests() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_orders.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"pytest --collect-only failed:\n{proc.stdout}\n{proc.stderr}"
    )
    test_lines = [
        line for line in proc.stdout.splitlines()
        if "test_orders.py::" in line
    ]
    # Base file has 4 tests; oracle requires 3 more = 7 minimum.
    assert len(test_lines) >= 7, (
        f"expected at least 7 tests in test_orders.py, got {len(test_lines)}:\n"
        + "\n".join(test_lines)
    )


def test_existing_tests_unchanged() -> None:
    src = _src()
    for name in (
        "test_create_order_persists_and_returns_total",
        "test_ship_order_sets_status",
        "test_cancel_order_sets_status",
        "test_notification_payload_shape",
    ):
        assert re.search(rf"\bdef {name}\b", src), f"original {name} was removed"
