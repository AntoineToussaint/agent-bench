"""Offline tests for the embedding retriever's token-truncation (no network).

Locks the fix for the bug that 30k-char inputs exceed the embedding model's
8192-token cap on dense code: `_truncate` must keep inputs within the limit.
"""

from __future__ import annotations

from file_localization.retrievers.embedding import _MAX_TOKENS, _truncate


def test_truncate_keeps_short_text_unchanged():
    s = "def f():\n    return 1\n"
    assert _truncate(s) == s


def test_truncate_caps_long_text_under_token_limit():
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    # ~50k tokens of distinct-ish content
    long = " ".join(f"symbol_{i}" for i in range(50_000))
    out = _truncate(long)
    assert len(enc.encode(out)) <= _MAX_TOKENS


def test_truncate_never_exceeds_model_cap_even_dense():
    # Worst case: a char that tokenizes ~1:1 still can't exceed the cap, because
    # token count <= char count and the cap (8000) < model max (8192).
    out = _truncate("x" * 200_000)
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    assert len(enc.encode(out)) <= 8192
