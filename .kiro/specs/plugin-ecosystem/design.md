# Design — Plugin Ecosystem (Phase 5)

## Overview

Phase 5 adds a structured plugin ecosystem on top of the existing `AutoDiscovery` flat-file mechanism. The design is strictly additive: no existing public API changes, no existing tests break. The new components live in `app/core/plugins/` and integrate with the existing `NodeRegistry`, `AutoDiscovery`, CLI, REST API, and SDK through well-defined extension points.

The central design principle is **layered opt-in**: a plugin author can drop a `.py` file and get the same behavior as today (legacy mode), or add a `plugin.toml` and get manifest validation, dependency checking, version compatibility, and lifecycle management (managed mode). The platform detects which mode applies automatically.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Interfaces                               │
│  CLI (plugin subcommand)  REST API (/plugins/)  SDK (Pipeline)  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ delegates to
┌──────────────────────────────▼──────────────────────────────────┐
│                       PluginManager                             │
│  install()  uninstall()  enable()  disable()  list_installed()  │
└──────┬──────────────┬──────────────┬──────────────┬────────────┘
       │              │              │              │
  PluginInstaller  PluginLoader  PluginStore  PluginIndexClient
  (fetch/extract)  (load/validate) (persist)   (browse/search)
       │              │
  PluginManifest  DependencyChecker
  (parse/validate) (check/install)
       │
  AutoDiscovery ──► NodeRegistry
  (register nodes)
```

### Component Responsibilities

| Component | File | Responsibility |
|---|---|---|
| `PluginManager` | `app/core/plugins/manager.py` | Orchestrates all lifecycle operations; single entry point for CLI/API/SDK |
| `PluginInstaller` | `app/core/plugins/installer.py` | Resolves source strings to local directories; handles Git, HTTP, local, index |
| `PluginLoader` | `app/core/plugins/loader.py` | Validates manifest, checks compatibility, checks deps, delegates to AutoDiscovery |
| `PluginStore` | `app/core/plugins/store.py` | Persists `PluginRecord` objects in `workspace/plugins/registry.json` |
| `PluginIndexClient` | `app/core/plugins/index.py` | Fetches and searches the plugin index |
| `PluginManifest` | `app/core/plugins/manifest.py` | Pydantic model + parser for `plugin.toml` / `plugin.json` |
| `DependencyChecker` | `app/core/plugins/dependencies.py` | Checks PEP 508 deps against current environment; optional auto-install |
| Plugin errors | `app/core/plugins/errors.py` | All plugin exception classes |
| `app/core/plugins/__init__.py` | `app/core/plugins/__init__.py` | Package init; exports public API |

## Components and Interfaces

### PluginManifest (`app/core/plugins/manifest.py`)

```python
class PluginManifest(BaseModel):
    name: str                          # slug: ^[a-z][a-z0-9_-]*$
    version: str                       # PEP 440 version
    description: str
    author: str
    platform_version: str              # PEP 440 specifier, e.g. ">=5.0,<6.0"
    entry_points: list[str]            # ["module.py", ...]
    tags: list[str] = []
    dependencies: list[str] = []       # PEP 508 requirements
    homepage: str | None = None
    license: str | None = None
    min_python: str | None = None

def load_manifest(plugin_dir: Path) -> PluginManifest:
    """Parse plugin.toml (preferred) or plugin.json from plugin_dir.
    Raises PluginManifestError on parse or validation failure."""
```

### PluginLoader (`app/core/plugins/loader.py`)

```python
class PluginLoader:
    def __init__(self, registry: NodeRegistry) -> None: ...

    def load(self, plugin_dir: Path) -> list[str]:
        """Load a manifest-based plugin. Returns list of registered node_types.
        Raises PluginManifestError, PluginCompatibilityError, PluginDependencyError."""
        # 1. load_manifest(plugin_dir)
        # 2. check platform version compatibility
        # 3. check Python version compatibility (if min_python set)
        # 4. DependencyChecker.check(manifest.dependencies)
        # 5. For each entry_point: AutoDiscovery._import_file() + _process_module()
        # 6. Return list of newly registered node_types
```

### PluginStore (`app/core/plugins/store.py`)

```python
class PluginRecord(BaseModel, frozen=True):
    name: str
    version: str
    source: str
    install_path: str
    enabled: bool
    installed_at: str   # ISO 8601
    manifest: dict

class PluginStore:
    def __init__(self, base_dir: str | None = None) -> None: ...
    def get(self, name: str) -> PluginRecord: ...          # raises PluginNotFoundError
    def list(self) -> list[PluginRecord]: ...
    def save(self, record: PluginRecord) -> None: ...
    def delete(self, name: str) -> None: ...
    def update_enabled(self, name: str, enabled: bool) -> PluginRecord: ...
