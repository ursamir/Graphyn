# req-02 — Dependency Management

## Introduction

Plugins declare their Python package dependencies in the manifest `dependencies` field. The `DependencyChecker` verifies these are satisfied in the current environment before any plugin code is imported. An optional auto-install mode (`GRAPHYN_PLUGIN_AUTO_INSTALL=1`) allows the platform to install missing dependencies automatically using `pip`.

## Glossary

- **DependencyChecker** — Component that validates plugin dependencies against the current Python environment.
- **PluginDependencyError** — Exception raised when one or more declared dependencies are not satisfied and auto-install is disabled or failed.
- **PEP 508** — Python's dependency specification standard. Each entry in `dependencies` must be a valid PEP 508 requirement string.
- **importlib.metadata** — Python stdlib module for querying installed package metadata. Used for dependency checking without importing packages.

## Requirement 3: Dependency Management

**User Story:** As a plugin author, I want to declare my plugin's Python package dependencies, so that the platform can verify they are satisfied before loading my plugin.

### Acceptance Criteria

1. WHEN a plugin manifest declares `dependencies`, THE DependencyChecker SHALL verify that each declared dependency is satisfied in the current Python environment using `importlib.metadata` or `pkg_resources`.
2. WHEN a declared dependency is not satisfied, THE DependencyChecker SHALL raise a `PluginDependencyError` listing all unsatisfied dependencies (not just the first one).
3. WHEN the `GRAPHYN_PLUGIN_AUTO_INSTALL` environment variable is set to `"1"` or `"true"`, THE DependencyChecker SHALL attempt to install unsatisfied dependencies using `pip` before raising an error.
4. WHEN auto-install is attempted and succeeds, THE DependencyChecker SHALL log the installed packages at INFO level and proceed with plugin loading.
5. WHEN auto-install is attempted and fails, THE DependencyChecker SHALL raise a `PluginDependencyError` with the pip error output included in the message.
6. WHEN a plugin has no declared `dependencies`, THE DependencyChecker SHALL skip dependency checking entirely.
7. THE DependencyChecker SHALL validate each dependency string as a valid PEP 508 requirement using the `packaging` library before attempting to check or install it.
8. IF a dependency string is not a valid PEP 508 requirement, THEN THE DependencyChecker SHALL raise a `PluginManifestError` identifying the malformed dependency string.

## Implementation Notes

- Use `importlib.metadata.requires()` and `importlib.metadata.version()` for checking installed packages.
- Use `packaging.requirements.Requirement` to parse and validate each dependency string.
- Use `packaging.version.Version` and `packaging.specifiers.SpecifierSet` to check version constraints.
- Auto-install uses `subprocess.run([sys.executable, "-m", "pip", "install", ...], capture_output=True)`.
- Collect all unsatisfied dependencies before raising — do not fail fast on the first missing dep.
- `DependencyChecker` lives in `app/core/plugins/dependencies.py`.

## Isolation Strategy

Phase 5 does not implement full virtual environment isolation per plugin (that is a Phase 6+ concern). Dependencies are installed into the current Python environment. The `GRAPHYN_PLUGIN_AUTO_INSTALL` flag is opt-in and disabled by default to prevent unexpected package installations in production environments.

## File Location

`app/core/plugins/dependencies.py`
