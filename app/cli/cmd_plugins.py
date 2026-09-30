# app/cli/cmd_plugins.py
"""
Bounded Context:  CLI Interface
Responsibility:   plugin install/list/enable/disable/remove/search/info subcommands.
Owns:             cmd_plugin_*
Public Surface:   cmd_plugin_*
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

def cmd_plugin_install(args):
    """Install a plugin from a source string."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError

    try:
        record = PluginManager().install(args.source, upgrade=args.upgrade)
        print(f"✓ Installed {record.name} v{record.version}")
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_plugin_list(args):
    """Print a table of installed plugins."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError

    try:
        records = PluginManager().list_installed()
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "enabled", False):
        records = [r for r in records if r.enabled]

    if not records:
        print("No plugins installed.")
        return

    col_name = 20
    col_ver = 10
    col_status = 10
    col_source = 30

    header = (
        f"{'NAME':<{col_name}}  "
        f"{'VERSION':<{col_ver}}  "
        f"{'STATUS':<{col_status}}  "
        f"{'SOURCE':<{col_source}}"
    )
    print(header)
    print("-" * len(header))

    for record in records:
        name = str(record.name)[:col_name]
        version = str(record.version)[:col_ver]
        status = "enabled" if record.enabled else "disabled"
        source = str(record.source)[:col_source]
        print(
            f"{name:<{col_name}}  "
            f"{version:<{col_ver}}  "
            f"{status:<{col_status}}  "
            f"{source:<{col_source}}"
        )


def cmd_plugin_enable(args):
    """Enable an installed plugin."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError

    try:
        PluginManager().enable(args.name)
        print(f"✓ Enabled {args.name}")
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_plugin_disable(args):
    """Disable an installed plugin."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError

    try:
        PluginManager().disable(args.name)
        print(f"✓ Disabled {args.name}")
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_plugin_remove(args):
    """Uninstall an installed plugin."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError

    try:
        PluginManager().uninstall(args.name)
        print(f"✓ Removed {args.name}")
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_plugin_search(args):
    """Search the plugin index."""
    from app.core.plugins.index import PluginIndexClient
    from app.core.plugins.errors import PluginError

    try:
        results = PluginIndexClient().search(args.query)
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("No plugins found.")
        return

    col_name = 20
    col_ver = 10
    col_desc = 40
    col_tags = 30

    header = (
        f"{'NAME':<{col_name}}  "
        f"{'VERSION':<{col_ver}}  "
        f"{'DESCRIPTION':<{col_desc}}  "
        f"{'TAGS':<{col_tags}}"
    )
    print(header)
    print("-" * len(header))

    for entry in results:
        name = str(entry.name)[:col_name]
        version = str(entry.version)[:col_ver]
        desc = str(entry.description)
        desc = (desc[:col_desc - 1] + "…") if len(desc) > col_desc else desc
        tags = ", ".join(entry.tags)[:col_tags]
        print(
            f"{name:<{col_name}}  "
            f"{version:<{col_ver}}  "
            f"{desc:<{col_desc}}  "
            f"{tags:<{col_tags}}"
        )


def cmd_plugin_info(args):
    """Print full info for a plugin (installed or from index)."""
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.index import PluginIndexClient
    from app.core.plugins.errors import PluginError, PluginNotFoundError

    # Try installed first
    try:
        record = PluginManager().get(args.name)
        print(json.dumps(record.model_dump(mode="json"), indent=2))
        return
    except PluginNotFoundError:
        pass
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Fall back to index lookup
    try:
        entry = PluginIndexClient().lookup(args.name)
        print(json.dumps(entry.model_dump(mode="json"), indent=2))
    except PluginNotFoundError:
        print(f"Error: Plugin '{args.name}' not found (not installed and not in index).", file=sys.stderr)
        sys.exit(1)
    except PluginError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
