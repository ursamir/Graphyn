# app/mcp/__init__.py
"""
Bounded Context:  MCP Server
Responsibility:   MCP package marker. The stdio server lives in server.py.
Owns:             Nothing at import time.
Public Surface:   app.mcp.server:main, app.mcp.tool_registry, app.mcp.handlers
Must NOT:         Import the server or tool registry here.
Dependencies:     None.
Reason To Change: The MCP entry point moves.
"""
