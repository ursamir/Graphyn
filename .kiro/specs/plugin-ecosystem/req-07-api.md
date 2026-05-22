# req-07 — REST API

## Introduction

The `/api/v1/plugins/` router exposes plugin management operations over HTTP. It follows the same pattern as the existing `artifacts.py` router. All operations delegate to `PluginManager`.

## Requirement 8: REST API

**User Story:** As an API consumer, I want REST endpoints for plugin management, so that I can integrate plugin operations into automated workflows and the frontend.

### Acceptance Criteria

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

## Endpoint Summary

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/plugins` | List all installed plugins |
| `POST` | `/api/v1/plugins/install` | Install a plugin from a source |
| `GET` | `/api/v1/plugins/{name}` | Get a specific installed plugin |
| `POST` | `/api/v1/plugins/{name}/enable` | Enable a plugin |
| `POST` | `/api/v1/plugins/{name}/disable` | Disable a plugin |
| `DELETE` | `/api/v1/plugins/{name}` | Uninstall a plugin |
| `GET` | `/api/v1/plugins/search?q=` | Search the plugin index |

## Error Code Mapping

| Exception | HTTP Status |
|---|---|
| `PluginNotFoundError` | 404 |
| `PluginAlreadyInstalledError` | 409 |
| `PluginCompatibilityError` | 422 |
| `PluginDependencyError` | 422 |
| `PluginInstallError` | 502 |
| `PluginIndexError` | 502 |

## Implementation Notes

- Create `app/api/routers/plugins.py` with `router = APIRouter(prefix="/plugins", tags=["plugins"])`.
- Register in `app/api/main.py` with `app.include_router(plugins_router, prefix="/api/v1", dependencies=_deps)`.
- Async install uses `asyncio.get_event_loop().run_in_executor(None, PluginManager().install, source, upgrade)`.
- Use FastAPI `HTTPException` for error responses.
