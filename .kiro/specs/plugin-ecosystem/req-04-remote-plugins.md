# req-04 — Remote Plugin Installation

## Introduction

`PluginInstaller` fetches plugin packages from remote sources and prepares them for installation by `PluginManager`. Three remote source types are supported: Git repositories, HTTP archives (`.zip` / `.tar.gz`), and plugin index lookups by name. Local directory and archive paths are also supported for development workflows.

## Glossary

- **PluginInstaller** — Component that resolves a source string to a local plugin directory and hands it to `PluginManager`.
- **PluginInstallError** — Exception raised when a remote fetch, extraction, or validation step fails.
- **source string** — The argument passed to `plugin install`. May be a Git URL, HTTP URL, plugin name, local path, or `name==version` specifier.

## Requirement 5: Remote Plugin Installation

**User Story:** As a developer, I want to install plugins from remote sources (Git repositories, HTTP archives, plugin index), so that I can share and consume plugins without manual file copying.

### Acceptance Criteria

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

## Source String Resolution Logic

```
source string
├── starts with "git+" or ends with ".git"  → Git clone
├── starts with "http://" or "https://"
│   ├── ends with ".zip" or ".tar.gz"       → HTTP archive download
│   └── other                               → treat as Git URL
├── is an existing local directory           → local directory copy
├── is an existing local file (.zip/.tar.gz) → local archive extract
└── plain name (optionally with ==version)  → plugin index lookup → resolved URL
```

## Implementation Notes

- Use `httpx` (already a project dependency via FastAPI) for HTTP downloads with a 30-second timeout.
- Use `subprocess.run(["git", "clone", "--depth", "1", url, tmpdir])` for Git clones.
- Use Python stdlib `zipfile` and `tarfile` for archive extraction.
- Use `tempfile.TemporaryDirectory()` as a context manager to guarantee cleanup.
- The `PluginInstaller` is a stateless class with a single `resolve(source) -> Path` method that returns the local plugin directory path.

## File Location

`app/core/plugins/installer.py`
