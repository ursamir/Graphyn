# design-02 — PluginStore and PluginManager

## Overview

`PluginStore` persists plugin state to disk. `PluginManager` orchestrates all lifecycle operations and is the single entry point for CLI, REST API, and SDK.

## PluginStore

### File: `app/core/plugins/store.py`

```python
from __future__ import annotations
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel
from app.core.plugins.errors import PluginNotFoundError

class PluginRecord(BaseModel, frozen=True):
    name: str
    version: str
    source: str
    install_path: str
    enabled: bool
    installed_at: str   # ISO 8601
    manifest: dict      # raw manifest dict

class PluginStore:
    def __init__(self, base_dir: str | None = None) -> None:
        import os
        workspace = base_dir or os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")
        self.base = Path(workspace) / "plugins"
        self.base.mkdir(parents=True, exist_ok=True)
        self._registry_path = self.base / "registry.json"
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if not self._registry_path.exists():
            return {}
        try:
            with open(self._registry_path) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, data: dict) -> None:
        tmp = self._registry_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self._registry_path)

    def get(self, name: str) -> PluginRecord:
        with self._lock:
            data = self._load()
        if name not in data:
            raise PluginNotFoundError(f"Plugin '{name}' is not installed.")
        return PluginRecord.model_validate(data[name])

    def list(self) -> list[PluginRecord]:
        with self._lock:
            data = self._load()
        return [PluginRecord.model_validate(v) for v in data.values()]

    def save(self, record: PluginRecord) -> None:
        with self._lock:
            data = self._load()
            data[record.name] = record.model_dump(mode="json")
            self._save(data)

    def delete(self, name: str) -> None:
        with self._lock:
            data = self._load()
            if name not in data:
                raise PluginNotFoundError(f"Plugin '{name}' is not installed.")
            del data[name]
            self._save(data)

    def update_enabled(self, name: str, enabled: bool) -> PluginRecord:
        with self._lock:
            data = self._load()
            if name not in data:
                raise PluginNotFoundError(f"Plugin '{name}' is not installed.")
            data[name]["enabled"] = enabled
            self._save(data)
            return PluginRecord.model_validate(data[name])
```

## PluginManager

### File: `app/core/plugins/manager.py`

```python
from __future__ import annotations
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from app.core.plugins.store import PluginStore, PluginRecord
from app.core.plugins.installer import PluginInstaller
from app.core.plugins.loader import PluginLoader
from app.core.plugins.manifest import load_manifest
from app.core.plugins.errors import PluginAlreadyInstalledError, PluginNotFoundError

log = logging.getLogger(__name__)

class PluginManager:
    def __init__(self, registry=None, base_dir: str | None = None) -> None:
        import os
        if registry is None:
            from app.core.nodes import registry as _registry
            registry = _registry
        self._registry = registry
        self._store = PluginStore(base_dir)
        self._loader = PluginLoader(registry)
        self._installer = PluginInstaller()
        self._plugins_dir = Path(os.environ.get("GRAPHYN_PLUGINS_DIR", "plugins"))

    def install(self, source: str, upgrade: bool = False) -> PluginRecord:
        plugin_dir = self._installer.resolve(source)
        manifest = load_manifest(plugin_dir)
        try:
            existing = self._store.get(manifest.name)
            if not upgrade:
                raise PluginAlreadyInstalledError(
                    f"Plugin '{manifest.name}' is already installed (v{existing.version}). "
                    "Use upgrade=True to replace it."
                )
            self.uninstall(manifest.name)
        except PluginNotFoundError:
            pass  # not installed yet — proceed

        dest = self._plugins_dir / manifest.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(plugin_dir, dest)

        node_types = self._loader.load(dest)
        record = PluginRecord(
            name=manifest.name,
            version=manifest.version,
            source=source,
            install_path=str(dest.resolve()),
            enabled=True,
            installed_at=datetime.now(timezone.utc).isoformat(),
            manifest=manifest.model_dump(mode="json"),
        )
        self._store.save(record)
        log.info("Installed plugin '%s' v%s (%d node types)", manifest.name, manifest.version, len(node_types))
        return record

    def uninstall(self, name: str) -> None:
        record = self._store.get(name)  # raises PluginNotFoundError
        self._unload_node_types(record)
        self._store.delete(name)
        install_path = Path(record.install_path)
        if install_path.exists():
            shutil.rmtree(install_path)
        log.info("Uninstalled plugin '%s'", name)

    def enable(self, name: str) -> PluginRecord:
        record = self._store.get(name)
        if not record.enabled:
            self._loader.load(Path(record.install_path))
        return self._store.update_enabled(name, True)

    def disable(self, name: str) -> PluginRecord:
        record = self._store.get(name)
        if record.enabled:
            self._unload_node_types(record)
        return self._store.update_enabled(name, False)

    def list_installed(self) -> list[PluginRecord]:
        return self._store.list()

    def get(self, name: str) -> PluginRecord:
        return self._store.get(name)  # raises PluginNotFoundError

    def load_enabled_plugins(self) -> None:
        """Called at startup to load all enabled plugins from PluginStore."""
        for record in self._store.list():
            if record.enabled:
                try:
                    self._loader.load(Path(record.install_path))
                except Exception as exc:
                    log.warning("Failed to load plugin '%s' at startup: %s", record.name, exc)

    def _unload_node_types(self, record: PluginRecord) -> None:
        manifest_data = record.manifest
        entry_points = manifest_data.get("entry_points", [])
        # Unregister node types that came from this plugin
        # We identify them by checking which node types are defined in the plugin's modules
        install_path = Path(record.install_path)
        for ep in entry_points:
            module_stem = Path(ep).stem
            module_name = f"{install_path.name}.{module_stem}"
            to_remove = [
                nt for nt, cls in self._registry._classes.items()
                if cls.__module__ == module_name
            ]
            for nt in to_remove:
                self._registry.unregister(nt)
```

## NodeRegistry Extension

Add `unregister()` to `app/core/nodes/registry.py`:

```python
def unregister(self, node_type: str) -> None:
    """Remove a node type from the registry. No-op if not registered."""
    self._classes.pop(node_type, None)
    self._metadata.pop(node_type, None)
```

## Startup Integration

In `app/core/registry_runtime.py` (or wherever `get_registry()` initializes the registry), add:

```python
# After NodeRegistry is initialized and before AutoDiscovery runs:
from app.core.plugins.manager import PluginManager
PluginManager().load_enabled_plugins()
```

## Design Decisions

1. **Atomic writes for `registry.json`**: Write to `.tmp` then `rename()` to avoid corrupt state if the process is killed mid-write.

2. **`PluginManager` is stateless except for `PluginStore`**: Each call creates fresh `PluginLoader` and `PluginInstaller` instances. This makes testing straightforward and avoids shared mutable state.

3. **`_unload_node_types` uses module name matching**: When a plugin is disabled/uninstalled, we identify its node types by checking `cls.__module__` against the expected module name. This is the same pattern `AutoDiscovery._process_module()` uses to filter classes defined in the current module.

4. **`load_enabled_plugins()` is fault-tolerant**: A plugin that fails to load at startup logs a WARNING and is skipped. The platform continues to start. This matches the existing `AutoDiscovery` behavior.
