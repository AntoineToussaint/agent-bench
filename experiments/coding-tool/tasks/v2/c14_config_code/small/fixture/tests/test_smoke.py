"""Regression smoke tests — must keep passing after the config extraction."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


def test_request_url_uses_base_url():
    assert app.request_url("/users") == "https://api.example.com/users"


def test_fetch_returns_dict_with_expected_keys():
    res = app.fetch("/users", retries=3)
    assert res is not None
    assert res["url"] == "https://api.example.com/users"
    assert res["timeout"] == 30


def test_default_settings_shape():
    settings = app.default_settings()
    assert settings["timeout"] == 30
    assert settings["retries"] == 3
    assert settings["base_url"] == "https://api.example.com"
