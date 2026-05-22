"""Oracle for c14_config_code / large."""

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
    assert (ROOT / "ecom" / "config.py").exists(), "ecom/config.py must be created"


def test_config_exports_expected_constants() -> None:
    [config] = _reload("ecom.config")
    assert config.TAX_RATE == 0.08
    assert config.SHIPPING_PER_KG == 2.50
    assert config.FREE_SHIPPING_THRESHOLD == 100.0
    assert config.MAX_DISCOUNT_PCT == 50.0
    assert config.SUPPORT_EMAIL == "support@example.com"
    assert config.LOW_STOCK_DEFAULT_THRESHOLD == 5


def test_pricing_no_longer_defines_constants() -> None:
    src = (ROOT / "ecom" / "pricing.py").read_text(encoding="utf-8")
    for name in ("TAX_RATE", "SHIPPING_PER_KG", "FREE_SHIPPING_THRESHOLD", "MAX_DISCOUNT_PCT"):
        assert not re.search(rf"^{name}\s*=", src, flags=re.MULTILINE), (
            f"{name} must not be defined in ecom/pricing.py"
        )


def test_notifications_no_longer_defines_support_email() -> None:
    src = (ROOT / "ecom" / "notifications.py").read_text(encoding="utf-8")
    assert not re.search(r"^SUPPORT_EMAIL\s*=", src, flags=re.MULTILINE), (
        "SUPPORT_EMAIL must not be defined in ecom/notifications.py"
    )


def test_pricing_imports_from_config() -> None:
    src = (ROOT / "ecom" / "pricing.py").read_text(encoding="utf-8")
    assert "ecom.config" in src or "from ecom import config" in src


def test_notifications_imports_from_config() -> None:
    src = (ROOT / "ecom" / "notifications.py").read_text(encoding="utf-8")
    assert "ecom.config" in src or "from ecom import config" in src


def test_inventory_imports_low_stock_default() -> None:
    src = (ROOT / "ecom" / "inventory.py").read_text(encoding="utf-8")
    assert "LOW_STOCK_DEFAULT_THRESHOLD" in src, (
        "ecom/inventory.py must reference LOW_STOCK_DEFAULT_THRESHOLD"
    )
    assert "ecom.config" in src or "from ecom import config" in src


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


def test_notifications_behavior_preserved() -> None:
    [notif, models] = _reload("ecom.notifications", "ecom.models")
    order = models.Order(
        order_id=1,
        user=models.User(user_id=1, email="a@b.com", name="A"),
        lines=[],
    )
    payload = notif.send_order_confirmation(order)
    assert payload["reply_to"] == "support@example.com"
