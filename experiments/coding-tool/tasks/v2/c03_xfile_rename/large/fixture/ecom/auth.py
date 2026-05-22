"""Authentication and role-based access control."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Callable, Iterable


class Permission(str, Enum):
    VIEW_ORDER = "view_order"
    CREATE_ORDER = "create_order"
    CANCEL_ORDER = "cancel_order"
    SHIP_ORDER = "ship_order"
    APPLY_COUPON = "apply_coupon"
    VIEW_REPORTS = "view_reports"
    MANAGE_INVENTORY = "manage_inventory"
    MANAGE_USERS = "manage_users"


ROLES = ("admin", "customer", "staff")


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "admin": frozenset(Permission),
    "staff": frozenset(
        {
            Permission.VIEW_ORDER,
            Permission.SHIP_ORDER,
            Permission.CANCEL_ORDER,
            Permission.VIEW_REPORTS,
            Permission.MANAGE_INVENTORY,
        }
    ),
    "customer": frozenset(
        {
            Permission.VIEW_ORDER,
            Permission.CREATE_ORDER,
            Permission.APPLY_COUPON,
        }
    ),
}


@dataclass
class AuthUser:
    user_id: int
    email: str
    role: str
    active: bool = True
    extra_permissions: set[Permission] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"unknown role: {self.role}")


class PermissionDenied(Exception):
    pass


def _normalize(action: Permission | str) -> Permission:
    if isinstance(action, Permission):
        return action
    try:
        return Permission(action)
    except ValueError as exc:
        raise ValueError(f"unknown permission: {action}") from exc


def permissions_for(role: str) -> frozenset[Permission]:
    if role not in ROLE_PERMISSIONS:
        raise ValueError(f"unknown role: {role}")
    return ROLE_PERMISSIONS[role]


def has_permission(user: AuthUser, action: Permission | str) -> bool:
    if not user.active:
        return False
    perm = _normalize(action)
    if perm in user.extra_permissions:
        return True
    return perm in ROLE_PERMISSIONS.get(user.role, frozenset())


def has_any(user: AuthUser, actions: Iterable[Permission | str]) -> bool:
    return any(has_permission(user, a) for a in actions)


def has_all(user: AuthUser, actions: Iterable[Permission | str]) -> bool:
    return all(has_permission(user, a) for a in actions)


def grant(user: AuthUser, action: Permission | str) -> None:
    user.extra_permissions.add(_normalize(action))


def revoke(user: AuthUser, action: Permission | str) -> None:
    user.extra_permissions.discard(_normalize(action))


def require_role(*allowed_roles: str) -> Callable:
    """Decorator factory: only callers whose `user.role` is in allowed_roles pass."""
    for role in allowed_roles:
        if role not in ROLES:
            raise ValueError(f"unknown role: {role}")

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(user: AuthUser, *args, **kwargs):
            if not isinstance(user, AuthUser):
                raise TypeError("first argument must be AuthUser")
            if not user.active:
                raise PermissionDenied(f"user {user.user_id} is inactive")
            if user.role not in allowed_roles:
                raise PermissionDenied(
                    f"role '{user.role}' not in allowed {allowed_roles}"
                )
            return fn(user, *args, **kwargs)

        return wrapper

    return decorator


def require_permission(action: Permission | str) -> Callable:
    perm = _normalize(action)

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(user: AuthUser, *args, **kwargs):
            if not has_permission(user, perm):
                raise PermissionDenied(
                    f"user {user.user_id} lacks {perm.value}"
                )
            return fn(user, *args, **kwargs)

        return wrapper

    return decorator


def assert_can(user: AuthUser, action: Permission | str) -> None:
    if not has_permission(user, action):
        raise PermissionDenied(f"user {user.user_id} cannot {_normalize(action).value}")
