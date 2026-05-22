"""Canonical solution for c05_api_migration / small."""

from __future__ import annotations

from pathlib import Path


LOGGING_HELPERS_NEW = '''"""Small set of event-logging helpers — toy size."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def log_request(method, path):
    logger.info(f"REQ {method} {path}")


def log_response(status, path):
    logger.info(f"RES {status} {path}")


def log_error(exc):
    logger.info(f"ERR {exc!r}")


def log_audit(user_id, action):
    logger.info(f"AUDIT user={user_id} action={action}")


def log_metric(name, value):
    logger.info(f"METRIC {name}={value}")
'''


MAIN_NEW = '''"""Tiny entry point that uses the logging helpers."""

from __future__ import annotations

import logging

from logging_helpers import log_audit, log_request

logger = logging.getLogger(__name__)


def handle(method, path, user_id):
    logger.info(f"handling {method} {path}")
    log_request(method, path)
    log_audit(user_id, f"{method}:{path}")
    return {"method": method, "path": path}
'''


def apply(workdir: Path) -> None:
    (workdir / "logging_helpers.py").write_text(LOGGING_HELPERS_NEW, encoding="utf-8")
    (workdir / "main.py").write_text(MAIN_NEW, encoding="utf-8")
