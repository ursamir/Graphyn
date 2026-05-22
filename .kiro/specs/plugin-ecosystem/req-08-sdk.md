# req-08 — SDK Interface

## Introduction

The SDK exposes `PluginManager` as a first-class importable class and adds a `Pipeline.install_plugin()` convenience method. This follows the Phase 1 principle that the SDK is the single source of truth for all platform operations.

## Requirement 9: SDK Interface

**User Story:** As a Python developer, I want to manage plugins programmatically through the SDK, so that I can install and configure plugins as part of my pipeline setup code.

### Acceptance Criteria

1. THE SDK SHALL expose a `PluginManager` class importable from `app.core.plugins.manager`.
2. WHEN `PluginManager.install(source, upgrade=False)` is called, THE PluginManager SHALL install the plugin from the given source and return a `PluginRecord`.
3. WHEN `PluginManager.uninstall(name)` is called, THE PluginManager SHALL uninstall the named plugin and return `None`.
4. WHEN `PluginManager.enable(name)` is called, THE PluginManager SHALL enable the named plugin and return the updated `PluginRecord`.
5. WHEN `PluginManager.disable(name)` is called, THE PluginManager SHALL disable the named plugin and return the updated `PluginRecord`.
6. WHEN `PluginManager.list_installed()` is called, THE PluginManager SHALL return a list of all `PluginRecord` objects from `PluginStore`.
7. WHEN `PluginManager.get(name)` is called for an installed plugin, THE PluginManager SHALL return the `PluginRecord` for that plugin.
8. WHEN `PluginManager.get(name)` is called for a plugin that is not installed, THE PluginManager SHALL raise a `PluginNotFoundError`.
9. THE `Pipeline` class SHALL expose a `Pipeline.install_plugin(source, upgrade=False) -> PluginRecord` convenience method that delegates to `PluginManager.install()`.

## Usage Example

```python
from app.core.plugins.manager import PluginManager
from app.core.sdk import Pipeline

# Install a plugin
manager = PluginManager()
record = manager.install("audio-denoiser")
print(f"Installed {record.name} {record.version}")

# Or via Pipeline convenience method
pipeline = Pipeline([...])
record = pipeline.install_plugin("audio-denoiser")

# List installed plugins
for r in manager.list_installed():
    print(f"{r.name} {r.version} {'enabled' if r.enabled else 'disabled'}")

# Disable a plugin
manager.disable("audio-denoiser")

# Uninstall
manager.uninstall("audio-denoiser")
```

## Implementation Notes

- `Pipeline.install_plugin()` is a thin wrapper: `return PluginManager().install(source, upgrade=upgrade)`.
- `PluginManager` is instantiated fresh per call (stateless except for `PluginStore` on disk).
- All exceptions from `PluginManager` propagate unchanged to the SDK caller.
