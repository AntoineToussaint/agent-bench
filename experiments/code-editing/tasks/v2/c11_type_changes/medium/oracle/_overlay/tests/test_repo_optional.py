"""Oracle for c11_type_changes / medium — repository returns Optional[T] / bool."""

import typing

from ecom.models import Order, OrderLine, Product, User
from ecom.repository import Repository


def _fresh() -> Repository:
    return Repository()


def test_get_user_missing_returns_none() -> None:
    assert _fresh().get_user(999) is None


def test_get_product_missing_returns_none() -> None:
    assert _fresh().get_product(999) is None


def test_get_order_missing_returns_none() -> None:
    assert _fresh().get_order(999) is None


def test_get_user_present_returns_user() -> None:
    repo = _fresh()
    user = User(user_id=1, email="a@b.com", name="A")
    repo.users[1] = user
    assert repo.get_user(1) is user


def test_delete_missing_order_returns_false() -> None:
    assert _fresh().delete_order(999) is False


def test_delete_existing_order_returns_true() -> None:
    repo = _fresh()
    user = User(user_id=1, email="a@b.com", name="A")
    product = Product(product_id=1, name="W", unit_price=1.0, weight_kg=0.5)
    order = Order(order_id=7, user=user, lines=[OrderLine(product=product, quantity=1)])
    repo.save_order(order)
    assert repo.delete_order(7) is True
    assert 7 not in repo.orders


def test_return_annotations_are_optional() -> None:
    hints_user = typing.get_type_hints(Repository.get_user)
    hints_product = typing.get_type_hints(Repository.get_product)
    hints_order = typing.get_type_hints(Repository.get_order)

    # typing.Optional[X] resolves to Union[X, None] in get_type_hints
    assert hints_user["return"] == typing.Optional[User]
    assert hints_product["return"] == typing.Optional[Product]
    assert hints_order["return"] == typing.Optional[Order]


def test_save_and_delete_annotations() -> None:
    save_hints = typing.get_type_hints(Repository.save_order)
    delete_hints = typing.get_type_hints(Repository.delete_order)
    assert save_hints["return"] is type(None)
    assert delete_hints["return"] is bool
