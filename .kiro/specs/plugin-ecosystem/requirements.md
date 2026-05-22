# Requirements — Plugin Ecosystem (Phase 5)

## Introduction

Phase 5 evolves the existing `AutoDiscovery` flat-file plugin architecture into a full plugin ecosystem. Phases 1–4 established the Graph IR, MCP layer, advanced runtime, and provenance/artifact system. Phase 5 builds on those foundations to give plugins a structured identity (manifests), safe dependency management, version compatibility enforcement, remote sourcing, and a browsable marketplace index.

The current system (`app/core/nodes/discovery.py`) is a flat file drop: place a `.py` file in `plugins/` and `AutoDiscovery` registers it at startup. No manifest, no versioning, no dependency management. Phase 5 adds all of these while preserving full backward compatibility with existing flat `.py` drop-in plugins.

**Regression constraint:** All existing tests must continue to pass. No existing public API may be removed or have its signature changed in a breaking way.

## Glossary

- **Plugin** — A distributable unit of one or more `Node` subclasses, described by a `plugin.toml` manifest and optionally packaged as a directory or archive.
- **Plugin Manifest** — A `plugin.toml` file at the root of a plugin package that declares the plugin's identity, version, platform compatibility, Python dependencies, and entry points.
- **Plugin Package** — A directory containing a `plugin.toml` and one or more `.py` module files. May be distributed as a `.zip` or `.tar.gz` archive.
- **Legacy Plugin** — A bare `.py` file in the plugins directory with no accompanying `plugin.toml`. Continues to work unchanged (backward compatibility).
- **PluginManifest** — The Pydantic model that represents a parsed and validated `plugin.toml`.
- **PluginRecord** — The persistent state record for an installed plugin: manifest data, install source, enabled/disabled state, install timestamp.
- **PluginRegistry** — The runtime registry of installed plugins and their state. Distinct from `NodeRegistry` (which maps node types to classes).
- **PluginStore** — The on-disk persistence layer for `PluginRecord` objects (`workspace/plugins/`).
- **PluginLoader** — The component that loads a plugin package directory, validates its manifest, checks dependencies, and delegates to `AutoDiscovery` for node registration.
- **PluginInstaller** — The component that fetches a plugin from a remote source (Git URL, HTTP archive, plugin index) and installs it into the plugins directory.
- **PluginIndex** — A JSON document (local or remote) listing available plugins with their names, versions, descriptions, and download URLs.
- **platform_version** — The version string of the pipeline engine platform (read from `app/__version__.py` or equivalent). Used for compatibility checking.
- **version constraint** — A PEP 440-compatible version specifier string (e.g., `">=5.0,<6.0"`) that a plugin declares as its required platform version range.
- **Workspace** — The `workspace/` directory tree. Phase 5 adds `workspace/plugins/` for plugin state persistence.

## Sub-Document Index

| File | Scope |
|---|---|
| `req-01-manifest.md` | `plugin.toml` schema, `PluginManifest` Pydantic model, manifest validation |
| `req-02-dependency-management.md` | Dependency checking, optional auto-install, isolation strategy |
| `req-03-lifecycle.md` | Install, enable, disable, uninstall operations; `PluginStore` persistence |
| `req-04-remote-plugins.md` | Git URL, HTTP archive, plugin index fetch and install |
| `req-05-plugin-index.md` | Plugin index format, local/remote index, browse and search |
| `req-06-cli.md` | `audiobuilder plugin` subcommand group |
| `req-07-api.md` | REST API `/api/v1/plugins/` endpoints |
| `req-08-sdk.md` | `Pipeline.install_plugin()` and SDK plugin management |
| `req-09-backward-compat.md` | Legacy flat `.py` plugin support, migration path |

## Cross-Phase Constraints

The following Phase 1–4 constraints are binding on Phase 5:

