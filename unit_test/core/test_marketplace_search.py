"""Marketplace catalog search helper (shared REST/MCP)."""
from __future__ import annotations

from app.core.templates.pipeline_template_materializer import search_marketplace_templates


def test_search_marketplace_templates_basic():
    r = search_marketplace_templates(limit=5)
    assert r["catalog_missing"] is False
    assert r["count"] <= 5
    assert r["matched"] >= r["count"]
    assert r["total_in_catalog"] >= 100
    assert isinstance(r["templates"], list)


def test_search_marketplace_pack_filter():
    # F19 (F-07): RAG pack removed on this branch; filter on a shipped pack.
    r = search_marketplace_templates(pack="Agents", limit=10)
    assert r["catalog_missing"] is False
    assert r["matched"] >= 1
    for t in r["templates"]:
        pack = str(t.get("pack") or "")
        assert pack == "Agents" or "agents" in pack.lower()


def test_search_q_substring():
    r = search_marketplace_templates(q="email-alert", limit=10)
    assert r["matched"] >= 1
    blob = " ".join(str(t.get("id") or "") + " " + str(t.get("name") or "") for t in r["templates"]).lower()
    assert "email" in blob
