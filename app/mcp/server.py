# app/mcp/server.py
"""MCP server — stdio transport, tool dispatch, structured logging.

Req 1.1–1.11
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from app.mcp.auth import check_auth

log = logging.getLogger(__name__)

# ── Server instance ────────────────────────────────────────────────────────────

_server = Server("graphyn-mcp")

# ── Tool registration ──────────────────────────────────────────────────────────

_TOOLS: dict[str, dict] = {}  # name → {description, inputSchema, handler}


def _register(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    handler,
) -> None:
    """Register a tool handler. Called by tool_registry.py at startup."""
    _TOOLS[name] = {
        "description": description,
        "inputSchema": input_schema,
        "handler": handler,
    }


# ── MCP protocol handlers ──────────────────────────────────────────────────────

@_server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """Return the tool manifest (Req 1.2)."""
    return [
        types.Tool(
            name=name,
            description=info["description"],
            inputSchema=info["inputSchema"],
        )
        for name, info in _TOOLS.items()
    ]


@_server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Dispatch a tool invocation (Req 1.4, 1.7, 1.9, 1.11)."""
    # ── Auth check ─────────────────────────────────────────────────────────────
    auth_error = check_auth(arguments)
    if auth_error is not None:
        log.info("tool=%s outcome=unauthorized", name)
        return [types.TextContent(type="text", text=json.dumps(auth_error))]

    # ── Unknown tool ───────────────────────────────────────────────────────────
    if name not in _TOOLS:
        error = {
            "error": True,
            "error_type": "unknown_tool",
            "message": f"Tool '{name}' is not registered.",
            "available_tools": sorted(_TOOLS.keys()),
        }
        log.info("tool=%s outcome=unknown_tool", name)
        return [types.TextContent(type="text", text=json.dumps(error))]

    # ── Dispatch ───────────────────────────────────────────────────────────────
    handler = _TOOLS[name]["handler"]
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, lambda: handler(arguments)
        )
        log.info("tool=%s outcome=success", name)
        return [types.TextContent(type="text", text=json.dumps(result))]
    except Exception as exc:
        error = {
            "error": True,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        log.info("tool=%s outcome=error error_type=%s", name, type(exc).__name__)
        return [types.TextContent(type="text", text=json.dumps(error))]


# ── Startup ────────────────────────────────────────────────────────────────────

def _startup() -> None:
    """Register all tools. Exit with code 1 on any registration failure (Req 1.3)."""
    try:
        # Import here to avoid circular dependency at module load time
        from app.mcp.tool_registry import register_all_tools
        register_all_tools(_register)
    except Exception as exc:
        log.error("Tool registration failed: %s", exc, exc_info=True)
        sys.exit(1)

    log.info(
        "MCP server started — %d tools registered: %s",
        len(_TOOLS),
        sorted(_TOOLS.keys()),
    )


# ── Main ───────────────────────────────────────────────────────────────────────

async def _run_server() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await _server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="graphyn-mcp",
                server_version="2.0.0",
                capabilities=_server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    """Entry point for `python -m app.mcp.server` and `graphyn mcp`."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,  # Req 1.11: log to stderr, not stdout (stdout = JSON-RPC)
    )
    _startup()
    asyncio.run(_run_server())


if __name__ == "__main__":
    main()