| Constraint | Origin | Phase 5 Impact |
|---|---|---|
| `NodeMetadata` capability fields | Phase 1, req-05 | Plugin manifests expose capability metadata; `PluginLoader` validates it |
| SDK is single source of truth | Phase 1, req-02 §2.9 | CLI and REST API delegate plugin operations to `PluginManager` |
| `AutoDiscovery` is the node registration mechanism | Phase 1 | `PluginLoader` delegates to `AutoDiscovery`; does not bypass it |
| `GRAPHYN_PLUGINS_DIR` env var | Phase 1 | Remains the override for the plugins directory root |
| Stabilized runtime | Phase 3 | Plugin lifecycle hooks (`setup`, `teardown`) run safely in the Phase 3 runtime |
| Artifact system | Phase 4 | Plugin install/uninstall events are logged; no artifact store dependency required |
| All existing tests must pass | Phase 1–4 | All new code is additive; no existing signatures change |

## Requirements

### Requirement 1: Plugin Manifest

**User Story:** As a plugin author, I want to declare my plugin's identity, version, platform compatibility, dependencies, and entry points in a structured manifest file, so that the platform can validate and manage my plugin automatically.

#### Acceptance Criteria

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

### Requirement 2: Manifest Validation and Platform Compatibility

**User Story:** As a platform operator, I want incompatible plugins to be rejected at load time with clear error messages, so that I can diagnose and resolve compatibility issues without runtime failures.

#### Acceptance Criteria

1. WHEN a plugin package is loaded, THE PluginLoader SHALL parse and validate the plugin's `plugin.toml` manifest before importing any Python modules from the package.
2. WHEN the platform version does not satisfy the plugin's `platform_version` constraint, THE PluginLoader SHALL raise a `PluginCompatibilityError` with a message stating the plugin name, the required constraint, and the actual platform version.
3. WHEN the running Python version does not satisfy the plugin's `min_python` constraint (if declared), THE PluginLoader SHALL raise a `PluginCompatibilityError` with a message stating the required and actual Python versions.
4. WHEN a plugin package directory does not contain a `plugin.toml` or `plugin.json`, THE PluginLoader SHALL treat the package as a legacy plugin and skip manifest validation.
5. WHEN a `plugin.toml` exists but is not valid TOML, THE PluginLoader SHALL raise a `PluginManifestError` with the parse error detail.
6. WHEN a plugin is rejected due to a compatibility error, THE PluginLoader SHALL log the rejection at WARNING level and continue loading other plugins.
7. WHEN a plugin is successfully loaded, THE PluginLoader SHALL log the plugin name, version, and number of registered node types at INFO level.
8. WHEN a plugin declares `entry_points`, THE PluginLoader SHALL import only the listed modules (not all `.py` files in the package directory).
9. WHEN a plugin declares no `entry_points` (legacy mode), THE PluginLoader SHALL fall back to scanning all `.py` files in the package directory via `AutoDiscovery`.

### Requirement 3: Dependency Management

**User Story:** As a plugin author, I want to declare my plugin's Python package dependencies, so that the platform can verify they are satisfied before loading my plugin.

#### Acceptance Criteria

1. WHEN a plugin manifest declares `dependencies`, THE DependencyChecker SHALL verify that each declared dependency is satisfied in the current Python environment using `importlib.metadata` or `pkg_resources`.
2. WHEN a declared dependency is not satisfied, THE DependencyChecker SHALL raise a `PluginDependencyError` listing all unsatisfied dependencies (not just the first one).
3. WHEN the `GRAPHYN_PLUGIN_AUTO_INSTALL` environment variable is set to `"1"` or `"true"`, THE DependencyChecker SHALL attempt to install unsatisfied dependencies using `pip` before raising an error.
4. WHEN auto-install is attempted and succeeds, THE DependencyChecker SHALL log the installed packages at INFO level and proceed with plugin loading.
5. WHEN auto-install is attempted and fails, THE DependencyChecker SHALL raise a `PluginDependencyError` with the pip error output included in the message.
6. WHEN a plugin has no declared `dependencies`, THE DependencyChecker SHALL skip dependency checking entirely.
7. THE DependencyChecker SHALL validate each dependency string as a valid PEP 508 requirement using the `packaging` library before attempting to check or install it.
8. IF a dependency string is not a valid PEP 508 requirement, THEN THE DependencyChecker SHALL raise a `PluginManifestError` identifying the malformed dependency string.

### Requirement 4: Plugin Lifecycle

**User Story:** As a platform operator, I want to install, enable, disable, and uninstall plugins through a managed lifecycle, so that I can control which plugins are active without restarting the server.

