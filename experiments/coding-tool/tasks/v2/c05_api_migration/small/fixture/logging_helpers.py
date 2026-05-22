"""Small set of event-logging helpers — toy size."""

from __future__ import annotations


def log_request(method, path):
    print(f"REQ {method} {path}")


def log_response(status, path):
    print(f"RES {status} {path}")


def log_error(exc):
    print(f"ERR {exc!r}")


def log_audit(user_id, action):
    print(f"AUDIT user={user_id} action={action}")


def log_metric(name, value):
    print(f"METRIC {name}={value}")
