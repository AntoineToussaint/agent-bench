"""Oracle for c13_test_work / small."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _test_calc_source() -> str:
    return (ROOT / "tests" / "test_calc.py").read_text(encoding="utf-8")


def test_test_add_negative_defined() -> None:
    assert re.search(r"\bdef test_add_negative\b", _test_calc_source()), (
        "test_add_negative must be defined in tests/test_calc.py"
    )


def test_test_add_zero_defined() -> None:
    assert re.search(r"\bdef test_add_zero\b", _test_calc_source()), (
        "test_add_zero must be defined in tests/test_calc.py"
    )


def test_test_add_large_defined() -> None:
    assert re.search(r"\bdef test_add_large\b", _test_calc_source()), (
        "test_add_large must be defined in tests/test_calc.py"
    )


def test_pytest_collects_at_least_seven_tests() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_calc.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"pytest --collect-only failed:\n{proc.stdout}\n{proc.stderr}"
    )
    # Count lines that look like test ids
    test_lines = [
        line for line in proc.stdout.splitlines()
        if "test_calc.py::" in line
    ]
    assert len(test_lines) >= 7, (
        f"expected at least 7 tests in test_calc.py, got {len(test_lines)}:\n"
        + "\n".join(test_lines)
    )


def test_existing_tests_unchanged() -> None:
    src = _test_calc_source()
    # The four original tests must still be present.
    for name in ("test_add", "test_sub", "test_mul", "test_div"):
        assert re.search(rf"\bdef {name}\b", src), f"original {name} was removed"