#### Acceptance Criteria

1. THE PluginStore SHALL persist plugin state in `workspace/plugins/registry.json` as a JSON object mapping plugin name to `PluginRecord`.
2. THE PluginRecord SHALL contain the following fields: `name`, `version`, `source` (install source URL or path), `install_path` (absolute path to the installed plugin directory), `enabled` (boolean), `installed_at` (ISO 8601 timestamp), `manifest` (the full parsed manifest as a dict).
3. WHEN a plugin is installed, THE PluginManager SHALL write a `PluginRecord` to `PluginStore` with `enabled=true`.
4. WHEN a plugin is disabled, THE PluginManager SHALL update the `PluginRecord` in `PluginStore` to `enabled=false` and unload the plugin's node types from `NodeRegistry`.
5. WHEN a plugin is enabled, THE PluginManager SHALL update the `PluginRecord` in `PluginStore` to `enabled=true` and reload the plugin's node types into `NodeRegistry`.
6. WHEN a plugin is uninstalled, THE PluginManager SHALL remove the `PluginRecord` from `PluginStore`, unload the plugin's node types from `NodeRegistry`, and delete the plugin directory from disk.
7. WHEN a plugin is uninstalled and its node types are referenced in a loaded `GraphIR`, THE PluginManager SHALL log a WARNING identifying the affected node types but SHALL proceed with uninstallation.
8. WHEN the platform starts, THE PluginManager SHALL load all plugins with `enabled=true` from `PluginStore` before `AutoDiscovery` scans the plugins directory.
9. WHEN a plugin with the same name is already installed, THE PluginManager SHALL raise a `PluginAlreadyInstalledError` unless the `--upgrade` flag is specified, in which case it SHALL replace the existing installation.
10. THE PluginStore SHALL use a threading lock for all read-modify-write operations on `registry.json`.

### Requirement 5: Remote Plugin Installation

**User Story:** As a developer, I want to install plugins from remote sources (Git repositories, HTTP archives, plugin index), so that I can share and consume plugins without manual file copying.

#### Acceptance Criteria

1. WHEN a source string begins with `git+` or ends with `.git`, THE PluginInstaller SHALL clone the repository using `git clone --depth 1` to a temporary directory, then install from the cloned directory.
2. WHEN a source string is an HTTP or HTTPS URL ending in `.zip` or `.tar.gz`, THE PluginInstaller SHALL download the archive to a temporary file, extract it, locate the `plugin.toml` within the extracted tree, and install from that directory.
3. WHEN a source string is a plain plugin name (no URL scheme, no file path), THE PluginInstaller SHALL look up the name in the configured plugin index and resolve it to a download URL before installing.
4. WHEN a source string is a local file path to a directory containing `plugin.toml`, THE PluginInstaller SHALL copy the directory into the plugins directory and install from the copy.
5. WHEN a source string is a local file path to a `.zip` or `.tar.gz` archive, THE PluginInstaller SHALL extract the archive and install from the extracted directory.
6. WHEN a remote download fails (network error, 404, timeout), THE PluginInstaller SHALL raise a `PluginInstallError` with the source URL and HTTP status code or error message.
7. WHEN a Git clone fails, THE PluginInstaller SHALL raise a `PluginInstallError` with the repository URL and the git error output.
8. WHEN an archive is extracted and no `plugin.toml` is found within two directory levels, THE PluginInstaller SHALL raise a `PluginInstallError` stating that no manifest was found.
9. THE PluginInstaller SHALL clean up all temporary files and directories on both success and failure.
10. WHEN a version specifier is provided alongside a plugin name (e.g., `my-plugin==1.2.0`), THE PluginInstaller SHALL pass the version constraint to the plugin index lookup and install the matching version.

### Requirement 6: Plugin Index and Marketplace

**User Story:** As a developer, I want to browse and search a registry of available plugins, so that I can discover and install plugins by name without knowing their source URLs.

#### Acceptance Criteria

