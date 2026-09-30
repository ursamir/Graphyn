"""Leftover fixes: graph-author-selected secret names never read raw process env.

Covers app/core/credentials/resolve.py (api_secret_name) and PluginPackage
nodes that take a secret/env *name* from config (http_request, http_webhook,
rag_*_connector, vector_store_*, speaker_separator, structured_llm,
asr_transcribe).
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGINS = REPO / "PluginPackage"

INTERNAL = "GRAPHYN_API_TOKEN"


@pytest.fixture
def cred_home(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "ghome"))
    monkeypatch.delenv("GRAPHYN_CREDENTIALS_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("GRAPHYN_SECRET_ENV_ALLOWLIST", raising=False)
    monkeypatch.delenv("GRAPHYN_LLM_BASE_URL_ALLOWLIST", raising=False)
    monkeypatch.setenv(INTERNAL, "internal-token-value")
    return tmp_path


def _load_plugin_class(rel_dir: str, node_type: str):
    """Import a source plugin straight from PluginPackage (no install)."""
    from app.core.nodes.discovery import AutoDiscovery
    from app.core.nodes.registry import NodeRegistry

    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    root = PLUGINS / rel_dir
    for entry in ("types.py", "nodes.py"):
        path = root / entry
        if path.is_file():
            module = disc._import_file(path, package_prefix=None)
            disc._process_module(module)
    return reg.get_class(node_type)


# ── static guard ─────────────────────────────────────────────────────────────


def _env_reads_with_dynamic_name(tree: ast.AST) -> list[int]:
    """Line numbers of os.environ.get(x)/os.getenv(x)/os.environ[x] with non-literal x."""
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            fn = node.func
            name = ""
            if isinstance(fn, ast.Attribute):
                if fn.attr == "get" and isinstance(fn.value, ast.Attribute) and fn.value.attr == "environ":
                    name = "environ.get"
                elif fn.attr == "getenv":
                    name = "getenv"
            if name and not isinstance(node.args[0], ast.Constant):
                hits.append(node.lineno)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
            if node.value.attr == "environ" and not isinstance(node.slice, ast.Constant):
                hits.append(node.lineno)
    return hits


def test_no_plugin_reads_env_by_dynamic_name():
    offenders = []
    for path in sorted(PLUGINS.rglob("nodes.py")):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line in _env_reads_with_dynamic_name(tree):
            offenders.append(f"{path.relative_to(REPO)}:{line}")
    # yolo_train reads a literal flag; asr_transcribe maps provider → fixed name.
    assert offenders == [], (
        "Plugins must resolve config-supplied secret names via "
        "app.core.trust.secrets.resolve_secret (guarded env fallback): " + ", ".join(offenders)
    )


# ── resolve_llm_credentials ──────────────────────────────────────────────────


def test_resolve_llm_credentials_refuses_internal_env_name(cred_home):
    from app.core.credentials.errors import NeedsCredentialsError
    from app.core.credentials.resolve import resolve_llm_credentials

    with pytest.raises(NeedsCredentialsError):
        resolve_llm_credentials(provider="openai_compat", api_secret_name=INTERNAL)


def test_resolve_llm_credentials_env_secret_shaped_name_ok(cred_home, monkeypatch):
    from app.core.credentials.resolve import resolve_llm_credentials

    monkeypatch.setenv("MY_LLM_API_KEY", "sk-mine")
    out = resolve_llm_credentials(provider="openai_compat", api_secret_name="MY_LLM_API_KEY")
    assert out["api_key"] == "sk-mine"


def test_resolve_llm_credentials_allowlisted_internal_name(cred_home, monkeypatch):
    from app.core.credentials.resolve import resolve_llm_credentials

    monkeypatch.setenv("GRAPHYN_SECRET_ENV_ALLOWLIST", INTERNAL)
    out = resolve_llm_credentials(provider="openai_compat", api_secret_name=INTERNAL)
    assert out["api_key"] == "internal-token-value"


# ── plugins ──────────────────────────────────────────────────────────────────


def test_http_request_auth_env_internal_refused(cred_home):
    cls = _load_plugin_class("Common/http_request", "http_request")
    node = cls(config={"url": "https://api.example.com/x", "auth_env": INTERNAL}, seed=0)
    with patch("httpx.request") as req, patch("httpx.get") as get, patch("httpx.post") as post:
        with pytest.raises(RuntimeError, match="empty"):
            node.process({"input": None})
    req.assert_not_called()
    get.assert_not_called()
    post.assert_not_called()


def test_http_request_auth_env_secret_shaped_ok(cred_home, monkeypatch):
    from app.core.trust.secrets import resolve_secret

    monkeypatch.setenv("SERVICE_TOKEN", "tok")
    assert resolve_secret("SERVICE_TOKEN") == "tok"


@pytest.mark.parametrize(
    "rel,node_type",
    [
        ("RAG/rag_slack_connector", "rag_slack_connector"),
        ("RAG/rag_notion_connector", "rag_notion_connector"),
    ],
)
def test_rag_connectors_refuse_internal_env(cred_home, rel, node_type):
    cls = _load_plugin_class(rel, node_type)
    node = cls(config={"secret_name": INTERNAL}, seed=0)
    with patch("httpx.get") as get, patch("httpx.post") as post:
        with pytest.raises(RuntimeError, match="requires env/secret"):
            node.process({})
    get.assert_not_called()
    post.assert_not_called()


def test_vector_store_write_dsn_secret_internal_refused(cred_home, monkeypatch):
    monkeypatch.delenv("PGVECTOR_DSN", raising=False)
    cls = _load_plugin_class("RAG/vector_store_write", "vector_store_write")
    node = cls(config={"pg_dsn_secret": INTERNAL}, seed=0)
    assert node._resolve_pg_dsn() == ""
    monkeypatch.setenv("PGVECTOR_DSN", "postgresql://x")
    assert node._resolve_pg_dsn() == "postgresql://x"
