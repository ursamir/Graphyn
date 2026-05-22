# design-01 — Manifest and Loader

## Overview

This document details the design of `PluginManifest`, `PluginManifestError`, and `PluginLoader` — the components responsible for parsing, validating, and loading manifest-based plugins.

## PluginManifest

### File: `app/core/plugins/manifest.py`

```python
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
from pydantic import BaseModel, field_validator, model_validator
from packaging.version import Version, InvalidVersion
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.requirements import Requirement, InvalidRequirement

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

class PluginManifest(BaseModel):
    name: str
    version: str
    description: str
    author: str
    platform_version: str
    entry_points: list[str]
    tags: list[str] = []
    dependencies: list[str] = []
    homepage: str | None = None
    license: str | None = None
    min_python: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(f"name must match ^[a-z][a-z0-9_-]*$, got '{v}'")
        return v

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        try:
            Version(v)
        except InvalidVersion:
            raise ValueError(f"version must be a valid PEP 440 version, got '{v}'")
        return v

    @field_validator("platform_version")
    @classmethod
    def _validate_platform_version(cls, v: str) -> str:
        try:
            SpecifierSet(v)
        except InvalidSpecifier:
            raise ValueError(f"platform_version must be a valid PEP 440 specifier, got '{v}'")
        return v

    @field_validator("dependencies", each_item=True)
    @classmethod
    def _validate_dependency(cls, v: str) -> str:
        try:
            Requirement(v)
        except InvalidRequirement:
            raise ValueError(f"dependency must be a valid PEP 508 requirement, got '{v}'")
        return v

    @field_validator("entry_points", each_item=True)
    @classmethod
    def _validate_entry_point(cls, v: str) -> str:
        if not v.endswith(".py"):
            raise ValueError(f"entry_point must end with .py, got '{v}'")
        if "\\" in v or v.startswith("/"):
            raise ValueError(f"entry_point must use forward slashes and be relative, got '{v}'")
        return v

    @model_validator(mode="after")
    def _validate_entry_points_nonempty(self) -> "PluginManifest":
        if not self.entry_points:
            raise ValueError("entry_points must contain at least one entry")
        return self


def load_manifest(plugin_dir: Path) -> PluginManifest:
    """Parse plugin.toml (preferred) or plugin.json from plugin_dir."""
    toml_path = plugin_dir / "plugin.toml"
    json_path = plugin_dir / "plugin.json"

    if toml_path.exists():
        return _load_toml(toml_path)
    elif json_path.exists():
        return _load_json(json_path)
    else:
        raise PluginManifestError(
            f"No plugin.toml or plugin.json found in {plugin_dir}"
        )


def _load_toml(path: Path) -> PluginManifest:
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomli as tomllib  # backport for 3.10
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        raise PluginManifestError(f"Failed to parse {path}: {exc}") from exc
    # Support both [plugin] section and flat top-level
    raw = data.get("plugin", data)
    return _validate_raw(raw, path)


def _load_json(path: Path) -> PluginManifest:
    import json
    try:
        with open(path) as f:
            raw = json.load(f)
    except Exception as exc:
        raise PluginManifestError(f"Failed to parse {path}: {exc}") from exc
    return _validate_raw(raw, path)


def _validate_raw(raw: dict, path: Path) -> PluginManifest:
    import pydantic
    try:
        return PluginManifest.model_validate(raw)
    except pydantic.ValidationError as exc:
        raise PluginManifestError(
            f"Invalid manifest at {path}: {exc}"
        ) from exc
```

## PluginLoader

### File: `app/core/plugins/loader.py`

```python
from __future__ import annotations
import logging
import sys
from pathlib import Path
from packaging.version import Version
from packaging.specifiers import SpecifierSet

from app.core.plugins.manifest import load_manifest, PluginManifest
from app.core.plugins.dependencies import DependencyChecker
from app.core.plugins.errors import PluginCompatibilityError, PluginManifestError

log = logging.getLogger(__name__)

# Platform version — read from app/__version__.py or hardcoded for now
PLATFORM_VERSION = "5.0.0"


class PluginLoader:
    def __init__(self, registry) -> None:
        self._registry = registry

    def load(self, plugin_dir: Path) -> list[str]:
        """Load a manifest-based plugin. Returns list of registered node_types."""
        manifest = load_manifest(plugin_dir)  # raises PluginManifestError
        self._check_platform_compat(manifest)
        self._check_python_compat(manifest)
        DependencyChecker().check(manifest.dependencies)
        node_types = self._import_entry_points(plugin_dir, manifest)
        log.info(
            "Loaded plugin '%s' v%s — %d node type(s) registered",
            manifest.name, manifest.version, len(node_types)
        )
        return node_types

    def _check_platform_compat(self, manifest: PluginManifest) -> None:
        spec = SpecifierSet(manifest.platform_version)
        if Version(PLATFORM_VERSION) not in spec:
            raise PluginCompatibilityError(
                f"Plugin '{manifest.name}' requires platform {manifest.platform_version} "
                f"but current platform is {PLATFORM_VERSION}."
            )

    def _check_python_compat(self, manifest: PluginManifest) -> None:
        if manifest.min_python is None:
            return
        current = Version(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        required = SpecifierSet(f">={manifest.min_python}")
        if current not in required:
            raise PluginCompatibilityError(
                f"Plugin '{manifest.name}' requires Python >={manifest.min_python} "
                f"but current Python is {current}."
            )

    def _import_entry_points(self, plugin_dir: Path, manifest: PluginManifest) -> list[str]:
        from app.core.nodes.discovery import AutoDiscovery
        discovery = AutoDiscovery(self._registry)
        node_types_before = set(self._registry._classes.keys())
        for ep in manifest.entry_points:
            ep_path = plugin_dir / ep
            try:
                module = discovery._import_file(ep_path, package_prefix=None)
                discovery._process_module(module)
            except Exception as exc:
                log.warning("Plugin '%s': failed to load entry point '%s': %s", manifest.name, ep, exc)
        node_types_after = set(self._registry._classes.keys())
        return list(node_types_after - node_types_before)
```

## Design Decisions

1. **`[plugin]` section vs flat top-level**: The TOML parser supports both `[plugin]` section (recommended) and flat top-level keys for flexibility. JSON manifests use flat top-level only.

2. **`tomllib` vs `tomli`**: Python 3.11+ has `tomllib` in stdlib. For Python 3.10 compatibility, `tomli` is used as a fallback. `tomli` should be added to `requirements.txt`.

3. **`PluginManifestError` is a `ValueError` subclass**: This allows it to be caught by generic `except ValueError` handlers in existing code, reducing the risk of unhandled exceptions during the transition period.

4. **`PluginLoader` delegates to `AutoDiscovery`**: Rather than reimplementing node registration, `PluginLoader` reuses `AutoDiscovery._import_file()` and `_process_module()`. This ensures that all existing node registration logic (duplicate detection, metadata validation, port population) applies to plugin nodes.
