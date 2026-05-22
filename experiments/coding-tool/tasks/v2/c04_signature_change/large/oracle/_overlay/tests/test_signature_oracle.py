"""Oracle for c04_signature_change / large — add `currency` param."""

import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))

CURRENCY_RE = re.compile(r"\bcurrency\b")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_signature_has_currency() -> None:
    from ecom.pricing import compute_total

    sig = inspect.signature(compute_total)
    params = list(sig.parameters)
    assert "currency" in params
    p = sig.parameters["currency"]
    assert p.default == "USD"
    assert p.annotation in (str, "str"), f"currency annotation must be str, got {p.annotation!r}"
    # must come AFTER `order`
    assert params.index("currency") > params.index("order")


def test_default_behaviour_unchanged() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.pricing import compute_total

    user = User(user_id=1, email="a@b.com", name="A")
    p = Product(product_id=1, name="W", unit_price=50.0, weight_kg=1.0)
    order = Order(order_id=1, user=user, lines=[OrderLine(product=p, quantity=2)])
    assert compute_total(order) == 108.0


def test_explicit_currency_does_not_change_math() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.pricing import compute_total

    user = User(user_id=1, email="a@b.com", name="A")
    p = Product(product_id=1, name="W", unit_price=50.0, weight_kg=1.0)
    order = Order(order_id=1, user=user, lines=[OrderLine(product=p, quantity=2)])
    assert compute_total(order, currency="EUR") == compute_total(order)
    assert compute_total(order, currency="JPY") == compute_total(order)


CREATE_ORDER_RE = re.compile(
    r"def create_order\b[^\n]*\n(.*?)(?=\ndef |\Z)", re.DOTALL
)


def test_create_order_passes_currency_eur() -> None:
    src = _read("ecom/orders.py")
    m = CREATE_ORDER_RE.search(src)
    assert m, "create_order function not found"
    body = m.group(1)
    assert re.search(
        r"compute_total\(\s*order\s*,\s*currency\s*=\s*['\"]EUR['\"]\s*\)",
        body,
    ), "create_order must call compute_total(order, currency=\"EUR\")"


def test_other_orders_functions_do_not_mention_currency() -> None:
    src = _read("ecom/orders.py")
    # Strip the create_order body, then check the rest of the file is clean
    rest = CREATE_ORDER_RE.sub("", src)
    assert not CURRENCY_RE.search(rest), (
        "only create_order in orders.py should mention currency"
    )


def test_other_modules_untouched() -> None:
    for rel in ("ecom/app.py", "ecom/coupons.py", "ecom/reports.py"):
        assert not CURRENCY_RE.search(_read(rel)), (
            f"{rel} must not mention currency"
        )