```

### PluginManager (`app/core/plugins/manager.py`)

```python
class PluginManager:
    def __init__(self, registry: NodeRegistry | None = None,
                 base_dir: str | None = None) -> None: ...

    def install(self, source: str, upgrade: bool = False) -> PluginRecord: ...
    def uninstall(self, name: str) -> None: ...
    def enable(self, name: str) -> PluginRecord: ...
    def disable(self, name: str) -> PluginRecord: ...
    def list_installed(self) -> list[PluginRecord]: ...
    def get(self, name: str) -> PluginRecord: ...
    def load_enabled_plugins(self) -> None: ...  # called at startup
```

### PluginInstaller (`app/core/plugins/installer.py`)

```python
class PluginInstaller:
    def resolve(self, source: str, version_constraint: str | None = None) -> Path:
        """Resolve source to a local plugin directory. Caller owns cleanup."""

    def _resolve_git(self, url: str) -> Path: ...
    def _resolve_http_archive(self, url: str) -> Path: ...
    def _resolve_index(self, name: str, version: str | None) -> Path: ...
    def _resolve_local_dir(self, path: Path) -> Path: ...
    def _resolve_local_archive(self, path: Path) -> Path: ...
```

### PluginIndexClient (`app/core/plugins/index.py`)

```python
class PluginIndexEntry(BaseModel):
    name: str
    version: str
    description: str
    author: str
    tags: list[str]
    platform_version: str
    download_url: str
    homepage: str | None = None
    checksum: str | None = None

class PluginIndexClient:
    def fetch(self) -> list[PluginIndexEntry]: ...
    def search(self, query: str) -> list[PluginIndexEntry]: ...
    def lookup(self, name: str, version: str | None = None) -> PluginIndexEntry: ...
```

### Error Hierarchy (`app/core/plugins/errors.py`)

```python
class PluginError(Exception): ...
class PluginManifestError(PluginError, ValueError): ...
class PluginCompatibilityError(PluginError): ...
class PluginDependencyError(PluginError): ...
class PluginInstallError(PluginError): ...
class PluginNotFoundError(PluginError, KeyError): ...
class PluginAlreadyInstalledError(PluginError): ...
class PluginIndexError(PluginError): ...
```

## Data Models

### `plugin.toml` Schema

```toml
[plugin]
name = "audio-denoiser"           # required, slug
version = "1.2.0"                 # required, PEP 440
description = "..."               # required
author = "Jane Smith"             # required
platform_version = ">=5.0,<6.0"  # required, PEP 440 specifier
entry_points = ["denoiser.py"]    # required, min 1 entry

# optional
tags = ["audio", "denoising"]
dependencies = ["scipy>=1.10", "numpy>=1.24"]
homepage = "https://github.com/..."
license = "MIT"
min_python = "3.10"
```

### `workspace/plugins/registry.json`

```json
{
  "audio-denoiser": {
    "name": "audio-denoiser",
    "version": "1.2.0",
    "source": "audio-denoiser",
    "install_path": "/abs/path/to/plugins/audio-denoiser",
    "enabled": true,
    "installed_at": "2025-01-15T10:30:00Z",
    "manifest": { ... }
  }
}
```

### Plugin Index Format

```json
{
  "schema_version": "1.0",
  "plugins": [
    {
      "name": "audio-denoiser",
      "version": "1.2.0",
      "description": "Spectral subtraction denoiser.",
      "author": "Jane Smith",
      "tags": ["audio", "denoising"],
      "platform_version": ">=5.0,<6.0",
      "download_url": "https://example.com/audio-denoiser-1.2.0.zip",
      "checksum": "sha256:abc123..."
    }
  ]
}
```

### Workspace Layout (additions)

```
workspace/
└── plugins/
    ├── registry.json          # PluginStore persistence
    └── index.json             # optional local plugin index
plugins/                       # GRAPHYN_PLUGINS_DIR (default)
├── legacy_plugin.py           # legacy flat-file plugin (unchanged)
└── audio-denoiser/            # managed plugin package
    ├── plugin.toml
    └── denoiser.py
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Manifest Round-Trip

*For any* valid `PluginManifest` object, serializing it to a TOML string and parsing it back SHALL produce an equivalent `PluginManifest` with all fields equal to the original.

**Validates: Requirements 1.1, 1.3**

### Property 2: Invalid Manifest Always Rejected

*For any* manifest dict that violates at least one validation rule (missing required field, invalid slug, malformed PEP 440 version, malformed PEP 440 specifier, malformed PEP 508 dependency), parsing SHALL raise `PluginManifestError`.

**Validates: Requirements 1.4, 1.5, 1.7, 1.8, 1.9, 3.8**

### Property 3: Platform Version Compatibility Correctness

