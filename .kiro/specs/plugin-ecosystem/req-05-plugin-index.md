# req-05 — Plugin Index and Marketplace

## Introduction

The plugin index is a JSON document that lists available plugins with their metadata and download URLs. It can be hosted remotely (configured via `GRAPHYN_PLUGIN_INDEX_URL`) or stored locally at `workspace/plugins/index.json`. The `PluginIndexClient` fetches, caches, and searches the index.

## Glossary

- **PluginIndexClient** — Component that fetches and searches the plugin index.
- **PluginIndexEntry** — A single entry in the index representing one available plugin version.
- **PluginIndexError** — Exception raised when the index cannot be fetched or parsed.
- **GRAPHYN_PLUGIN_INDEX_URL** — Environment variable that points to the remote index URL.

## Requirement 6: Plugin Index and Marketplace

**User Story:** As a developer, I want to browse and search a registry of available plugins, so that I can discover and install plugins by name without knowing their source URLs.

### Acceptance Criteria

1. THE Plugin_Index_Format SHALL be a JSON document with a top-level `plugins` array, where each entry contains: `name`, `version`, `description`, `author`, `tags`, `platform_version`, `download_url`, and optionally `homepage` and `checksum`.
2. WHEN the `GRAPHYN_PLUGIN_INDEX_URL` environment variable is set, THE PluginIndexClient SHALL fetch the index from that URL using an HTTP GET request with a 10-second timeout.
3. WHEN `GRAPHYN_PLUGIN_INDEX_URL` is not set, THE PluginIndexClient SHALL look for a local index file at `workspace/plugins/index.json`.
4. WHEN neither a remote URL nor a local index file is available, THE PluginIndexClient SHALL return an empty index and log a WARNING.
5. WHEN a search query is provided, THE PluginIndexClient SHALL return all index entries where the query string appears (case-insensitive) in the `name`, `description`, or `tags` fields.
6. WHEN a plugin index entry declares a `checksum` field (SHA-256 hex digest), THE PluginInstaller SHALL verify the downloaded archive against the checksum and raise a `PluginInstallError` if the checksum does not match.
7. THE PluginIndexClient SHALL cache the fetched remote index in memory for the duration of the process (no disk caching).
8. WHEN the remote index fetch fails, THE PluginIndexClient SHALL raise a `PluginIndexError` with the URL and error detail.
9. THE Plugin_Index_Format SHALL support a `schema_version` field at the top level for forward compatibility.

## Reference: Canonical Index Format

```json
{
  "schema_version": "1.0",
  "plugins": [
    {
      "name": "audio-denoiser",
      "version": "1.2.0",
      "description": "Spectral subtraction denoiser for audio pipelines.",
      "author": "Jane Smith",
      "tags": ["audio", "denoising"],
      "platform_version": ">=5.0,<6.0",
      "download_url": "https://example.com/plugins/audio-denoiser-1.2.0.zip",
      "homepage": "https://github.com/example/audio-denoiser",
      "checksum": "sha256:abc123..."
    }
  ]
}
```

## Implementation Notes

- `PluginIndexClient` is a stateless class with `fetch() -> list[PluginIndexEntry]` and `search(query) -> list[PluginIndexEntry]` methods.
- In-memory cache: store the fetched list as a class-level or instance-level attribute after the first fetch.
- Use `httpx.get(url, timeout=10)` for remote fetches.
- `PluginIndexEntry` is a Pydantic model with all index entry fields.
- `lookup(name, version_constraint=None) -> PluginIndexEntry` raises `PluginIndexError` if not found.

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `GRAPHYN_PLUGIN_INDEX_URL` | `""` | Remote plugin index URL |

## File Location

`app/core/plugins/index.py`
