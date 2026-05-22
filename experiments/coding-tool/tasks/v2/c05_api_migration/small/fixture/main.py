"""Tiny entry point that uses the logging helpers."""

from __future__ import annotations

from logging_helpers import log_audit, log_request


def handle(method, path, user_id):
    print(f"handling {method} {path}")
    log_request(method, path)
    log_audit(user_id, f"{method}:{path}")
    return {"method": method, "path": path}
