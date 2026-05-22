# design-04 — CLI, REST API, and SDK

## Overview

This document details the CLI subcommand group, REST API router, and SDK additions for plugin management. All three interfaces delegate to `PluginManager`.

## CLI (`app/cli/main.py`)

### New subcommand group: `audiobuilder plugin`

```python
def cmd_plugin_install(args):
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError
    try:
        manager = PluginManager()
        record = manager.install(args.source, upgrade=getattr(args, "upgrade", False))
        print(f"✓ Installed {record.name} {record.version}")
        sys.exit(0)
    except PluginError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)

def cmd_plugin_list(args):
    from app.core.plugins.manager import PluginManager
    manager = PluginManager()
    records = manager.list_installed()
    enabled_only = getattr(args, "enabled", False)
    if enabled_only:
        records = [r for r in records if r.enabled]
    if not records:
        print("No plugins installed.")
        sys.exit(0)
    col_name, col_ver, col_status, col_src = 25, 10, 10, 40
    header = f"{'NAME':<{col_name}}  {'VERSION':<{col_ver}}  {'STATUS':<{col_status}}  SOURCE"
    print(header)
    print("-" * len(header))
    for r in sorted(records, key=lambda r: r.name):
        status = "enabled" if r.enabled else "disabled"
        src = r.source[:col_src]
        print(f"{r.name:<{col_name}}  {r.version:<{col_ver}}  {status:<{col_status}}  {src}")
    sys.exit(0)

def cmd_plugin_enable(args):
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError
    try:
        record = PluginManager().enable(args.name)
        print(f"✓ Enabled {record.name}")
        sys.exit(0)
    except PluginError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)

def cmd_plugin_disable(args):
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError
    try:
        record = PluginManager().disable(args.name)
        print(f"✓ Disabled {record.name}")
        sys.exit(0)
    except PluginError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)

def cmd_plugin_remove(args):
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.errors import PluginError
    try:
        PluginManager().uninstall(args.name)
        print(f"✓ Removed {args.name}")
        sys.exit(0)
    except PluginError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)

def cmd_plugin_search(args):
    from app.core.plugins.index import PluginIndexClient
    from app.core.plugins.errors import PluginError
    try:
        results = PluginIndexClient().search(args.query)
    except PluginError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)
    if not results:
        print(f"No plugins found matching '{args.query}'.")
        sys.exit(0)
    col_name, col_ver, col_desc = 25, 10, 45
    header = f"{'NAME':<{col_name}}  {'VERSION':<{col_ver}}  {'DESCRIPTION':<{col_desc}}  TAGS"
    print(header)
    print("-" * len(header))
    for e in results:
        desc = e.description[:col_desc]
        tags = ", ".join(e.tags)
        print(f"{e.name:<{col_name}}  {e.version:<{col_ver}}  {desc:<{col_desc}}  {tags}")
    sys.exit(0)

def cmd_plugin_info(args):
    import json
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.index import PluginIndexClient
    from app.core.plugins.errors import PluginNotFoundError
    try:
        record = PluginManager().get(args.name)
        print(json.dumps(record.model_dump(mode="json"), indent=2))
        sys.exit(0)
    except PluginNotFoundError:
        pass
    try:
        results = PluginIndexClient().search(args.name)
        matches = [e for e in results if e.name == args.name]
        if matches:
            print(json.dumps(matches[0].model_dump(mode="json"), indent=2))
            sys.exit(0)
    except Exception:
        pass
    print(f"Plugin '{args.name}' not found (not installed and not in index).", file=sys.stderr)
    sys.exit(1)
```

### Parser additions in `build_parser()`

```python
plugin_parser = subparsers.add_parser("plugin", help="Manage plugins")
plugin_sub = plugin_parser.add_subparsers(dest="plugin_command", metavar="ACTION")
plugin_sub.required = True

p_install = plugin_sub.add_parser("install", help="Install a plugin")
p_install.add_argument("source", help="Source: name, git URL, HTTP URL, or local path")
p_install.add_argument("--upgrade", action="store_true", default=False)
p_install.set_defaults(func=cmd_plugin_install)

p_list = plugin_sub.add_parser("list", help="List installed plugins")
p_list.add_argument("--enabled", action="store_true", default=False)
p_list.set_defaults(func=cmd_plugin_list)

p_enable = plugin_sub.add_parser("enable", help="Enable a plugin")
p_enable.add_argument("name")
p_enable.set_defaults(func=cmd_plugin_enable)

p_disable = plugin_sub.add_parser("disable", help="Disable a plugin")
p_disable.add_argument("name")
p_disable.set_defaults(func=cmd_plugin_disable)

p_remove = plugin_sub.add_parser("remove", help="Uninstall a plugin")
p_remove.add_argument("name")
p_remove.set_defaults(func=cmd_plugin_remove)

p_search = plugin_sub.add_parser("search", help="Search the plugin index")
p_search.add_argument("query")
p_search.set_defaults(func=cmd_plugin_search)

p_info = plugin_sub.add_parser("info", help="Show plugin details")
p_info.add_argument("name")
p_info.set_defaults(func=cmd_plugin_info)
```

