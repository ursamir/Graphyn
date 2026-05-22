# tasks-01 — Foundation: Plugin Package, Errors, Manifest, Dependencies

## Overview

Create the `app/core/plugins/` package with all foundational components: error classes, `PluginManifest` model and parser, and `DependencyChecker`. These have no dependencies on other Phase 5 components and can be implemented first.

## Tasks

- [x] 1. Create `app/core/plugins/` package and error classes
  - Create `app/core/plugins/__init__.py` (empty, with `from __future__ import annotations`)
  - Create `app/core/plugins/errors.py` with the full error hierarchy:
    - `PluginError(Exception)` — base class
    - `PluginManifestError(PluginError, ValueError)` — manifest parse/validation failures
    - `PluginCompatibilityError(PluginError)` — platform/Python version mismatch
    - `PluginDependencyError(PluginError)` — unsatisfied Python dependencies
    - `PluginInstallError(PluginError)` — remote fetch/extract/git failures
    - `PluginNotFoundError(PluginError, KeyError)` — plugin not in PluginStore
    - `PluginAlreadyInstalledError(PluginError)` — duplicate install without upgrade
    - `PluginIndexError(PluginError)` — index fetch/parse failures
  - _Requirements: req-01 §1.4, req-02 §2.2, req-03 §3.2, req-04 §5.6, req-05 §6.8_

- [x] 2. Implement `PluginManifest` and `load_manifest()` (`app/core/plugins/manifest.py`)
  - [x] 2.1 Define `PluginManifest` Pydantic model with all required and optional fields
    - Required: `name` (slug), `version` (PEP 440), `description`, `author`, `platform_version` (PEP 440 specifier), `entry_points` (list[str], min 1)
    - Optional with defaults: `tags=[]`, `dependencies=[]`, `homepage=None`, `license=None`, `min_python=None`
    - Field validators: `_validate_name` (slug regex), `_validate_version` (PEP 440), `_validate_platform_version` (PEP 440 specifier), `_validate_dependency` (PEP 508 per item), `_validate_entry_point` (ends with .py, no backslashes)
    - Model validator: `entry_points` must be non-empty
    - _Requirements: req-01 §1.1, §1.2, §1.7, §1.8, §1.9, §1.10_

  - [x] 2.2 Implement `load_manifest(plugin_dir: Path) -> PluginManifest`
    - Try `plugin.toml` first, then `plugin.json`; raise `PluginManifestError` if neither exists
    - TOML parsing: use `tomllib` (Python 3.11+) with `tomli` fallback for 3.10; support both `[plugin]` section and flat top-level
    - JSON parsing: flat top-level only
    - Wrap `pydantic.ValidationError` in `PluginManifestError` with field name and violation
    - _Requirements: req-01 §1.3, §1.4, §1.5, §1.6_

  - [x]* 2.3 Write unit tests for `PluginManifest` and `load_manifest()`
    - Create `tests/test_plugin_manifest.py`
    - Test valid `plugin.toml` parses to correct `PluginManifest`
    - Test valid `plugin.json` parses to correct `PluginManifest`
    - Test `plugin.toml` takes precedence over `plugin.json` when both exist
    - Test missing required field raises `PluginManifestError` naming the field
    - Test invalid slug name raises `PluginManifestError`
    - Test invalid PEP 440 version raises `PluginManifestError`
    - Test invalid PEP 440 specifier in `platform_version` raises `PluginManifestError`
    - Test invalid PEP 508 dependency raises `PluginManifestError`
    - Test empty `entry_points` raises `PluginManifestError`
    - Test entry point without `.py` suffix raises `PluginManifestError`
    - Test missing manifest file raises `PluginManifestError`
    - Test invalid TOML syntax raises `PluginManifestError`
    - Use `tmp_path` fixture to create manifest files
    - _Requirements: req-01 §1.1–§1.10_

- [x] 3. Implement `DependencyChecker` (`app/core/plugins/dependencies.py`)
  - [x] 3.1 Implement `DependencyChecker.check(dependencies: list[str]) -> None`
    - Skip entirely if `dependencies` is empty
    - Validate each string as PEP 508 using `packaging.requirements.Requirement`; raise `PluginManifestError` for invalid strings
    - Check each requirement against `importlib.metadata`: use `importlib.metadata.version(pkg_name)` and `packaging.specifiers.SpecifierSet` to verify version constraints
    - Collect ALL unsatisfied requirements before raising
    - Raise `PluginDependencyError` with the full list of unsatisfied requirements
    - _Requirements: req-02 §3.1, §3.2, §3.6, §3.7, §3.8_

  - [x] 3.2 Implement auto-install mode
    - Check `os.environ.get("GRAPHYN_PLUGIN_AUTO_INSTALL", "")` — enable if value is `"1"` or `"true"` (case-insensitive)
    - When enabled and unsatisfied deps found: run `subprocess.run([sys.executable, "-m", "pip", "install", ...unsatisfied_deps], capture_output=True)`
    - On pip success: log installed packages at INFO, re-check deps, proceed
    - On pip failure: raise `PluginDependencyError` with pip stderr included
    - _Requirements: req-02 §3.3, §3.4, §3.5_

  - [x]* 3.3 Write unit tests for `DependencyChecker`
    - Create `tests/test_plugin_dependencies.py`
    - Test empty dependencies list → no error
    - Test satisfied dependency → no error (mock `importlib.metadata.version`)
    - Test unsatisfied dependency → `PluginDependencyError` listing the dep
    - Test multiple unsatisfied deps → `PluginDependencyError` listing ALL of them
    - Test invalid PEP 508 string → `PluginManifestError`
    - Test auto-install disabled (default) → raises without calling pip
    - Test auto-install enabled, pip succeeds → no error (mock subprocess.run)
    - Test auto-install enabled, pip fails → `PluginDependencyError` with pip output
    - Use `monkeypatch` to mock `importlib.metadata.version` and `subprocess.run`
    - _Requirements: req-02 §3.1–§3.8_

- [x] 4. Checkpoint — verify all existing tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions.
  - Ask the user if questions arise.
