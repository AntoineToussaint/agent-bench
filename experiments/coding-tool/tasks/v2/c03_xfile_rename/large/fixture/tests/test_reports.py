"""Tests for the reports module."""

from datetime import date

from ecom.models import Order, OrderLine, Product, User
from ecom.reports import (
    average_order_value,
    biggest_spender,
    daily_sales,
    revenue_by_user,
    revenue_in_range,
    top_products,
    total_units_sold,
)


def _user(uid: int) -> User:
    return User(user_id=uid, email=f"u{uid}@example.com", name=f"U{uid}")


def _product(pid: int, price: float = 10.0) -> Product:
    return Product(product_id=pid, name=f"P{pid}", unit_price=price, weight_kg=0.5)


def _order(
    oid: int,
    user: User,
    lines: list[OrderLine],
    placed_on: date | None = None,
    status: str = "pending",
) -> Order:
    notes: list[str] = []
    if placed_on is not None:
        notes.append(f"placed_on={placed_on.isoformat()}")
    return Order(order_id=oid, user=user, lines=lines, status=status, notes=notes)


def _orders() -> list[Order]:
    u1, u2 = _user(1), _user(2)
    p1, p2 = _product(1, 10.0), _product(2, 25.0)
    return [
        _order(
            1,
            u1,
            [OrderLine(product=p1, quantity=2), OrderLine(product=p2, quantity=1)],
            placed_on=date(2024, 1, 5),
        ),
        _order(2, u1, [OrderLine(product=p1, quantity=5)], placed_on=date(2024, 1, 5)),
        _order(3, u2, [OrderLine(product=p2, quantity=3)], placed_on=date(2024, 1, 6)),
        _order(
            4,
            u2,
            [OrderLine(product=p1, quantity=10)],
            placed_on=date(2024, 1, 6),
            status="cancelled",
        ),
    ]


def test_daily_sales_groups_by_date() -> None:
    report = daily_sales(_orders(), date(2024, 1, 5))
    assert report.on_date == date(2024, 1, 5)
    assert report.order_count == 2
    assert report.gross_revenue > 0


def test_daily_sales_excludes_cancelled() -> None:
    report = daily_sales(_orders(), date(2024, 1, 6))
    # only the non-cancelled order on the 6th counts
    assert report.order_count == 1


def test_top_products_orders_by_units_sold() -> None:
    ranking = top_products(_orders(), n=2)
    assert len(ranking) == 2
    # p1: 2+5 = 7 units, p2: 1+3 = 4 units (cancelled order excluded)
    assert ranking[0].product_id == 1
    assert ranking[0].units_sold == 7
    assert ranking[1].product_id == 2


def test_revenue_by_user_sums_per_user() -> None:
    revenue = revenue_by_user(_orders())
    assert set(revenue.keys()) == {1, 2}
    assert revenue[1] > 0
    assert revenue[2] > 0


def test_revenue_in_range_filters_dates() -> None:
    total = revenue_in_range(_orders(), date(2024, 1, 5), date(2024, 1, 5))
    assert total > 0
    empty = revenue_in_range(_orders(), date(2024, 2, 1), date(2024, 2, 28))
    assert empty == 0.0


def test_helpers_handle_empty_input() -> None:
    assert average_order_value([]) == 0.0
    assert total_units_sold([]) == 0
    assert biggest_spender([]) is None
    assert top_products([], n=5) == []
