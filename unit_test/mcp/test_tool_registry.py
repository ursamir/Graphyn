# unit_test/mcp/test_tool_registry.py
"""Tests for app/mcp/tool_registry.py — Req 25 criteria 6–8."""
from __future__ import annotations

from app.mcp.tool_registry import register_all_tools

EXPECTED_TOOL_NAMES = {
    "list_nodes",
    "generate_graph",
    "validate_graph",
    "get_graph_schema",
    "get_graph_capability_summary",
    "get_event_schema",
    "execute_pipeline",
    "inspect_run",
    "pause_run",
    "resume_run",
    "cancel_run",
    "list_artifacts",
    "get_artifact_lineage",
    "replay_run",
    "optimize_execution",
}


def test_register_all_tools_calls_register_15_times():
    """Req 25.6 — register_all_tools calls register_fn exactly 15 times."""
    calls = []
    register_all_tools(lambda name, desc, schema, handler: calls.append(name))
    assert len(calls) == 15, f"Expected 15 calls, got {len(calls)}: {calls}"


def test_register_all_tools_correct_names():
    """Req 25.7 — registered tool names match the expected 15 names exactly."""
    registered = []
    register_all_tools(lambda name, desc, schema, handler: registered.append(name))
    assert set(registered) == EXPECTED_TOOL_NAMES, (
        f"Unexpected tools: {set(registered) - EXPECTED_TOOL_NAMES}\n"
        f"Missing tools: {EXPECTED_TOOL_NAMES - set(registered)}"
    )


def test_register_all_tools_non_empty_descriptions():
    """Req 25.8 — each tool registration passes a non-empty description string."""
    descriptions = []
    register_all_tools(lambda name, desc, schema, handler: descriptions.append(desc))
    for i, desc in enumerate(descriptions):
        assert isinstance(desc, str) and desc.strip(), (
            f"Tool #{i} has empty description: {desc!r}"
        )


def test_register_all_tools_non_empty_schemas():
    """Req 25.8 — each tool registration passes a non-empty input schema dict."""
    schemas = []
    register_all_tools(lambda name, desc, schema, handler: schemas.append(schema))
    for i, schema in enumerate(schemas):
        assert isinstance(schema, dict) and schema, (
            f"Tool #{i} has empty schema: {schema!r}"
        )


def test_register_all_tools_handlers_are_callable():
    """Each registered handler is callable."""
    handlers = []
    register_all_tools(lambda name, desc, schema, handler: handlers.append(handler))
    for i, handler in enumerate(handlers):
        assert callable(handler), f"Tool #{i} handler is not callable: {handler!r}"
