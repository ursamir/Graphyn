# app/core/ir/secret_policy.py
"""
Bounded Context:  BC1 — Graph Language
Responsibility:   Fail-closed policy: reject Graph IR node configs that embed
                  secret-shaped values inline (use Secrets store / *_env instead).
Owns:             find_inline_secrets(), assert_no_inline_secrets(),
                  InlineSecretError.
Public Surface:   Same as Owns.
Must NOT:         Import app.domain, app.api, orchestrator, or plugins.
Dependencies:     re, typing; app.core.ir.models.GraphIR (optional duck typing).
Reason To Change: New forbidden key patterns or allowlist exceptions.
"""
from __future__ import annotations

import re
from types import MappingProxyType
from typing import Any, Iterable

# Exact keys and suffixes that must not carry non-empty inline secrets.
_EXACT = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "password",
        "passwd",
        "secret",
        "hmac_secret",
        "client_secret",
        "private_key",
        "token",
    }
)
_SUFFIX_RE = re.compile(
    r"(?:^|_)(api_key|apikey|access_token|auth_token|password|passwd|"
    r"secret|hmac_secret|client_secret|private_key|token)$",
    re.IGNORECASE,
)
# Keys that intentionally name an env var or secret *reference*, not a value.
_ALLOW_EXACT = frozenset(
    {
        "auth_env",
        "api_key_env",
        "token_env",
        "secret_env",
        "hmac_secret_env",
        "password_env",
        "secret_name",
        "secrets_ref",
    }
)
_ALLOW_SUFFIX = ("_env", "_secret_name", "_ref")


class InlineSecretError(ValueError):
    """Raised when Graph IR contains inline secret-shaped config values."""


def _is_forbidden_key(key: str) -> bool:
    k = key.strip()
    if not k:
        return False
    low = k.lower()
    if low in _ALLOW_EXACT:
        return False
    if any(low.endswith(suf) for suf in _ALLOW_SUFFIX):
        return False
    if low in _EXACT:
        return True
    return bool(_SUFFIX_RE.search(low))


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (bytes, bytearray)):
        return len(value) > 0
    if isinstance(value, (dict, list, tuple, set)):
        return False  # nested scanned separately; container alone is not a secret
    return True  # numbers/bools on a secret key are still rejected


def _walk_config(config: Any, path: str, hits: list[str]) -> None:
    if isinstance(config, (dict, MappingProxyType)):
        for key, val in config.items():
            if not isinstance(key, str):
                continue
            child = f"{path}.{key}" if path else key
            if _is_forbidden_key(key) and _nonempty(val) and not isinstance(
                val, (dict, list, tuple, MappingProxyType)
            ):
                hits.append(child)
            else:
                _walk_config(val, child, hits)
    elif isinstance(config, (list, tuple)):
        for i, item in enumerate(config):
            _walk_config(item, f"{path}[{i}]", hits)


def find_inline_secrets(graph: Any) -> list[str]:
    """Return dotted paths of inline secret-shaped values in node configs."""
    hits: list[str] = []
    nodes: Iterable[Any]
    if hasattr(graph, "nodes"):
        nodes = getattr(graph, "nodes") or []
    elif isinstance(graph, dict):
        nodes = graph.get("nodes") or []
    else:
        return hits

    for idx, node in enumerate(nodes):
        if hasattr(node, "config"):
            cfg = getattr(node, "config", None) or {}
            nid = getattr(node, "id", None) or getattr(node, "node_id", None) or idx
            ntype = getattr(node, "node_type", None) or "?"
        elif isinstance(node, dict):
            cfg = node.get("config") or {}
            nid = node.get("id") or node.get("node_id") or idx
            ntype = node.get("node_type") or "?"
        else:
            continue
        prefix = f"nodes[{nid}:{ntype}].config"
        _walk_config(cfg, prefix, hits)
    return hits


def assert_no_inline_secrets(graph: Any) -> None:
    """Raise InlineSecretError if any inline secrets are present."""
    hits = find_inline_secrets(graph)
    if not hits:
        return
    shown = ", ".join(hits[:8])
    more = f" (+{len(hits) - 8} more)" if len(hits) > 8 else ""
    raise InlineSecretError(
        "Inline secrets are not allowed in Graph IR. "
        f"Move values to the Secrets store or *_env fields. Found: {shown}{more}"
    )
