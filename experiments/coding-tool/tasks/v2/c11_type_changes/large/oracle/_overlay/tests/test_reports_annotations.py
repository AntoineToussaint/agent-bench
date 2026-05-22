"""Oracle for c11_type_changes / large — annotate every function in reports.py."""

from __future__ import annotations

import inspect
import typing
from datetime import date

import pytest

from ecom import reports
from ecom.models import Order, OrderLine, Product, User


# All top-level functions in reports.py we expect annotated.
EXPECTED_FUNCTIONS = [
    "_order_date",
    "_is_billable",
    "daily_sales",
    "top_products",
    "revenue_by_user",
    "status_breakdown",
    "average_order_value",
    "total_units_sold",
    "revenue_in_range",
    "biggest_spender",
]


@pytest.mark.parametrize("name", EXPECTED_FUNCTIONS)
def test_function_has_full_annotations(name: str) -> None:
    fn = getattr(reports, name)
    sig = inspect.signature(fn)
    # Every parameter must have an annotation.
    for param_name, param in sig.parameters.items():
        assert param.annotation is not inspect.Parameter.empty, (
            f"{name} parameter {param_name!r} is missing an annotation"
        )
    # Return annotation must be present and not "empty".
    assert sig.return_annotation is not inspect.Signature.empty, (
        f"{name} is missing a return annotation"
    )


@pytest.mark.parametrize("name", EXPECTED_FUNCTIONS)
def test_function_type_hints_resolve(name: str) -> None:
    fn = getattr(reports, name)
    hints = typing.get_type_hints(fn)
    # Must have a "return" key and at least as many parameter entries as
    # non-self parameters.
    assert "return" in hints, f"{name}: missing return entry in get_type_hints"
    sig = inspect.signature(fn)
    for param_name in sig.parameters:
        assert param_name in hints, (
            f"{name}: parameter {param_name!r} missing from get_type_hints"
        )


def test_behavior_preserved_daily_sales() -> None:
    user = User(user_id=1, email="a@b.com", name="A")
    product = Product(product_id=1, name="W", unit_price=10.0, weight_kg=0.5)
    order = Order(
        order_id=1,
        user=user,
        lines=[OrderLine(product=product, quantity=2)],
        notes=["placed_on=2024-01-05"],
    )
    rep = reports.daily_sales([order], date(2024, 1, 5))
    assert rep.order_count == 1
    assert rep.gross_revenue > 0


def test_behavior_preserved_helpers() -> None:
    assert reports.average_order_value([]) == 0.0
    assert reports.total_units_sold([]) == 0
    assert reports.biggest_spender([]) is None
    assert reports.top_products([], n=5) == []
