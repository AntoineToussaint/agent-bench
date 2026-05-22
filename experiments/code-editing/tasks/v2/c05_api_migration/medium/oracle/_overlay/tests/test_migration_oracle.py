"""Oracle for c05_api_migration / medium — print → logger.info."""

import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))

PRINT_RE = re.compile(r"\bprint\(")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_print_in_notifications() -> None:
    assert not PRINT_RE.search(_read("ecom/notifications.py"))


def test_logger_defined_in_notifications() -> None:
    src = _read("ecom/notifications.py")
    assert "import logging" in src
    assert re.search(r"logger\s*=\s*logging\.getLogger\(__name__\)", src)


def test_send_order_confirmation_returns_expected_dict() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.notifications import send_order_confirmation

    user = User(user_id=1, email="a@b.com", name="A")
    p = Product(product_id=1, name="Widget", unit_price=10.0, weight_kg=1.0)
    order = Order(order_id=42, user=user, lines=[OrderLine(product=p, quantity=2)])

    payload = send_order_confirmation(order)
    assert payload["to"] == "a@b.com"
    assert "confirmed" in payload["subject"]
    assert "42" in payload["subject"]
    assert payload["reply_to"] == "support@example.com"


def test_log_records_emitted(caplog) -> None:
    import importlib

    import ecom.notifications as notifications

    importlib.reload(notifications)
    caplog.set_level(logging.INFO, logger="ecom.notifications")

    from ecom.models import Order, OrderLine, Product, User

    user = User(user_id=1, email="hello@example.com", name="Hello")
    p = Product(product_id=1, name="X", unit_price=1.0, weight_kg=0.1)
    order = Order(order_id=1, user=user, lines=[OrderLine(product=p, quantity=1)])

    notifications.send_order_confirmation(order)
    assert any("hello@example.com" in r.getMessage() for r in caplog.records)


def test_other_modules_untouched() -> None:
    # the migration is scoped to notifications.py only
    for rel in ("ecom/pricing.py", "ecom/orders.py", "ecom/app.py"):
        src = _read(rel)
        assert "logging.getLogger" not in src, (
            f"{rel} must not have been migrated"
        )
