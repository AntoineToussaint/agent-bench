"""Oracle tests for c04_signature_change / small."""

import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def test_signature_has_tax_rate() -> None:
    import billing

    sig = inspect.signature(billing.compute_total)
    assert "tax_rate" in sig.parameters, "compute_total must accept tax_rate"
    p = sig.parameters["tax_rate"]
    assert p.default == 0.0, f"tax_rate default must be 0.0, got {p.default!r}"


def test_tax_rate_applied() -> None:
    import billing

    assert abs(billing.compute_total([("a", 100)], tax_rate=0.1) - 110.0) < 1e-9


def test_checkout_uses_tax_rate() -> None:
    import app

    # 100 * (1 - 0.05) * (1 + 0.1) = 95 * 1.1 = 104.5
    assert abs(app.checkout([("a", 100)]) - 104.5) < 1e-9


def test_report_callsite_unchanged() -> None:
    src = (ROOT / "report.py").read_text(encoding="utf-8")
    assert not re.search(r"\btax_rate\b", src), "report.py must not mention tax_rate"


def test_quick_total_default_behaviour() -> None:
    import app

    # No tax, no discount -> identity sum.
    assert app.quick_total([("a", 100), ("b", 50)]) == 150.0