1. THE Plugin_Index_Format SHALL be a JSON document with a top-level `plugins` array, where each entry contains: `name`, `version`, `description`, `author`, `tags`, `platform_version`, `download_url`, and optionally `homepage` and `checksum`.
2. WHEN the `GRAPHYN_PLUGIN_INDEX_URL` environment variable is set, THE PluginIndexClient SHALL fetch the index from that URL using an HTTP GET request with a 10-second timeout.
3. WHEN `GRAPHYN_PLUGIN_INDEX_URL` is not set, THE PluginIndexClient SHALL look for a local index file at `workspace/plugins/index.json`.
4. WHEN neither a remote URL nor a local index file is available, THE PluginIndexClient SHALL return an empty index and log a WARNING.
5. WHEN a search query is provided, THE PluginIndexClient SHALL return all index entries where the query string appears (case-insensitive) in the `name`, `description`, or `tags` fields.
6. WHEN a plugin index entry declares a `checksum` field (SHA-256 hex digest), THE PluginInstaller SHALL verify the downloaded archive against the checksum and raise a `PluginInstallError` if the checksum does not match.
7. THE PluginIndexClient SHALL cache the fetched remote index in memory for the duration of the process (no disk caching).
8. WHEN the remote index fetch fails, THE PluginIndexClient SHALL raise a `PluginIndexError` with the URL and error detail.
9. THE Plugin_Index_Format SHALL support a `schema_version` field at the top level for forward compatibility.

### Requirement 7: CLI Interface

**User Story:** As a developer, I want to manage plugins from the command line, so that I can install, list, enable, disable, remove, and search plugins without writing Python code.

#### Acceptance Criteria

1. THE CLI SHALL provide an `audiobuilder plugin` subcommand group with the following sub-subcommands: `install`, `list`, `enable`, `disable`, `remove`, `search`, `info`.
2. WHEN `audiobuilder plugin install <source>` is executed, THE CLI SHALL call `PluginManager.install(source)`, print the installed plugin name and version on success, and print an error message and exit with code 1 on failure.
3. WHEN `audiobuilder plugin install <source> --upgrade` is executed, THE CLI SHALL pass `upgrade=True` to `PluginManager.install()`.
4. WHEN `audiobuilder plugin list` is executed, THE CLI SHALL print a table with columns `NAME`, `VERSION`, `STATUS`, `SOURCE` for all installed plugins.
5. WHEN `audiobuilder plugin list --enabled` is executed, THE CLI SHALL filter the table to show only enabled plugins.
6. WHEN `audiobuilder plugin enable <name>` is executed, THE CLI SHALL call `PluginManager.enable(name)` and print a confirmation message.
7. WHEN `audiobuilder plugin disable <name>` is executed, THE CLI SHALL call `PluginManager.disable(name)` and print a confirmation message.
8. WHEN `audiobuilder plugin remove <name>` is executed, THE CLI SHALL call `PluginManager.uninstall(name)` and print a confirmation message.
9. WHEN `audiobuilder plugin search <query>` is executed, THE CLI SHALL call `PluginIndexClient.search(query)` and print a table with columns `NAME`, `VERSION`, `DESCRIPTION`, `TAGS`.
10. WHEN `audiobuilder plugin info <name>` is executed, THE CLI SHALL print the full `PluginRecord` as formatted JSON for installed plugins, or the full index entry for uninstalled plugins found in the index.
11. WHEN a plugin operation targets a plugin name that is not installed, THE CLI SHALL print a clear error message and exit with code 1.

### Requirement 8: REST API

**User Story:** As an API consumer, I want REST endpoints for plugin management, so that I can integrate plugin operations into automated workflows and the frontend.

#### Acceptance Criteria

