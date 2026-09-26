#!/usr/bin/env python3
"""Install only lean plugins into GRAPHYN_HOME without booting full AutoDiscovery."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path("/home/meritech/Desktop/newAudio3")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

home = ROOT / ".graphyn-mcp-lean"
home.mkdir(parents=True, exist_ok=True)
os.environ["GRAPHYN_HOME"] = str(home)
proj = home / "workspace"
proj.mkdir(parents=True, exist_ok=True)
os.environ["GRAPHYN_PROJECT_DIR"] = str(proj)
os.environ["GRAPHYN_AUTO_INSTALL_PLUGINS"] = "0"
os.environ["GRAPHYN_SKIP_PLUGIN_LOAD"] = "1"
os.environ["GRAPHYN_ISOLATED_BOOT_HEAVY"] = "0"
os.environ["GRAPHYN_ENV"] = "development"
os.environ.pop("GRAPHYN_PLUGINS_DIR", None)

from app.core.plugins.manager import PluginManager

pm = PluginManager()
srcs = [
    ROOT / "PluginPackage/Agents/llm_chat",
    ROOT / "PluginPackage/Common/send_email",
    ROOT / "PluginPackage/Common/set_map",
    ROOT / "PluginPackage/Common/python_code",
    ROOT / "PluginPackage/Common/json_transform",
    ROOT / "plugins/_agent_selftest_echo",
]
for src in srcs:
    print("install", src)
    rec = pm.install(str(src), upgrade=True)
    print("  ->", getattr(rec, "name", rec), getattr(rec, "version", ""), getattr(rec, "node_types", None))

print("installed_count", len(pm.list_installed()))
# Create local project for save_pipeline (under GRAPHYN_PROJECT_DIR)
os.environ.pop("GRAPHYN_SKIP_PLUGIN_LOAD", None)
from app.domain.project_manager import ProjectManager
pmgr = ProjectManager()
try:
    meta = pmgr.create("mcp-agentic-selftest")
    print("created_project", meta.get("name"))
except FileExistsError:
    print("project_exists")
except Exception as exc:
    # older create may not raise FileExistsError
    print("project_create", type(exc).__name__, exc)

for r in pm.list_installed():
    print(" ", r.name, r.enabled, getattr(r, "install_path", None))
