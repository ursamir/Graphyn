# unit_test/core/test_secret_policy.py
"""Unit tests for Graph IR inline secret policy."""
from __future__ import annotations

import pytest

from app.core.ir.secret_policy import (
    InlineSecretError,
    assert_no_inline_secrets,
    find_inline_secrets,
)


def test_allows_auth_env_reference():
    graph = {
        "nodes": [
            {"id": "a", "node_type": "http_request", "config": {"auth_env": "MY_TOKEN", "url": "https://x"}}
        ]
    }
    assert find_inline_secrets(graph) == []
    assert_no_inline_secrets(graph)


def test_rejects_inline_api_key_on_loaded_graph():
    from app.core.ir.loader import load_ir

    graph = load_ir(
        {
            "schema_version": "1.0",
            "metadata": {"name": "x", "seed": 1},
            "nodes": [
                {
                    "id": "a",
                    "node_type": "http_request",
                    "config": {"api_key": "sk-abc", "url": "https://x"},
                }
            ],
            "edges": [],
        }
    )
    with pytest.raises(InlineSecretError):
        assert_no_inline_secrets(graph)


def test_rejects_hmac_secret_suffix():
    graph = {
        "nodes": [
            {"id": "a", "node_type": "webhook", "config": {"hmac_secret": "shh"}}
        ]
    }
    with pytest.raises(InlineSecretError):
        assert_no_inline_secrets(graph)
