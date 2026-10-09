# app/mcp/server.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   MCP server startup, stdio transport loop, and tool dispatch.
                  Thin shell — all business logic lives in handlers/ and core.
Owns:             _server (Server instance), _TOOLS registry, _register(),
                  get_tool(), handle_list_tools(), handle_call_tool(),
                  _startup(), main().
Public Surface:   main() — entry point for `graphyn mcp` and `python -m app.mcp.server`.
                  get_tool(name) — look up a registered tool handler dict.
Must NOT:         Contain business logic. Each handler must stay ≤ ~30 lines.
                  Must log to stderr only (stdout is JSON-RPC transport).
Dependencies:     mcp (server, types), app.mcp.auth, app.mcp.tool_registry,
                  stdlib (asyncio, json, logging, sys).
Reason To Change: MCP protocol version changes, transport changes (stdio →
                  HTTP), or tool dispatch mechanism evolves.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

# The MCP SDK is an optional extra (setup.py extras_require["mcp"]); the API
# image does not bake it (its pins conflict with FastAPI's starlette). Only the
# stdio transport needs it — the tool catalog (get_tool / _TOOLS) used
# in-process by the mcp_tool_call node must import without it.
try:
    import mcp.server.stdio
    import mcp.types as types
    from mcp.server.lowlevel import NotificationOptions, Server
    from mcp.server.models import InitializationOptions

    MCP_SDK_IMPORT_ERROR: ImportError | None = None
except ImportError as _sdk_exc:  # pragma: no cover - exercised in a subprocess test
    MCP_SDK_IMPORT_ERROR = _sdk_exc
    types = None  # type: ignore[assignment]
    NotificationOptions = InitializationOptions = None  # type: ignore[assignment]

    class Server:  # type: ignore[no-redef]
        """Stand-in so the protocol handlers below still define without the SDK."""

        def __init__(self, name: str) -> None:
            self.name = name

        def list_tools(self):
            return lambda fn: fn

        def call_tool(self):
            return lambda fn: fn

from app.mcp.auth import check_auth

log = logging.getLogger(__name__)


def _json_fallback(obj: Any) -> Any:
    """Handle mappingproxy and other non-serializable types in JSON output."""
    from types import MappingProxyType
    if isinstance(obj, MappingProxyType):
        return dict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

# ── Server instance ────────────────────────────────────────────────────────────

_server = Server("graphyn-mcp")

# ── Tool registration ──────────────────────────────────────────────────────────

_TOOLS: dict[str, dict] = {}  # name → {description, inputSchema, handler}

# Bounded executor for handler dispatch — prevents the default ThreadPoolExecutor
# from growing unbounded under sustained MCP load (max_workers=8 matches the
# number of concurrent pipeline slots in _PIPELINE_EXECUTOR).
_HANDLER_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mcp-handler")


def _register(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    handler,
) -> None:
    """Register a tool handler. Called by tool_registry.py at startup."""
    if name in _TOOLS:
        log.warning("Tool '%s' already registered — overwriting.", name)
    _TOOLS[name] = {
        "description": description,
        "inputSchema": input_schema,
        "handler": handler,
    }


def get_tool(name: str) -> dict[str, Any] | None:
    """Return the registered tool dict for *name*, registering the catalog if empty."""
    if not _TOOLS:
        from app.mcp.tool_registry import register_all_tools

        register_all_tools(_register)
    return _TOOLS.get(name)


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


def _is_error_payload(result: Any) -> bool:
    """Handlers signal failure with an ``{"error": True, ...}`` envelope."""
    return isinstance(result, dict) and result.get("error") is True


def _tool_result(payload: Any, *, is_error: bool) -> types.CallToolResult:
    """Wrap a JSON payload as a CallToolResult with an explicit ``isError``."""
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, default=_json_fallback))],
        isError=is_error,
    )


@_server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict[str, Any],
) -> types.CallToolResult:
    """Dispatch a tool invocation (Req 1.4, 1.7, 1.9, 1.11).

    Every failure — auth, unknown tool, handler exception, or a handler's
    ``{"error": True}`` envelope — is returned with ``isError=True`` so MCP
    clients / agents can distinguish it from a successful result. The JSON
    body is unchanged.
    """
    # ── Auth check ─────────────────────────────────────────────────────────────
    auth_error = check_auth(arguments, name)
    if auth_error is not None:
        log.info("tool=%s outcome=unauthorized", name)
        return _tool_result(auth_error, is_error=True)

    # ── Unknown tool ───────────────────────────────────────────────────────────
    if name not in _TOOLS:
        error = {
            "error": True,
            "error_type": "unknown_tool",
            "message": f"Tool '{name}' is not registered.",
            "available_tools": sorted(_TOOLS.keys()),
        }
        log.info("tool=%s outcome=unknown_tool", name)
        return _tool_result(error, is_error=True)

    # ── Dispatch ───────────────────────────────────────────────────────────────
    handler = _TOOLS[name]["handler"]

    def _call_with_identity():
        # Bind the caller (token → user / operator) so record_audit names them.
        from app.core.trust.identity import identity_from_credentials, reset_request_identity, set_request_identity

        meta = arguments.get("_meta") if isinstance(arguments, dict) and isinstance(arguments.get("_meta"), dict) else {}
        ident = identity_from_credentials(str(meta.get("auth_token") or "") or None)
        ident["origin"] = "mcp"
        tok = set_request_identity(ident if ident.get("token_mapped") else None)
        try:
            return handler(arguments)
        finally:
            reset_request_identity(tok)

    try:
        result = await asyncio.get_running_loop().run_in_executor(_HANDLER_EXECUTOR, _call_with_identity)
    except Exception as exc:
        error = {
            "error": True,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        log.info("tool=%s outcome=exception error_type=%s", name, type(exc).__name__)
        return _tool_result(error, is_error=True)
    if _is_error_payload(result):
        log.info(
            "tool=%s outcome=error error_type=%s",
            name,
            result.get("error_type") or "error",
        )
        return _tool_result(result, is_error=True)
    log.info("tool=%s outcome=success", name)
    return _tool_result(result, is_error=False)


# ── Startup ────────────────────────────────────────────────────────────────────

def _startup() -> None:
    """Register all tools. Exit with code 1 on any registration failure (Req 1.3)."""
    try:
        # Register domain serializers so artifact_store/pipeline_cache/checkpoint
        # can handle AudioSample objects without importing domain models (ARCH-2 fix).
        from app.models.serializers import register_builtin_serializers
        register_builtin_serializers()

        # Explicitly populate the NodeRegistry singleton after the domain serializer
        # is registered so node imports that reference AudioSample work correctly.
        from app.core.nodes import initialize_registry
        initialize_registry()

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

def _require_sdk() -> None:
    if MCP_SDK_IMPORT_ERROR is not None:
        raise RuntimeError(
            "graphyn mcp (stdio server) needs the MCP SDK: pip install -e \".[mcp]\" "
            f"(mcp==1.27.0) — {MCP_SDK_IMPORT_ERROR}"
        )


async def _run_server() -> None:
    _require_sdk()
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
    _require_sdk()
    _startup()
    try:
        asyncio.run(_run_server())
    finally:
        _HANDLER_EXECUTOR.shutdown(wait=False)


if __name__ == "__main__":
    main()
