# req-06 — CLI Interface

## Introduction

The `audiobuilder plugin` subcommand group provides a complete command-line interface for plugin management. It follows the same pattern as the existing `audiobuilder artifacts` and `audiobuilder runs` subcommand groups.

## Requirement 7: CLI Interface

**User Story:** As a developer, I want to manage plugins from the command line, so that I can install, list, enable, disable, remove, and search plugins without writing Python code.

### Acceptance Criteria

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

## Command Reference

```
audiobuilder plugin install <source> [--upgrade]
audiobuilder plugin list [--enabled]
audiobuilder plugin enable <name>
audiobuilder plugin disable <name>
audiobuilder plugin remove <name>
audiobuilder plugin search <query>
audiobuilder plugin info <name>
```

## Example Output

```
$ audiobuilder plugin install audio-denoiser
✓ Installed audio-denoiser 1.2.0

$ audiobuilder plugin list
NAME              VERSION   STATUS    SOURCE
audio-denoiser    1.2.0     enabled   audio-denoiser

$ audiobuilder plugin search denois
NAME              VERSION   DESCRIPTION                              TAGS
audio-denoiser    1.2.0     Spectral subtraction denoiser...         audio, denoising

$ audiobuilder plugin disable audio-denoiser
✓ Disabled audio-denoiser

$ audiobuilder plugin remove audio-denoiser
✓ Removed audio-denoiser
```

## Implementation Notes

- Add `plugin_parser = subparsers.add_parser("plugin", ...)` to `build_parser()` in `app/cli/main.py`.
- All `cmd_plugin_*` functions delegate to `PluginManager` — no direct store or loader access.
- Error handling: catch `PluginNotFoundError`, `PluginCompatibilityError`, `PluginDependencyError`, `PluginInstallError`, `PluginAlreadyInstalledError` and print a user-friendly message before `sys.exit(1)`.
- Table formatting follows the same column-width pattern as `cmd_artifacts_list`.
