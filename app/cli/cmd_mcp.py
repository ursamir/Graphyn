# app/cli/cmd_mcp.py
"""
Bounded Context:  CLI Interface
Responsibility:   mcp subcommand. Starts the stdio MCP server.
Owns:             cmd_mcp
Public Surface:   cmd_mcp
Must NOT:         Contain pipeline execution logic. Must not import app.api.
Dependencies:     app.core.sdk and the core package each command calls.
Reason To Change: That subcommand's flags or output change.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import yaml

def cmd_mcp(args):
    """Launch the MCP server (stdio transport) in-process."""
    from app.mcp.server import main
    main()
