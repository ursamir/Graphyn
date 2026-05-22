# tasks-05 — CLI, REST API, and SDK

## Overview

Add the `audiobuilder plugin` CLI subcommand group, the `/api/v1/plugins/` REST router, and the `Pipeline.install_plugin()` SDK method. All three delegate to `PluginManager`. These depend on tasks-03.

## Tasks

- [x] 17. Implement `audiobuilder plugin` CLI subcommand group (`app/cli/main.py`)
  - [x] 17.1 Implement `cmd_plugin_install`, `cmd_plugin_list`, `cmd_plugin_enable`, `cmd_plugin_disable`, `cmd_plugin_remove`, `cmd_plugin_search`, `cmd_plugin_info`
    - Each function delegates to `PluginManager` (or `PluginIndexClient` for search)
    - Error handling: catch all `PluginError` subclasses, print user-friendly message, `sys.exit(1)`
    - `cmd_plugin_list`: print table with columns `NAME`, `VERSION`, `STATUS`, `SOURCE`; support `--enabled` filter
    - `cmd_plugin_search`: print table with columns `NAME`, `VERSION`, `DESCRIPTION`, `TAGS`
    - `cmd_plugin_info`: print `PluginRecord` JSON for installed plugins; fall back to index entry for uninstalled
    - _Requirements: req-06 §7.1–§7.11_

  - [x] 17.2 Register `plugin` subparser in `build_parser()`
    - Add `plugin_parser = subparsers.add_parser("plugin", ...)` with sub-subparsers: `install`, `list`, `enable`, `disable`, `remove`, `search`, `info`
    - `install`: positional `source`, optional `--upgrade` flag
    - `list`: optional `--enabled` flag
    - `enable`, `disable`, `remove`, `info`: positional `name`
    - `search`: positional `query`
    - _Requirements: req-06 §7.1_

  - [x]* 17.3 Write unit tests for CLI plugin subcommand
    - Create `tests/test_plugins_cli.py`
    - Test `build_parser()` includes `plugin` subcommand with all 7 sub-subcommands
    - Test `plugin install <local_dir>` prints success message and exits 0
    - Test `plugin install <nonexistent>` prints error and exits 1
    - Test `plugin list` prints table header and exits 0
    - Test `plugin list` prints "No plugins installed." when empty
    - Test `plugin list --enabled` filters to enabled only
    - Test `plugin enable <name>` prints confirmation and exits 0
    - Test `plugin enable <nonexistent>` exits 1
    - Test `plugin disable <name>` prints confirmation and exits 0
    - Test `plugin remove <name>` prints confirmation and exits 0
    - Test `plugin search <query>` prints table and exits 0
    - Test `plugin info <installed_name>` prints JSON and exits 0
    - Test `plugin info <nonexistent>` exits 1
    - Use `tmp_path` and mock `PluginManager` methods
    - _Requirements: req-06 §7.1–§7.11_

- [x] 18. Implement REST API `/api/v1/plugins/` (`app/api/routers/plugins.py`)
  - [x] 18.1 Create `plugins.py` router with all endpoints
    - `GET /plugins` → `PluginManager().list_installed()`
    - `POST /plugins/install` → `PluginManager().install(source, upgrade)` (async for remote sources)
    - `GET /plugins/search?q=` → `PluginIndexClient().search(q)`
    - `GET /plugins/{name}` → `PluginManager().get(name)`
    - `POST /plugins/{name}/enable` → `PluginManager().enable(name)`
    - `POST /plugins/{name}/disable` → `PluginManager().disable(name)`
    - `DELETE /plugins/{name}` → `PluginManager().uninstall(name)`
    - Error mapping: `PluginNotFoundError` → 404, `PluginAlreadyInstalledError` → 409, `PluginCompatibilityError`/`PluginDependencyError` → 422, `PluginInstallError`/`PluginIndexError` → 502
    - _Requirements: req-07 §8.1–§8.10_

  - [x] 18.2 Register `plugins_router` in `app/api/main.py`
    - Import `router as plugins_router` from `app.api.routers.plugins`
    - Add `app.include_router(plugins_router, prefix="/api/v1", dependencies=_deps)`
    - _Requirements: req-07 §8.1_

  - [x]* 18.3 Write unit tests for plugins REST API
    - Create `tests/test_plugins_api.py`
    - Test `GET /api/v1/plugins` returns `[]` when no plugins installed
    - Test `GET /api/v1/plugins` returns list of `PluginRecord` dicts after install
    - Test `POST /api/v1/plugins/install` with local source → `{"name": ..., "version": ..., "status": "installed"}`
    - Test `POST /api/v1/plugins/install` with remote source → `{"status": "installing", "name": ...}`
    - Test `POST /api/v1/plugins/install` duplicate without upgrade → 409
    - Test `GET /api/v1/plugins/{name}` returns `PluginRecord` dict
    - Test `GET /api/v1/plugins/{name}` for unknown → 404
    - Test `POST /api/v1/plugins/{name}/enable` → `{"name": ..., "enabled": true}`
    - Test `POST /api/v1/plugins/{name}/disable` → `{"name": ..., "enabled": false}`
    - Test `DELETE /api/v1/plugins/{name}` → `{"name": ..., "status": "uninstalled"}`
    - Test `DELETE /api/v1/plugins/{name}` for unknown → 404
    - Test `GET /api/v1/plugins/search?q=denois` returns matching entries
    - Use `TestClient` from `fastapi.testclient` and mock `PluginManager`
    - _Requirements: req-07 §8.1–§8.10_

- [x] 19. Add `Pipeline.install_plugin()` to SDK (`app/core/sdk.py`)
  - Add `install_plugin(self, source: str, upgrade: bool = False) -> "PluginRecord"` method to `Pipeline` class
  - Implementation: `from app.core.plugins.manager import PluginManager; return PluginManager().install(source, upgrade=upgrade)`
  - Add docstring with Args and Returns
  - _Requirements: req-08 §9.9_

  - [x]* 19.1 Write unit test for `Pipeline.install_plugin()`
    - Test `pipeline.install_plugin(local_dir)` returns `PluginRecord`
    - Test `pipeline.install_plugin(local_dir, upgrade=True)` passes `upgrade=True` to `PluginManager`
    - Mock `PluginManager.install` to avoid real filesystem operations
    - _Requirements: req-08 §9.9_

- [x] 20. Checkpoint — verify all existing tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions.
  - Ask the user if questions arise.
