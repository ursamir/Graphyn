# tasks-07 — Documentation Updates

## Overview

Update all steering files and project docs per the update-protocol.md. These tasks must be completed after the implementation tasks.

## Tasks

- [x] 23. Update steering files
  - [x] 23.1 Update `plugin-development.md`
    - Add a new section "Manifest-Based Plugins" with the canonical `plugin.toml` example
    - Add a "Plugin Lifecycle" section describing install/enable/disable/uninstall
    - Update the "Plugin Directory" section to describe both flat-file and subdirectory layouts
    - Add a "Managed Plugin Template" showing a plugin package directory structure
    - Keep the existing "Minimal Template" and "Key Rules" sections unchanged
    - _Per: update-protocol.md — plugin-development.md updates when plugins/ changes_

  - [x] 23.2 Update `project-overview.md`
    - Add new environment variables to the Environment Variables table:
      - `GRAPHYN_PLUGIN_AUTO_INSTALL` | `""` | Auto-install missing plugin dependencies
      - `GRAPHYN_PLUGIN_INDEX_URL` | `""` | Remote plugin index URL
    - Add new file map entries:
      - Plugin ecosystem | `app/core/plugins/` (`manager.py`, `store.py`, `loader.py`, `manifest.py`, `installer.py`, `index.py`, `dependencies.py`, `errors.py`)
    - Add `plugin-ecosystem.md` to the Steering File Index table
    - _Per: update-protocol.md — project-overview.md updates for new env vars and dirs_

  - [x] 23.3 Update `node-registry.md`
    - Add a note about `NodeRegistry.unregister()` and when it is called
    - _Per: update-protocol.md — node-registry.md updates when registry.py changes_

  - [x] 23.4 Update `api-endpoints.md`
    - Add the `/api/v1/plugins/` router section with all 7 endpoints
    - _Per: update-protocol.md — api-endpoints.md updates when new routers are added_

  - [x] 23.5 Update `api-structure.md`
    - Add `plugins_router` to the Active Routers table
    - _Per: update-protocol.md — api-structure.md updates when app/api/main.py changes_

  - [x] 23.6 Update `sdk-cli.md`
    - Add `Pipeline.install_plugin()` to the SDK methods section
    - Add `audiobuilder plugin` subcommand group to the CLI section
    - _Per: update-protocol.md — sdk-cli.md updates when sdk.py or cli/main.py changes_

- [x] 24. Update project docs
  - [x] 24.1 Update `docs/PLUGIN_GUIDE.md`
    - Add a "Phase 5: Manifest-Based Plugins" section with:
      - `plugin.toml` schema reference
      - Step-by-step guide: create a plugin package directory, write `plugin.toml`, install with `audiobuilder plugin install`
      - Dependency declaration example
      - Version constraint example
    - Add a "Plugin CLI Reference" section with all `audiobuilder plugin` commands
    - Keep all existing content (legacy flat-file guide) intact
    - _Per: docs-update.md — PLUGIN_GUIDE.md updates when plugins/ or discovery.py changes_

  - [x] 24.2 Update `docs/USERGUIDE.md`
    - Add a "Plugin Management" section with:
      - Installing plugins (CLI, SDK, API)
      - Listing and searching plugins
      - Enabling and disabling plugins
      - Uninstalling plugins
      - Writing a manifest-based plugin
    - Add `audiobuilder plugin` commands to the CLI Reference section
    - Add `Pipeline.install_plugin()` to the Python SDK section
    - _Per: docs-update.md — USERGUIDE.md updates for new CLI commands and SDK methods_

  - [x] 24.3 Update `docs/API_REFERENCE.md`
    - Add `/api/v1/plugins/` section with all 7 endpoints, request/response schemas, and error codes
    - _Per: docs-update.md — API_REFERENCE.md updates for new endpoints_

  - [x] 24.4 Update `docs/ARCHITECTURE.md`
    - Add a "Phase 5 — Plugin Ecosystem" section describing the new `app/core/plugins/` package and its integration with `AutoDiscovery` and `NodeRegistry`
    - _Per: docs-update.md — ARCHITECTURE.md updates for major structural changes_

  - [x] 24.5 Update `docs/SDK_AND_CLI.md`
    - Add `Pipeline.install_plugin()` to the SDK reference
    - Add `audiobuilder plugin` subcommand group to the CLI reference
    - _Per: docs-update.md — SDK_AND_CLI.md updates when sdk.py or cli/main.py changes_

- [x] 25. Create `plugin-ecosystem.md` steering file
  - Create `.kiro/steering/plugin-ecosystem.md` with:
    - `fileMatchPattern: "app/core/plugins/**"`
    - Component overview table (PluginManager, PluginStore, PluginLoader, etc.)
    - Key invariants (PluginStore is the source of truth, PluginManager is the single entry point)
    - Error hierarchy reference
    - Environment variables reference
    - Common patterns (install from local dir, install from index, enable/disable)
  - _Per: update-protocol.md — Index Maintenance: add new steering file to project-overview.md_
