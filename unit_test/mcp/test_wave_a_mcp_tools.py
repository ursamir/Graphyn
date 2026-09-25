# unit_test/mcp/test_wave_a_mcp_tools.py
"""Wave A MCP P0 tools registration + light handler smoke."""
from __future__ import annotations

import pytest

from app.mcp.tool_registry import register_all_tools

WAVE_A_TOOLS = {
    # J1
    "list_pipelines",
    "get_pipeline",
    "save_pipeline",
    "publish_pipeline",
    "promote_pipeline",
    "rollback_pipeline",
    "list_runs",
    "get_run",
    "get_run_outputs",
    "list_templates",
    "get_template",
    "instantiate_template",
    # J2
    "register_model",
    "list_models",
    "get_model",
    "request_model_prod",
    "approve_model_prod",
    "compare_runs",
    # J3
    "list_schedules",
    "upsert_schedule",
    "enable_schedule",
    "delete_schedule",
    "run_schedule_now",
    "get_webhooks",
    "put_webhooks",
    "test_webhook",
    # ops
    "get_readiness",
    # J4 ship
    "create_ship_package",
    "get_ship_package",
    "list_ship_packages",
    "download_ship_package",
    "promote_ship_package",
    # J6 audit
    "get_audit_events",
    "export_audit",
}


def test_wave_a_tools_registered(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GRAPHYN_MCP_HUMAN_APPROVAL", "1")
    names = []
    register_all_tools(lambda name, desc, schema, handler: names.append(name))
    missing = WAVE_A_TOOLS - set(names)
    assert not missing, f"Missing Wave A MCP tools: {sorted(missing)}"
    # Core 29 (with accept) + Wave A additions
    assert len(names) >= 29 + len(WAVE_A_TOOLS)


def test_get_readiness_smoke(tmp_workspace):
    from app.mcp.handlers.journey import get_readiness_handler

    out = get_readiness_handler({})
    assert "backend_mode" in out
    assert "checks" in out
    assert "ready" in out or "status" in out


def test_list_models_and_audit_smoke(tmp_workspace):
    from app.mcp.handlers.audit_ops import export_audit_handler, get_audit_events_handler
    from app.mcp.handlers.journey import list_models_handler

    models = list_models_handler({})
    assert "models" in models
    events = get_audit_events_handler({"limit": 10})
    assert "events" in events
    exported = export_audit_handler({"limit": 10})
    assert exported.get("format") == "jsonl"
    assert "content" in exported
