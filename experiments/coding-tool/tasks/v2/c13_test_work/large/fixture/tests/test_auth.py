"""Tests for the role-based auth module."""

import pytest

from ecom.auth import (
    AuthUser,
    Permission,
    PermissionDenied,
    grant,
    has_permission,
    permissions_for,
    require_permission,
    require_role,
    revoke,
)


def _admin() -> AuthUser:
    return AuthUser(user_id=1, email="admin@example.com", role="admin")


def _customer() -> AuthUser:
    return AuthUser(user_id=2, email="cust@example.com", role="customer")


def test_admin_has_every_permission() -> None:
    admin = _admin()
    for perm in Permission:
        assert has_permission(admin, perm)


def test_customer_cannot_view_reports() -> None:
    cust = _customer()
    assert has_permission(cust, Permission.CREATE_ORDER)
    assert not has_permission(cust, Permission.VIEW_REPORTS)


def test_require_role_allows_matching_role() -> None:
    @require_role("staff", "admin")
    def restricted(user: AuthUser) -> str:
        return "ok"

    assert restricted(_admin()) == "ok"


def test_require_role_blocks_wrong_role() -> None:
    @require_role("admin")
    def restricted(user: AuthUser) -> str:
        return "ok"

    with pytest.raises(PermissionDenied):
        restricted(_customer())


def test_grant_and_revoke_extra_permission() -> None:
    cust = _customer()
    assert not has_permission(cust, Permission.VIEW_REPORTS)
    grant(cust, Permission.VIEW_REPORTS)
    assert has_permission(cust, Permission.VIEW_REPORTS)
    revoke(cust, Permission.VIEW_REPORTS)
    assert not has_permission(cust, Permission.VIEW_REPORTS)


def test_inactive_user_loses_all_permissions() -> None:
    admin = _admin()
    admin.active = False
    assert not has_permission(admin, Permission.MANAGE_USERS)

    @require_permission(Permission.MANAGE_USERS)
    def restricted(user: AuthUser) -> str:
        return "ok"

    with pytest.raises(PermissionDenied):
        restricted(admin)


def test_permissions_for_unknown_role_raises() -> None:
    with pytest.raises(ValueError):
        permissions_for("ghost")
