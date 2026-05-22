"""
Plugin manifest model and parser for the plugin ecosystem (Phase 5).

Supports ``plugin.toml`` (preferred) and ``plugin.json`` manifest files.
Both formats are parsed into a validated ``PluginManifest`` Pydantic model.

Usage::

    from pathlib import Path
    from app.core.plugins.manifest import load_manifest

    manifest = load_manifest(Path("/path/to/my-plugin"))
    print(manifest.name, manifest.version)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator, model_validator

from app.core.plugins.errors import PluginManifestError

# ---------------------------------------------------------------------------
# TOML import — tomllib is stdlib on Python 3.11+; fall back to tomli on 3.10
# ---------------------------------------------------------------------------
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError as _tomli_err:
        raise ImportError(
            "Python 3.10 requires the 'tomli' package. "
            "Install it with: pip install tomli"
        ) from _tomli_err

# Slug pattern: must start with a lowercase letter, followed by lowercase
# letters, digits, hyphens, or underscores.
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class PluginManifest(BaseModel):
    """Validated representation of a ``plugin.toml`` or ``plugin.json`` file.

    Required fields
    ---------------
    name
        Plugin identifier slug matching ``^[a-z][a-z0-9_-]*$``.
    version
        PEP 440 version string (e.g. ``"1.2.0"``).
    description
        Non-empty human-readable description.
    author
        Non-empty author name / contact string.
    platform_version
        PEP 440 version specifier (e.g. ``">=5.0,<6.0"``).
    entry_points
        List of ``.py`` file paths (forward-slash separated, min 1 item).

    Optional fields (with defaults)
    --------------------------------
    tags
        List of free-form tag strings. Default ``[]``.
    dependencies
        List of PEP 508 requirement strings. Default ``[]``.
    optional_dependencies
        List of PEP 508 requirement strings for optional heavy deps (e.g. torch,
        tensorflow). These are NOT checked by DependencyChecker at install time —
        the node must degrade gracefully when they are absent. Default ``[]``.
    homepage
        URL string or ``None``.
    license
        SPDX identifier string or ``None``.
    min_python
        Minimum Python version string or ``None``.
    """

    # ------------------------------------------------------------------
    # Required fields
    # ------------------------------------------------------------------
    name: str
    version: str
    description: str
    author: str
    platform_version: str
    entry_points: list[str]

    # ------------------------------------------------------------------
    # Optional fields
    # ------------------------------------------------------------------
    tags: list[str] = []
    dependencies: list[str] = []
    optional_dependencies: list[str] = []
    homepage: str | None = None
    license: str | None = None
    min_python: str | None = None

    # ------------------------------------------------------------------
    # Field validators
    # ------------------------------------------------------------------

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v:
            raise ValueError("'name' must not be empty")
        if not _SLUG_RE.match(v):
            raise ValueError(
                f"'name' must start with a lowercase letter and contain only "
                f"lowercase letters, digits, hyphens, or underscores (got {v!r})"
            )
        return v

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not v:
            raise ValueError("'version' must not be empty")
        try:
            from packaging.version import Version

            Version(v)
        except Exception as exc:
            raise ValueError(
                f"'version' is not a valid PEP 440 version string (got {v!r}): {exc}"
            ) from exc
        return v

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("'description' must not be empty")
        return v

    @field_validator("author")
    @classmethod
    def _validate_author(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("'author' must not be empty")
        return v

    @field_validator("platform_version")
    @classmethod
    def _validate_platform_version(cls, v: str) -> str:
        if not v:
            raise ValueError("'platform_version' must not be empty")
        try:
            from packaging.specifiers import SpecifierSet

            SpecifierSet(v)
        except Exception as exc:
            raise ValueError(
                f"'platform_version' is not a valid PEP 440 specifier (got {v!r}): {exc}"
            ) from exc
        return v

    @field_validator("entry_points")
    @classmethod
    def _validate_entry_points(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("'entry_points' must contain at least one entry")
        for item in v:
            if not isinstance(item, str):
                raise ValueError(
                    f"Each entry in 'entry_points' must be a string (got {item!r})"
                )
            if not item.endswith(".py"):
                raise ValueError(
                    f"Each entry in 'entry_points' must end with '.py' (got {item!r})"
                )
            if "\\" in item:
                raise ValueError(
                    f"Entry points must use forward slashes only, not backslashes (got {item!r})"
                )
        return v

    @field_validator("dependencies")
    @classmethod
    def _validate_dependencies(cls, v: list[str]) -> list[str]:
        from packaging.requirements import Requirement

        for item in v:
            if not isinstance(item, str):
                raise ValueError(
                    f"Each dependency must be a string (got {item!r})"
                )
            try:
                Requirement(item)
            except Exception as exc:
                raise ValueError(
                    f"Dependency {item!r} is not a valid PEP 508 requirement: {exc}"
                ) from exc
        return v

    # ------------------------------------------------------------------
    # Cross-field validation: entry_points must have >= 1 item
    # (also enforced by field_validator above, but belt-and-suspenders)
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _check_entry_points_not_empty(self) -> "PluginManifest":
        if not self.entry_points:
            raise ValueError("'entry_points' must contain at least one entry")
        return self

    # ------------------------------------------------------------------
    # Wrap Pydantic ValidationError → PluginManifestError on direct
    # construction (PluginManifest(**data)).  model_validate() is handled
    # by _rewrap_validation_error in _parse_manifest_dict.
    # ------------------------------------------------------------------
    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except Exception as exc:
            _rewrap_validation_error(exc, source="<direct construction>")


def _rewrap_validation_error(exc: Exception, source: str) -> None:
    """Re-raise *exc* as :class:`PluginManifestError` if it is a Pydantic
    ``ValidationError``; otherwise re-raise as-is.

    This is a no-return helper — it always raises.
    """
    from pydantic import ValidationError as PydanticValidationError

    if isinstance(exc, PluginManifestError):
        raise exc

    if isinstance(exc, PydanticValidationError):
        errors = exc.errors(include_url=False)
        messages = []
        for err in errors:
            loc = " -> ".join(str(p) for p in err["loc"]) if err["loc"] else "<root>"
            messages.append(f"  {loc}: {err['msg']}")
        detail = "\n".join(messages)
        raise PluginManifestError(
            f"Manifest validation failed for {source!r}:\n{detail}"
        ) from exc

    raise PluginManifestError(
        f"Unexpected error parsing manifest {source!r}: {exc}"
    ) from exc


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_manifest(plugin_dir: Path) -> PluginManifest:
    """Parse and validate the manifest file inside *plugin_dir*.

    Tries ``plugin.toml`` first; falls back to ``plugin.json``.  Raises
    :class:`~app.core.plugins.errors.PluginManifestError` if:

    - Neither file exists.
    - The file cannot be parsed (TOML/JSON syntax error).
    - The parsed data fails ``PluginManifest`` validation.

    Parameters
    ----------
    plugin_dir:
        Path to the plugin package directory (must be an existing directory).

    Returns
    -------
    PluginManifest
        Fully validated manifest instance.

    Raises
    ------
    PluginManifestError
        On any parse or validation failure.
    """
    toml_path = plugin_dir / "plugin.toml"
    json_path = plugin_dir / "plugin.json"

    data: dict[str, Any]

    if toml_path.exists():
        data = _load_toml(toml_path)
    elif json_path.exists():
        data = _load_json(json_path)
    else:
        raise PluginManifestError(
            f"No manifest file found in {plugin_dir!r}. "
            "Expected 'plugin.toml' or 'plugin.json'."
        )

    return _parse_manifest_dict(data, source=str(toml_path if toml_path.exists() else json_path))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict[str, Any]:
    """Read and parse a TOML manifest file.

    Supports both ``[plugin]`` table and flat top-level keys.
    """
    try:
        with path.open("rb") as fh:
            raw: dict[str, Any] = tomllib.load(fh)
    except Exception as exc:
        raise PluginManifestError(
            f"Failed to parse TOML manifest at {path!r}: {exc}"
        ) from exc

    # Support [plugin] section (canonical) or flat top-level keys
    if "plugin" in raw and isinstance(raw["plugin"], dict):
        return raw["plugin"]
    return raw


def _load_json(path: Path) -> dict[str, Any]:
    """Read and parse a JSON manifest file."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        raise PluginManifestError(
            f"Failed to parse JSON manifest at {path!r}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise PluginManifestError(
            f"JSON manifest at {path!r} must be a JSON object, got {type(data).__name__}"
        )
    return data


def _parse_manifest_dict(data: dict[str, Any], source: str) -> PluginManifest:
    """Construct a ``PluginManifest`` from a raw dict, wrapping Pydantic errors."""
    try:
        return PluginManifest.model_validate(data)
    except Exception as exc:
        _rewrap_validation_error(exc, source=source)
        raise  # unreachable; satisfies type checkers