1. THE REST_API SHALL provide a `/api/v1/plugins/` router with the following endpoints: `GET /plugins`, `POST /plugins/install`, `POST /plugins/{name}/enable`, `POST /plugins/{name}/disable`, `DELETE /plugins/{name}`, `GET /plugins/{name}`, `GET /plugins/search`.
2. WHEN `GET /api/v1/plugins` is called, THE REST_API SHALL return a JSON array of all `PluginRecord` objects.
3. WHEN `POST /api/v1/plugins/install` is called with body `{"source": "<source>", "upgrade": false}`, THE REST_API SHALL call `PluginManager.install(source, upgrade=upgrade)` and return `{"name": ..., "version": ..., "status": "installed"}` on success.
4. WHEN `POST /api/v1/plugins/{name}/enable` is called, THE REST_API SHALL call `PluginManager.enable(name)` and return `{"name": ..., "enabled": true}`.
5. WHEN `POST /api/v1/plugins/{name}/disable` is called, THE REST_API SHALL call `PluginManager.disable(name)` and return `{"name": ..., "enabled": false}`.
6. WHEN `DELETE /api/v1/plugins/{name}` is called, THE REST_API SHALL call `PluginManager.uninstall(name)` and return `{"name": ..., "status": "uninstalled"}`.
7. WHEN `GET /api/v1/plugins/{name}` is called for an installed plugin, THE REST_API SHALL return the full `PluginRecord` as JSON.
8. WHEN `GET /api/v1/plugins/search?q=<query>` is called, THE REST_API SHALL call `PluginIndexClient.search(query)` and return the matching index entries as a JSON array.
9. WHEN a plugin operation fails with a known error (`PluginNotFoundError`, `PluginCompatibilityError`, `PluginDependencyError`, `PluginInstallError`), THE REST_API SHALL return the appropriate HTTP status code (404, 422, 422, 502) with a JSON error body containing `{"error": "<error_type>", "detail": "<message>"}`.
10. WHEN `POST /api/v1/plugins/install` is called with a remote source, THE REST_API SHALL execute the install asynchronously and return `{"status": "installing", "name": "<resolved_name>"}` immediately, with the final result available via `GET /api/v1/plugins/{name}`.

### Requirement 9: SDK Interface

**User Story:** As a Python developer, I want to manage plugins programmatically through the SDK, so that I can install and configure plugins as part of my pipeline setup code.

#### Acceptance Criteria

1. THE SDK SHALL expose a `PluginManager` class importable from `app.core.plugins.manager`.
2. WHEN `PluginManager.install(source, upgrade=False)` is called, THE PluginManager SHALL install the plugin from the given source and return a `PluginRecord`.
3. WHEN `PluginManager.uninstall(name)` is called, THE PluginManager SHALL uninstall the named plugin and return `None`.
4. WHEN `PluginManager.enable(name)` is called, THE PluginManager SHALL enable the named plugin and return the updated `PluginRecord`.
5. WHEN `PluginManager.disable(name)` is called, THE PluginManager SHALL disable the named plugin and return the updated `PluginRecord`.
6. WHEN `PluginManager.list_installed()` is called, THE PluginManager SHALL return a list of all `PluginRecord` objects from `PluginStore`.
7. WHEN `PluginManager.get(name)` is called for an installed plugin, THE PluginManager SHALL return the `PluginRecord` for that plugin.
8. WHEN `PluginManager.get(name)` is called for a plugin that is not installed, THE PluginManager SHALL raise a `PluginNotFoundError`.
9. THE `Pipeline` class SHALL expose a `Pipeline.install_plugin(source, upgrade=False) -> PluginRecord` convenience method that delegates to `PluginManager.install()`.

### Requirement 10: Backward Compatibility

**User Story:** As an existing plugin author, I want my flat `.py` drop-in plugins to continue working without modification, so that I do not need to migrate existing plugins to use the new manifest system.

#### Acceptance Criteria

1. WHEN `AutoDiscovery` scans the plugins directory and encounters a `.py` file with no accompanying `plugin.toml` in the same directory or parent directory, THE AutoDiscovery SHALL import and register the file using the existing flat-file mechanism unchanged.
2. WHEN `AutoDiscovery` scans the plugins directory and encounters a subdirectory containing a `plugin.toml`, THE AutoDiscovery SHALL delegate that subdirectory to `PluginLoader` instead of scanning it directly.
3. WHEN `AutoDiscovery` scans the plugins directory and encounters a subdirectory without a `plugin.toml`, THE AutoDiscovery SHALL scan the subdirectory for `.py` files using the existing mechanism (legacy package mode).
4. THE `GRAPHYN_PLUGINS_DIR` environment variable SHALL continue to control the root plugins directory for both legacy and manifest-based plugins.
5. WHEN a legacy plugin file is loaded, THE AutoDiscovery SHALL log a DEBUG-level message suggesting the author add a `plugin.toml` manifest.
6. THE existing `plugin-development.md` steering file template SHALL remain valid and functional for legacy plugins.
