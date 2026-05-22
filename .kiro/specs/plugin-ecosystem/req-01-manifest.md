# req-01 — Plugin Manifest

## Introduction

A plugin manifest is a `plugin.toml` (or `plugin.json`) file at the root of a plugin package directory. It gives the platform structured, machine-readable metadata about the plugin before any Python code is imported. This is the foundation for all other Phase 5 features: dependency checking, version compatibility, lifecycle management, and the marketplace index all depend on the manifest.

## Glossary

- **PluginManifest** — Pydantic model representing a parsed and validated manifest file.
- **PluginManifestError** — Exception raised when a manifest file is missing, malformed, or contains invalid field values.
- **slug** — A lowercase string matching `^[a-z][a-z0-9_-]*$`. Used for plugin names to ensure safe filesystem and URL usage.
- **PEP 440** — Python's version numbering standard. Used for `version` and `platform_version` fields.
- **PEP 508** — Python's dependency specification standard (e.g., `"numpy>=1.24"`). Used for `dependencies` entries.

## Requirement 1: Plugin Manifest Schema

**User Story:** As a plugin author, I want to declare my plugin's identity, version, platform compatibility, dependencies, and entry points in a structured manifest file, so that the platform can validate and manage my plugin automatically.

### Acceptance Criteria

1. THE Plugin_Manifest_Schema SHALL define a `plugin.toml` format with the following required fields: `name` (non-empty string, slug format), `version` (PEP 440 version string), `description` (non-empty string), `author` (non-empty string), `platform_version` (PEP 440 version constraint string), and `entry_points` (list of Python module file paths, minimum one entry).
2. THE Plugin_Manifest_Schema SHALL define the following optional fields with defaults: `tags` (list of strings, default `[]`), `dependencies` (list of PEP 508 requirement strings, default `[]`), `homepage` (URL string, default `null`), `license` (SPDX identifier string, default `null`), `min_python` (version string, default `null`).
3. WHEN a `plugin.toml` file is parsed, THE PluginManifest_Parser SHALL produce a `PluginManifest` Pydantic model instance with all fields validated.
4. WHEN a `plugin.toml` contains an invalid field value (wrong type, empty required string, malformed version), THE PluginManifest_Parser SHALL raise a `PluginManifestError` with a message identifying the field and the violation.
5. WHEN a `plugin.toml` is missing a required field, THE PluginManifest_Parser SHALL raise a `PluginManifestError` naming the missing field.
6. THE PluginManifest_Parser SHALL accept both `plugin.toml` (TOML format) and `plugin.json` (JSON format) manifest files, with `plugin.toml` taking precedence when both are present.
7. THE PluginManifest_Parser SHALL validate that the `name` field matches the pattern `^[a-z][a-z0-9_-]*$` (lowercase slug).
8. THE PluginManifest_Parser SHALL validate that the `version` field is a valid PEP 440 version string using the `packaging` library.
9. THE PluginManifest_Parser SHALL validate that the `platform_version` field is a valid PEP 440 version specifier string using the `packaging` library.
10. THE PluginManifest_Parser SHALL validate that each string in `entry_points` ends with `.py` and does not contain path separators other than forward slashes.

## Reference: Canonical `plugin.toml` Example

```toml
[plugin]
name = "audio-denoiser"
version = "1.2.0"
description = "Spectral subtraction denoiser for audio pipelines."
author = "Jane Smith <jane@example.com>"
platform_version = ">=5.0,<6.0"
entry_points = ["denoiser.py"]
tags = ["audio", "denoising", "processing"]
dependencies = ["scipy>=1.10", "numpy>=1.24"]
homepage = "https://github.com/example/audio-denoiser"
license = "MIT"
min_python = "3.10"
```

## Implementation Notes

- Use Python's `tomllib` (stdlib, Python 3.11+) or `tomli` (backport for 3.10) for TOML parsing.
- Use `packaging.version.Version` for `version` validation.
- Use `packaging.specifiers.SpecifierSet` for `platform_version` validation.
- Use `packaging.requirements.Requirement` for each `dependencies` entry validation.
- The `PluginManifest` Pydantic model lives in `app/core/plugins/manifest.py`.
- `PluginManifestError` is a subclass of `ValueError` for easy catching.

## File Location

`app/core/plugins/manifest.py`
