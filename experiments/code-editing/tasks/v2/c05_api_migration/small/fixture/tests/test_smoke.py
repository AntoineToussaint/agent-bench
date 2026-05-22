"""Regression smoke tests — calling the functions must keep working."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging_helpers
import main


def test_log_helpers_dont_raise():
    logging_helpers.log_request("GET", "/x")
    logging_helpers.log_response(200, "/x")
    logging_helpers.log_error(RuntimeError("boom"))
    logging_helpers.log_audit(42, "do-thing")
    logging_helpers.log_metric("latency_ms", 12.5)


def test_handle_returns_payload():
    out = main.handle("GET", "/x", 7)
    assert out == {"method": "GET", "path": "/x"}