## REST API (`app/api/routers/plugins.py`)

```python
from __future__ import annotations
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from app.core.plugins.manager import PluginManager
from app.core.plugins.index import PluginIndexClient
from app.core.plugins.errors import (
    PluginNotFoundError, PluginAlreadyInstalledError,
    PluginCompatibilityError, PluginDependencyError,
    PluginInstallError, PluginIndexError,
)

router = APIRouter(prefix="/plugins", tags=["plugins"])

_ERROR_STATUS = {
    PluginNotFoundError: 404,
    PluginAlreadyInstalledError: 409,
    PluginCompatibilityError: 422,
    PluginDependencyError: 422,
    PluginInstallError: 502,
    PluginIndexError: 502,
}

def _handle(exc: Exception) -> HTTPException:
    status = next((v for k, v in _ERROR_STATUS.items() if isinstance(exc, k)), 500)
    return HTTPException(status_code=status, detail={
        "error": type(exc).__name__,
        "detail": str(exc),
    })

class InstallRequest(BaseModel):
    source: str
    upgrade: bool = False

@router.get("")
def list_plugins():
    return [r.model_dump(mode="json") for r in PluginManager().list_installed()]

@router.post("/install")
def install_plugin(req: InstallRequest, background_tasks: BackgroundTasks):
    # For remote sources, install asynchronously
    is_remote = req.source.startswith(("http://", "https://", "git+")) or req.source.endswith(".git")
    if is_remote:
        # Resolve name from source for immediate response
        name = req.source.split("/")[-1].replace(".git", "").split("==")[0]
        background_tasks.add_task(PluginManager().install, req.source, req.upgrade)
        return {"status": "installing", "name": name}
    try:
        record = PluginManager().install(req.source, upgrade=req.upgrade)
        return {"name": record.name, "version": record.version, "status": "installed"}
    except Exception as exc:
        raise _handle(exc)

@router.get("/search")
def search_plugins(q: str = ""):
    try:
        return [e.model_dump(mode="json") for e in PluginIndexClient().search(q)]
    except Exception as exc:
        raise _handle(exc)

@router.get("/{name}")
def get_plugin(name: str):
    try:
        return PluginManager().get(name).model_dump(mode="json")
    except Exception as exc:
        raise _handle(exc)

@router.post("/{name}/enable")
def enable_plugin(name: str):
    try:
        record = PluginManager().enable(name)
        return {"name": record.name, "enabled": True}
    except Exception as exc:
        raise _handle(exc)

@router.post("/{name}/disable")
def disable_plugin(name: str):
    try:
        record = PluginManager().disable(name)
        return {"name": record.name, "enabled": False}
    except Exception as exc:
        raise _handle(exc)

@router.delete("/{name}")
def uninstall_plugin(name: str):
    try:
        PluginManager().uninstall(name)
        return {"name": name, "status": "uninstalled"}
    except Exception as exc:
        raise _handle(exc)
```

### Registration in `app/api/main.py`

```python
from app.api.routers.plugins import router as plugins_router
app.include_router(plugins_router, prefix="/api/v1", dependencies=_deps)
```

## SDK (`app/core/sdk.py`)

Add to `Pipeline` class:

```python
def install_plugin(self, source: str, upgrade: bool = False) -> "PluginRecord":
    """Install a plugin from source. Convenience wrapper for PluginManager.install().

    Args:
        source: Plugin source — name, git URL, HTTP URL, or local path.
        upgrade: If True, replace an existing installation of the same plugin.

    Returns:
        PluginRecord for the installed plugin.
    """
    from app.core.plugins.manager import PluginManager
    return PluginManager().install(source, upgrade=upgrade)
```

## Design Decisions

1. **Async install for remote sources**: Remote installs (git, HTTP) can take seconds. The REST API returns immediately with `{"status": "installing"}` and runs the install in a `BackgroundTask`. The client polls `GET /plugins/{name}` to check completion.

2. **Synchronous install for local sources**: Local directory and plain-name installs are fast enough to be synchronous in the REST API.

3. **`PluginManager` is instantiated per request**: This avoids shared mutable state between requests. The `PluginStore` handles thread safety internally.

4. **Error mapping table**: The `_ERROR_STATUS` dict maps exception types to HTTP status codes. This is cleaner than a chain of `isinstance` checks and makes it easy to add new error types.
