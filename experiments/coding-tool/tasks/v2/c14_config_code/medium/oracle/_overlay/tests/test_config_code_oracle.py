"""Oracle for c14_config_code / medium."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _reload(*mods):
    for name in list(sys.modules):
        if name.startswith("ecom"):
            del sys.modules[name]
    return [__import__(m, fromlist=["*"]) for m in mods]


def test_config_module_exists() -> None:
    assert (ROOT / "ecom" / "config.py").exists(), (
        "ecom/config.py must be created"
    )


def test_config_exports_expected_constants() -> None:
    [config] = _reload("ecom.config")
    assert config.TAX_RATE == 0.08
    assert config.SHIPPING_PER_KG == 2.50
    assert config.FREE_SHIPPING_THRESHOLD == 100.0
    assert config.MAX_DISCOUNT_PCT == 50.0


def test_pricing_no_longer_defines_constants() -> None:
    src = (ROOT / "ecom" / "pricing.py").read_text(encoding="utf-8")
    # pricing.py must NOT contain definitions like `TAX_RATE = ...` at module
    # scope. References (e.g. `subtotal * TAX_RATE`) are OK.
    for name in ("TAX_RATE", "SHIPPING_PER_KG", "FREE_SHIPPING_THRESHOLD", "MAX_DISCOUNT_PCT"):
        assert not re.search(rf"^{name}\s*=", src, flags=re.MULTILINE), (
            f"{name} must not be defined in ecom/pricing.py"
        )


def test_pricing_imports_from_config() -> None:
    src = (ROOT / "ecom" / "pricing.py").read_text(encoding="utf-8")
    assert "ecom.config" in src or "from ecom import config" in src, (
        "ecom/pricing.py must import constants from ecom.config"
    )


def test_pricing_behavior_preserved() -> None:
    [pricing, models] = _reload("ecom.pricing", "ecom.models")
    o = models.Order(
        order_id=1,
        user=models.User(user_id=1, email="a@b.com", name="A"),
        lines=[
            models.OrderLine(
                product=models.Product(
                    product_id=1, name="W", unit_price=50.0, weight_kg=1.0
                ),
                quantity=2,
            )
        ],
    )
    assert pricing.compute_total(o) == 108.0
    assert pricing.apply_tax(100.0) == 108.0
    assert pricing.apply_shipping(150.0, 5.0) == 150.0
