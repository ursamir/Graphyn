---
inclusion: fileMatch
fileMatchPattern: "app/core/plugins/**"
---

# Plugin Ecosystem — Internals

All plugin lifecycle logic lives in `app/core/plugins/`. `PluginManager` is the single entry point — CLI, REST API, and SDK all delegate to it. Never call `PluginLoader`, `PluginStore`, or `PluginInstaller` directly from outside this package.

## Component Map

| Component | File | Responsibility |
|---|---|---|
| `PluginManager` | `manager.py` | Orchestrates install, uninstall, enable, disable, startup loading |
| `PluginInstaller` | `installer.py` | Resolves source strings (local path, git URL, HTTP archive, index name) |
| `PluginLoader` | `loader.py` | Validates manifest, checks compat/deps, imports entry points, registers node types |
| `PluginStore` | `store.py` | Persists `PluginRecord` objects as JSON under `workspace/plugins/` |
| `PluginIndexClient` | `index.py` | Fetches/searches remote plugin index (`GRAPHYN_PLUGIN_INDEX_URL`) |
| `PluginManifest` | `manifest.py` | Pydantic model for `plugin.toml`; `load_manifest(plugin_dir)` is the public loader |
| `DependencyChecker` | `dependencies.py` | Verifies PEP 508 dependency strings against current environment |

## `PluginLoader` Load Sequence

`PluginLoader.load(plugin_dir)` runs in order:

1. Parse manifest → `PluginManifest` (raises `PluginManifestError`)
2. Check `platform_version` specifier (raises `PluginCompatibilityError`)
3. Check `min_python` (raises `PluginCompatibilityError`)
4. Verify `dependencies` via `DependencyChecker` (raises `PluginDependencyError`)
5. Import each `entry_points` file via `AutoDiscovery._import_file` + `_process_module`
6. Return sorted list of newly registered `node_type` strings

Individual entry-point failures → WARNING + skip; remaining entry points still load.

## Key Invariants

- `AutoDiscovery` is not bypassed — `PluginLoader` uses it internally to register node types
- `unregister()` is called on disable/uninstall — removes every contributed `node_type` from registry
- Startup loading failures are WARNING, not fatal
- Remote installs (git+, http://) run via `BackgroundTasks`; local path installs are synchronous

## `PluginManager` Full Method Reference

| Method | Returns | Raises |
|---|---|---|
| `install(source, upgrade=False)` | `PluginRecord` | `PluginAlreadyInstalledError`, `PluginManifestError`, `PluginCompatibilityError`, `PluginDependencyError`, `PluginInstallError` |
| `uninstall(name)` | `None` | `PluginNotFoundError` |
| `enable(name)` | `PluginRecord` | `PluginNotFoundError` |
| `disable(name)` | `PluginRecord` | `PluginNotFoundError` |
| `list_installed()` | `list[PluginRecord]` | — |
| `get(name)` | `PluginRecord` | `PluginNotFoundError` |
| `load_enabled_plugins()` | `None` | — (failures logged, not raised) |

## Error Hierarchy

```
PluginError
├── PluginManifestError         # missing/malformed manifest
├── PluginCompatibilityError    # platform_version or min_python not satisfied
├── PluginDependencyError       # PEP 508 dependency not installed
├── PluginInstallError          # source fetch/extract failure
├── PluginNotFoundError         # name not in PluginStore (also KeyError)
├── PluginAlreadyInstalledError # install() without upgrade=True
└── PluginIndexError            # remote index fetch/parse failure
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `GRAPHYN_PLUGINS_DIR` | `"plugins"` | Install directory |
| `GRAPHYN_PLUGIN_AUTO_INSTALL` | `""` | `"1"` or `"true"` to auto-install pip deps |
| `GRAPHYN_PLUGIN_INDEX_URL` | `""` | Remote index URL |
| `GRAPHYN_HOME` | `~/.graphyn/` | `PluginStore` writes to `{GRAPHYN_HOME}/plugins/` |
| `GRAPHYN_PLUGIN_ALLOWED_SOURCES` | `""` | Comma-separated URL prefixes; empty = allow all. When set, remote sources not matching any prefix are rejected with `PluginInstallError` (SEC-6 fix) |
| `GRAPHYN_PLUGIN_VENVS_DIR` | `{GRAPHYN_HOME}/plugins/venvs/` | Per-plugin isolated virtualenvs for `runtime = "isolated"` |
| `GRAPHYN_TF_DEVICE` | unset (GPU allowed) | Set `cpu` to hide CUDA from TensorFlow. Default allows GPUs with memory growth so other apps keep their VRAM. |
| `GRAPHYN_TF_FORCE_GPU` | unset | Set `1` to force Keras GPU even on unsupported compute capability (≥12 / Blackwell). |

### Dependency isolation (hybrid)

- Every plugin declares `dependencies` + `optional_dependencies` (PEP 508) in `plugin.toml`.
- Default `runtime = "inprocess"`: deps checked/installed into the shared platform venv; `DependencyChecker` refuses installs that contradict `PLATFORM_CONSTRAINTS` (numpy/pydantic/packaging).
- `runtime = "isolated"` (trainer, edge-optimizer, realtime-inference): create `{GRAPHYN_PLUGIN_VENVS_DIR}/<plugin>/` with `--system-site-packages`, install required deps there, write `requirements.lock`. `NodeExecutor` runs `process()` via `python -m app.core.plugins.worker` (pickle IPC).
- API: `GET/POST /api/v1/plugins/{name}/dependencies[/install]`, `POST /api/v1/plugins/venvs/gc`.
- Uninstall removes the plugin venv; `gc_plugin_venvs()` drops orphans.

### Trainer / ModelBuilder (Keras) device placement

- Device choice via `app.core.tf_runtime.select_keras_device()` (`auto`|`cpu`|`gpu`, plus env).
- Compute capability ≥ 12 (e.g. RTX 5070 Ti) → **CPU by default** — current TF wheels lack CUDA kernels / libdevice; GPU `fit` fails with XLA/JIT errors. Override with `GRAPHYN_TF_FORCE_GPU=1`.
- **CPU fit:** soft placement off + entire `fit` under `tf.device("/CPU:0")` (required when a GPU is still visible).
- **GPU fit:** soft placement on; do not wrap `fit` in `/GPU:0` (tf.data RangeDataset is CPU-only). On failure, clone+recompile on CPU and retry with the CPU fit pattern.
- After editing `PluginPackage/Common/trainer/`, reinstall with upgrade and restart the API.
