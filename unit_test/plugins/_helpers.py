# unit_test/plugins/_helpers.py
"""Helpers for plugin unit tests (isolated stubs vs real process classes)."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def materialize_isolated_class(stub_cls: type) -> type:
    """Return a real Node class for process() unit tests.

    Isolated plugin installs register host stubs whose ``process()`` refuses
    in-process execution. Metadata/construct tests can use the stub; smoke
    ``process()`` tests need the real class loaded from the install path via
    the same ``AutoDiscovery`` import path the in-process loader uses.
    """
    if not getattr(stub_cls, "_graphyn_isolated", False):
        return stub_cls
    install_path = getattr(stub_cls, "_graphyn_plugin_install_path", None)
    node_type = getattr(stub_cls, "node_type", None)
    if not install_path or not node_type:
        return stub_cls

    from app.core.nodes.discovery import AutoDiscovery
    from app.core.nodes.registry import NodeRegistry

    root = Path(install_path)
    reg = NodeRegistry()
    discovery = AutoDiscovery(reg)
    for entry in ("types.py", "nodes.py"):
        path = root / entry
        if not path.is_file():
            continue
        try:
            module = discovery._import_file(path, package_prefix=None)
            discovery._process_module(module)
        except Exception:
            continue
    try:
        return reg.get_class(node_type)
    except Exception:
        return stub_cls


def install_plugin(mgr: Any, source: str, **kwargs: Any) -> Any:
    """Install a plugin; treat already-installed (after reload) as success."""
    from app.core.plugins.errors import PluginAlreadyInstalledError

    try:
        return mgr.install(source, **kwargs)
    except PluginAlreadyInstalledError:
        return None