*For any* platform version string `v` and version constraint string `c`, `PluginLoader` SHALL accept the plugin if and only if `packaging.version.Version(v) in packaging.specifiers.SpecifierSet(c)`.

**Validates: Requirements 2.2**

### Property 4: Dependency Reporting Completeness

*For any* list of dependency requirement strings where a subset is unsatisfied, `DependencyChecker.check()` SHALL raise `PluginDependencyError` whose reported unsatisfied set equals exactly the set of unsatisfied requirements (no false positives, no false negatives).

**Validates: Requirements 3.1, 3.2**

### Property 5: PluginStore Round-Trip

*For any* `PluginRecord`, saving it to `PluginStore` and then loading it back SHALL produce an equal `PluginRecord` with all fields preserved.

**Validates: Requirements 4.1, 4.2**

### Property 6: Enable/Disable Toggles State Correctly

*For any* installed plugin, the sequence disable → enable SHALL result in `enabled=True`, and the sequence enable → disable SHALL result in `enabled=False`. The `enabled` field in `PluginStore` SHALL always reflect the last operation.

**Validates: Requirements 4.4, 4.5**

### Property 7: Search Results Are a Subset Matching the Query

*For any* plugin index (list of `PluginIndexEntry` objects) and any non-empty query string, `PluginIndexClient.search(query)` SHALL return a list where every entry contains the query string (case-insensitive) in at least one of `name`, `description`, or `tags`, and no matching entry from the index is omitted.

**Validates: Requirements 6.5**

### Property 8: Checksum Verification Correctness

*For any* byte sequence `data`, computing `sha256(data)` and then verifying `data` against that checksum SHALL pass. Verifying `data` against any other checksum string SHALL fail.

**Validates: Requirements 6.6**

### Property 9: Installed Plugins API Round-Trip

*For any* set of installed plugins, `GET /api/v1/plugins` SHALL return a JSON array whose length equals the number of installed plugins and whose entries contain the correct `name` and `version` for each installed plugin.

**Validates: Requirements 8.2**

## Error Handling

### Error Propagation Strategy

All plugin errors are subclasses of `PluginError`. The error hierarchy is designed so that callers can catch at different levels of specificity:

```python
try:
    manager.install(source)
except PluginCompatibilityError as e:
    # Platform version mismatch — user needs to upgrade platform or use older plugin
except PluginDependencyError as e:
    # Missing Python packages — user needs to install deps or set GRAPHYN_PLUGIN_AUTO_INSTALL=1
except PluginInstallError as e:
    # Network/git/archive failure — transient or source problem
except PluginError as e:
    # Any other plugin error
```

### Error Messages

All error messages must include:
- The plugin name (when known)
- The specific field or constraint that failed
- The actual value that was rejected
- A suggestion for how to fix the issue

Example: `PluginCompatibilityError: Plugin 'audio-denoiser' requires platform >=5.0,<6.0 but current platform is 4.3.1. Upgrade the platform or use an older version of the plugin.`

### Startup Failure Isolation

Plugin load failures at startup are isolated: a failing plugin logs a WARNING and is skipped. The platform continues to start. This matches the existing `AutoDiscovery` behavior for import errors.

## Testing Strategy

### Unit Tests

Unit tests cover specific examples, edge cases, and error conditions:

- `tests/test_plugin_manifest.py` — manifest parsing, validation, error cases
- `tests/test_plugin_loader.py` — compatibility checking, dependency checking, node registration
- `tests/test_plugin_store.py` — CRUD operations, thread safety, corrupt file handling
- `tests/test_plugin_manager.py` — install/enable/disable/uninstall lifecycle
- `tests/test_plugin_installer.py` — source string routing, archive extraction, cleanup
- `tests/test_plugin_index.py` — index fetch, search, lookup
- `tests/test_plugins_api.py` — REST API endpoints
- `tests/test_plugins_cli.py` — CLI subcommands
- `tests/test_plugin_backward_compat.py` — legacy flat-file plugins still work

### Property-Based Tests (Hypothesis)

Property tests use `hypothesis` (already a project dependency) with `@settings(max_examples=100)`:

- `tests/test_plugin_properties.py` — all 9 correctness properties above

Each property test is tagged with:
```python
# Feature: plugin-ecosystem, Property N: <property_text>
```

### Test Configuration

- All tests use `tmp_path` fixture for workspace isolation
- `monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))` for workspace override
- `monkeypatch.setenv("GRAPHYN_PLUGINS_DIR", str(tmp_path / "plugins"))` for plugin dir override
- Network calls in `PluginInstaller` and `PluginIndexClient` are mocked with `httpx_mock` or `unittest.mock.patch`
- Git operations are mocked with `unittest.mock.patch("subprocess.run")`

### Regression Baseline

All existing tests must continue to pass. Run `venv/bin/pytest tests/ -x --tb=short -q` after each task group to verify.
