# Plugin Dependency Isolation — Architecture Review

**Branch:** `cursor/plugin-dep-isolation` (`122417d` + follow-on `9786a43 c1`)
**Vs:** `master` @ `da0530d` (O9)
**Reviewer lens:** isolation guarantees first; surrounding architecture second.
**Method:** code-backed. Docs were treated as claims and checked against source.
**Date:** 2026-09-02
**Scope:** read-only. No production code was changed.

---

## Executive verdict

This branch adds an **opt-in hybrid isolation mode**, not a plugin sandbox.

- Default remains **in-process**: plugin code, pip deps, and `process()` share the API/MCP/CLI interpreter.
- `runtime = "isolated"` (3 of 30 first-party plugins) creates a per-plugin venv and runs **`process()`** in a subprocess worker.
- Isolation is **incomplete relative to the commit message** ("conflicting stacks cannot break the shared platform environment"):
  1. Isolated plugins are still **imported into the host** at load time.
  2. `NodeExecutor.setup()` still runs in the **host** before the worker, so `RealtimeInferenceNode.setup()` loads TF/Torch/ONNX in the API process.
  3. Venvs are created with **`system_site_packages=True`**, so the worker sees the base interpreter's packages.
  4. Optional heavy deps are **not** installed at load; the worker will happily import host TF/Torch via system site-packages.
  5. IPC is **pickle**, so a plugin can execute code in the host on `pickle.load`.
  6. Lookup failures in `NodeExecutor._process` **silently fall back** to in-process execution.

Treat this as a **dependency-conflict mitigation for trusted first-party nodes that lazy-import heavy stacks**, not as process/package isolation for third-party plugins.

**Do not merge as-is if the product goal is "plugins cannot affect the host interpreter."** Merge is reasonable only if the goal is narrowed in docs and the setup-in-host + silent-fallback bugs are fixed.

---

## 1. Intent of this branch vs master

### 1.1 What landed (isolation commit `122417d`)

Commit message:

> Plugins can declare `runtime=isolated`, install deps into a dedicated venv, and execute via a subprocess worker so conflicting ML stacks do not break the shared platform environment.

Design that actually exists:

| Mechanism | Used? | Where |
|---|---|---|
| Per-plugin venv | Yes, opt-in | `PluginVenvManager` (`app/core/plugins/venv_manager.py`) |
| Subprocess worker | Yes, for `process()` only | `isolated_executor.py` + `worker.py` |
| Pickle file IPC | Yes | tempfile dir, `inputs.pkl` / `outputs.pkl` |
| `runtime` manifest field | Yes | `PluginManifest.runtime`: `inprocess` \| `isolated` |
| `PYTHONPATH` mutation | Yes (host → worker) | `isolated_executor.run_isolated_node` prepends repo root |
| `system_site_packages` | Yes, default **True** | `PluginVenvManager.ensure()` |
| Lockfile | Write-only `pip freeze` | `{venv}/requirements.lock` — never read back |
| Pip extras | No | — |
| Namespace packages | Accidental, via hashed `_graphyn_plugin_*` module names | `AutoDiscovery._import_file` |
| importlib file load | Yes, **host and worker** | `spec_from_file_location` |
| Containers / separate OS users / seccomp | No | — |

First-party plugins flipped to `isolated`:

- `PluginPackage/Common/trainer/plugin.toml`
- `PluginPackage/Common/edge_optimizer/plugin.toml`
- `PluginPackage/Common/realtime_inference/plugin.toml`

The other **27** plugins stay `runtime = "inprocess"` (default).

### 1.2 Problem it is solving

Real problem: first-party ML nodes (trainer / TFLite / ONNX / Torch) pull conflicting native stacks into the **shared platform venv**. `DependencyChecker.PLATFORM_CONSTRAINTS` already refuses shared-env installs that fight `numpy` / `pydantic` / `packaging`, but it cannot make Torch and TensorFlow coexist, and it cannot stop `process()` from importing them into uvicorn/MCP.

The hybrid design tries to:

1. Keep lightweight plugins in-process (low overhead, typed ports, shared `AudioSample`).
2. Park conflicting required deps in `{GRAPHYN_PLUGIN_VENVS_DIR}/<name>/`.
3. Run `process()` under that venv's Python.

That is a reasonable **incremental** design. It is not implemented far enough to match the claim in the commit message or in `.kiro/steering/plugin-ecosystem.md` ("conflicting stacks cannot break the platform env").

### 1.3 What is incomplete

- Host still imports plugin entry points (`PluginLoader._import_entry_points`).
- Host still constructs the node and calls `setup()` (`orchestrator` → `NodeExecutor.setup()`).
- Worker is a **cold subprocess per `process()` call** (no pool, no timeout from `NodeExecutor`).
- Optional deps (`torch`, `tensorflow`, `onnxruntime`) are **not** installed into the venv at load.
- Lockfile is not used for reproducibility.
- Streaming path (`NodeExecutor.execute_stream`) never calls the isolated worker.
- CLI/SDK cannot pass `expected_sha256`.
- Docs/steering still describe the old `PluginLoader` 4-step sequence in places (shared-env `DependencyChecker` only).

### 1.4 Branch hygiene (merge risk, not isolation)

`master..HEAD` is two commits:

1. `122417d` — isolation feature (the review target).
2. `9786a43` **`c1`** — ~72k-line dump: deletes `.kiro/specs/**` and `review_agent_work/**`, adds `.cursor/rules`, `graphyn-ui`, pytest tweaks.

Merging this branch onto master as-is is **not** "just plugin isolation." Split `c1` or rebase isolation onto master without the spec deletion before any product merge.

---

## 2. Isolation guarantees (verified)

### 2.1 How plugins are installed, imported, executed

```
install source
  → PluginInstaller.resolve()          # git / http zip|tar.gz / local / index
  → copy to {plugins_home()}/{name}/
  → PluginLoader.load()
       parse plugin.toml
       if runtime==isolated:
           PluginVenvManager.ensure(name, manifest.dependencies)  # NOT optional_deps
           get_runtime_registry().register(IsolatedPluginSpec)
       else:
           DependencyChecker().check(manifest.dependencies)       # host env
       AutoDiscovery._import_file(entry_point)   # HOST process, always
       register Node subclasses on host NodeRegistry

execute graph
  → get_backend().execute() → orchestrator
  → NodeExecutor.setup()     # HOST node.setup() — always
  → NodeExecutor._process()
       if runtime_registry has node_type:
           pickle inputs; subprocess: {venv}/bin/python -m app.core.plugins.worker
           worker: import plugin again, node.setup(), node.process(), pickle outputs
       else:
           node.process() in host
```

Canonical symbols:

- `PluginLoader.load` — `app/core/plugins/loader.py`
- `PluginVenvManager.ensure` — `app/core/plugins/venv_manager.py`
- `PluginRuntimeRegistry` — `app/core/plugins/runtime_registry.py`
- `NodeExecutor._process` — `app/core/node_executor.py`
- `run_isolated_node` — `app/core/plugins/isolated_executor.py`
- `worker._run` — `app/core/plugins/worker.py`

### 2.2 Can a plugin's pip deps leak into the host process?

| Path | Leak? |
|---|---|
| Isolated **required** deps (`ensure(..., check_platform=False)`) | Installed into the plugin venv, **not** `sys.executable`. Host `pip` is not used. |
| Isolated **optional** deps | Only if someone calls `POST /plugins/{name}/dependencies/install?include_optional`. Load does not install them. |
| In-process deps | **Yes, by design.** `DependencyChecker.install()` runs `[sys.executable, -m, pip, install, ...]`. |
| Isolated plugin **import at load** | Host `exec_module` uses **host** `sys.path`. A module-level `import torch` loads host Torch (or fails). Packages that exist only in the plugin venv are **not** importable in the host — load then fails (`PluginInstallError` if no node types register). |
| `system_site_packages=True` | Worker can **see host/base packages**. Host cannot see plugin-venv site-packages unless those packages were also installed in the host. |

So: isolated **install** does not `pip install` into the host. Isolated **import/execute** still uses the host interpreter for load + `setup()`. That is the gap.

First-party isolated nodes currently import at module level:

- `numpy`, `app.core.nodes.*`, `app.models.*` (host-safe)
- Torch/TF/ONNX only inside `process()` / `setup()` / helpers (lazy)

`TrainerNode` has no `setup()` override, so its heavy imports happen in `process()` → worker. `RealtimeInferenceNode.setup()` is the counterexample (see findings).

### 2.3 Can plugins see each others' packages?

- **In-process plugins:** one `sys.path`, one `sys.modules`. Yes.
- **Two isolated venvs:** separate `{GRAPHYN_PLUGIN_VENVS_DIR}/<name>/`. Worker's `sys.path` does not include sibling venvs. They do **not** see each other's venv-only packages.
- **Both isolated + `system_site_packages=True`:** both see the **same** base/host packages. Shared global native state in the host is still possible via load/`setup()`, and both workers can load the same host TF/Torch if optional deps were not installed into the venv.

### 2.4 Shared global state / sys.path / env / cwd / native extensions

| Channel | Isolated worker | Host during load/`setup()` |
|---|---|---|
| `sys.path` | venv site-packages + system site-packages + `PYTHONPATH=repo_root` prepended | Unchanged; plugin file exec'd via importlib |
| `sys.modules` | Fresh process | Polluted by `_graphyn_plugin_{dir}_{md5[:8]}.{stem}` |
| `sitecustomize` | Not created by `EnvBuilder`; base interpreter's may apply via system site-packages | Host's |
| `PYTHONPATH` | Host env copied, then repo root **prepended** | If the host already had `PYTHONPATH` (e.g. host venv `site-packages`), that is inherited by the worker |
| `os.environ` | `os.environ.copy()` — **all host secrets** (`GRAPHYN_API_TOKEN`, cloud keys, `VIRTUAL_ENV`, `CUDA_*`) | Shared |
| cwd | Not set. Inherits host cwd. Relative writes (`workspace/artifacts/models`) hit the host tree | Shared |
| Native extensions | Loaded in worker **if** `process()` is the first import. Loaded in **host** if `setup()` or module-level import runs first | See realtime-inference |
| GPU / TF global config | Worker is a new process, so TF session state is separate — **unless** host `setup()` already initialized TF in uvicorn | `initialize_registry()` also calls `configure_tf_stable_defaults()` in the **host** |

`isolated_executor.py` PYTHONPATH construction:

```python
env = os.environ.copy()
project_root = str(Path(__file__).resolve().parents[3])
prev = env.get("PYTHONPATH", "")
env["PYTHONPATH"] = project_root if not prev else f"{project_root}{os.pathsep}{prev}"
```

The worker **must** import `app.core.*` from the host source tree (plugins are not a separate SDK). Combined with `system_site_packages=True` and `check_platform=False`, a plugin that pip-installs `pydantic<2` into its venv can break **worker bootstrap** (`PluginManifest` is Pydantic v2). Platform constraints are explicitly skipped for isolated installs.

### 2.5 IPC and pickle

`run_isolated_node` pickles the full `inputs` dict (often `AudioSample` / `ModelArtifact` / numpy arrays) to a temp file, then `pickle.load`s worker outputs in the host.

Consequences:

- Version skew of numpy/pydantic between host and worker can fail unpickle or worse (native crashes).
- `pickle.load` of worker output is **arbitrary code execution in the host** if the plugin is untrusted.
- No timeout is passed from `NodeExecutor` (`timeout=None` on `subprocess.run`).
- Temp dir cleanup is best-effort; extra files would block `rmdir`.

This IPC is acceptable only under a **trusted-plugin** threat model.

### 2.6 Hunch — confirmed

> Isolation may be incomplete if plugins still import into the same Python process as the API/MCP server.

Confirmed:

- `initialize_registry()` → `PluginManager.load_enabled_plugins()` → `PluginLoader.load()` → `discovery._import_file` / `_process_module` in the **server process**.
- Isolated or not, the `Node` class object lives in the host registry.
- `LocalPythonBackend` still runs the orchestrator in-process; isolation is a per-node subprocess **beside** that process, not instead of it.

---

## 3. Trust boundary

Plugins are executable Python. Isolation here is **not** a security boundary. Existing controls:

### 3.1 Install sources — `PluginInstaller.resolve`

Order: `git+` / `.git` → HTTP `.zip`/`.tar.gz` → local dir/archive → index name.

### 3.2 Allowlist `GRAPHYN_PLUGIN_ALLOWED_SOURCES`

- Implemented in `PluginInstaller._check_allowed_source`.
- **Default empty = allow all** (`plugin_allowed_sources()`).
- Prefix `startswith` only; checked when source starts with `git+`, `http://`, `https://`.
- **Not applied to:**
  - Local paths (documented).
  - Index lookups by **plain name** — `_resolve_index` downloads `entry.download_url` with **no** allowlist check.
  - Redirect targets — `_download_with_limit` uses `httpx.stream(..., follow_redirects=True)`.
  - `PluginIndexClient._fetch_remote` (index JSON URL).
  - Pip requirements (PEP 508 direct URLs like `pkg @ https://evil/pkg.whl` pass `Requirement()` validation and are `pip install`ed).

CLI (`cmd_plugin_install`) and SDK (`Pipeline.install_plugin`) do not accept `expected_sha256`. Only REST `InstallRequest` and `PluginManager.install(..., expected_sha256=)` do.

### 3.3 Checksums

- Optional `expected_sha256` for HTTP archives; ignored for git and local paths.
- Index entries may carry `checksum`; `_resolve_index` verifies **if present**.
- Git: `--depth 1`, no commit pin, no checksum.
- Not required. Supply-chain is honor-system.

### 3.4 Zip-slip / archives

TAR: rejects `issym`/`islnk`, then `is_relative_to()` on `member.name`.

ZIP: `is_relative_to()` on `member.filename`, then `ZipFile.extractall`. **Does not reject ZIP symlink members.** Classic "symlink then write-through" zip is not covered. Python 3.12+ `filter="data"` is not used.

`_MAX_DOWNLOAD_BYTES = 100 MiB`. Git clone timeout 120s. HTTP timeout 30s.

Local `copytree(..., symlinks=True)` preserves outgoing symlinks in the plugin tree (runtime follow still possible).

### 3.5 Arbitrary code at import time

`plugin.toml` is data-only (`load_manifest` does not exec plugin code). The next step **does**: `spec.loader.exec_module(module)` in the host.

There is no allowlist of imports, no RestrictedPython, no subprocess for **load**. A plugin's `nodes.py` top-level code runs with the server's privileges at install and at every startup (`load_enabled_plugins`).

### 3.6 Lifecycle / AutoDiscovery / registry

- Startup: `initialize_registry()` loads enabled plugins from `PluginStore`, then `AutoDiscovery.run(plugins_dir=None)` so plugins are not double-scanned.
- Fallback: if `load_enabled_plugins` throws, AutoDiscovery scans `plugins_home()` and may emit duplicate-registration warnings.
- `PluginPackage/` is **source**. Production load is from `GRAPHYN_PLUGINS_DIR` / `{GRAPHYN_HOME}/plugins/installed/`. First-party nodes appear only after `PluginManager.install`.
- Disable unloads node types from `NodeRegistry` (`inspect.getfile` prefix match) but **does not** `unregister_plugin` on `PluginRuntimeRegistry` (uninstall does). Stale isolated routing after disable is a real bug (finding below).
- Duplicate `node_type`: first wins; later entry points log WARNING.

---

## 4. Architecture (surrounding)

### 4.1 Bounded contexts

| BC | Isolation touch |
|---|---|
| BC3 catalog | `plugins/*`, `nodes/discovery.py`, `nodes/__init__.py` |
| BC5 runtime | `node_executor._process` (isolation bridge), `worker` as a second runtime |
| BC2 node contract | Unchanged. Isolated nodes are still `Node` subclasses imported in-host |
| BC4 planner | Unaware of isolation |
| BC6 storage | Unaware; pickle inputs may include artifacts |

`isolated_executor` claims "BC3 / BC5" in its header. That is honest: isolation is a cross-cutting bolt-on, not a new backend.

### 4.2 RuntimeBackend / orchestrator

- Interfaces → `get_backend().execute()` → `LocalPythonBackend` → lazy `run_pipeline_ir`. Correct.
- No `IsolatedPluginBackend`. Isolation is inside `NodeExecutor`, so parallel/streaming/retry all share one accidental policy.
- Orchestrator always `NodeExecutor.setup()` for every node **before** any `process()` (`app/core/orchestrator.py` ~L145–153). Isolated nodes cannot skip host `setup()` without an orchestrator change.

### 4.3 PluginPackage vs `app/core/nodes`

Clean split: `app/core/nodes/` is framework only (12 files). Implementations live in `PluginPackage/`. Plugins import `app.models.*` (AudioSample, ModelArtifact, …). That forces the worker to have the **platform source** on `PYTHONPATH` and a compatible pydantic/numpy. Isolated plugins are not independently distributable wheels.

### 4.4 Domain leaks

`app/core/**` does not import `app.domain` (grep clean). Domain is used from API routers (`projects`, `ingest`, `system`). Matches the platform rule.

`resolve_capability` lives in `registry_runtime.py`. `orchestrator` re-exports a shim; `pipeline.py` re-exports that shim. CLI/MCP import `registry_runtime` directly. Acceptable, slightly messy.

### 4.5 Circular imports

| Pair | How |
|---|---|
| `discovery` → `PluginLoader` | Lazy inside `AutoDiscovery.run` |
| `PluginLoader` → `AutoDiscovery` | Module-level |
| `node_executor` → `isolated_executor` / `runtime_registry` | Lazy inside `_process` |
| `runtime_backend` → `orchestrator` | Lazy inside `execute` |

No hard import cycle. The `node_executor` lazy import is wrapped in `except Exception: spec = None` — that is a behavior bug, not just style.

### 4.6 Layering nits

- `PluginManager` docstring still says "Must not call PluginLoader… from outside this package" but the API router constructs `PluginManager` directly (correct). AutoDiscovery also constructs `PluginLoader` (exception to the rule, documented).
- Steering `plugin-ecosystem.md` "PluginLoader Load Sequence" step 4 still says `DependencyChecker` only — **docs disagree with code**.
- `config.plugins_home()` default is `{GRAPHYN_HOME}/plugins/installed/`. Steering table still says default `"plugins"`.
- `PLUGIN_GUIDE.md` quality checklist still tells authors to implement `setup()` for model load — which, for `runtime=isolated`, currently runs in the **host**.

---

## 5. Tests

### 5.1 What exists

`unit_test/core/plugins/test_dep_isolation.py` (101 lines):

- Manifest `runtime` default / `isolated` / invalid
- `DependencyChecker.status` optional vs required
- `check_conflicts(["numpy>=99"])` nonempty
- `PluginRuntimeRegistry` register/unregister
- `PluginVenvManager.ensure("tiny-plugin", ["pip"])` + `gc_unused`
- `PLATFORM_CONSTRAINTS` contains numpy

`unit_test/api/test_plugins_router.py` — mocked manager; covers `runtime` in list payload and `POST /venvs/gc`.

Older plugin tests (`test_dependencies.py`, `test_installer.py`, `test_loader.py`, `test_manager.py`) predate isolation and do **not** exercise worker/IPC/allowlist/zip-slip.

### 5.2 What would fail if isolation broke

Almost nothing that matters.

- If `NodeExecutor._process` stopped calling the worker, **no test would fail**.
- If isolated plugins ran entirely in-host, **no test would fail**.
- If `system_site_packages` were flipped or venvs started sharing site-packages, **no test would fail**.
- If `setup()` loaded Torch in the host, **no test would fail**.
- `test_venv_manager_create_and_gc` only proves a venv directory can be created and deleted.

### 5.3 Missing tests (priority)

1. **End-to-end isolated roundtrip:** plugin with `runtime=isolated`, unique dep installed only in its venv, `process()` returns a value; assert host `importlib` cannot import that dep; assert worker can.
2. **Host `setup()` must not run plugin `setup()`** for isolated nodes (or must no-op).
3. **Silent fallback:** mock `get_runtime_registry` to raise; isolated node must **not** silently `node.process()` in-host (or must fail closed).
4. **Disable then re-register same `node_type`:** must not route to the old venv.
5. **Two isolated plugins, conflicting pins** (e.g. `pkg==1` vs `pkg==2`) both `process()` successfully.
6. **Allowlist:** remote URL rejected; index `download_url` should be rejected too (today it is not — test would document the hole).
7. **ZIP slip + ZIP symlink.**
8. **Redirect off allowlist.**
9. **Streaming isolated node** (today always in-process).
10. **Worker pickle of a platform type** (`ModelArtifact`) round-trip.
11. **Timeout** / hung worker.
12. **Optional deps not in host:** isolated `process()` should fail clearly unless `include_optional` was used — not silently use host TF via system site-packages.

---

## 6. Findings

Severity key: **blocker** = isolation claim is false for a shipped isolated plugin or untrusted code can run in the host via the isolation path. **High** = real correctness/security hole. **Medium** = design gap or missing control. **Low** / **nit** = docs, API completeness.

### Blocker

**B1. Isolated `setup()` still runs in the host process**

- Files: `app/core/orchestrator.py` (L145–153), `app/core/node_executor.py` `setup()`, `PluginPackage/Common/realtime_inference/nodes.py` `setup()` / `_setup_tflite` / `_setup_pytorch` / `_setup_onnx`
- Why: Orchestrator calls `NodeExecutor.setup()` on the host node instance before any `_process`. `RealtimeInferenceNode.setup()` imports tensorflow/torch/onnxruntime and loads the model **in uvicorn/MCP**. The worker then constructs a **second** instance and `setup()`s again. Isolation for the one first-party plugin that actually uses `setup()` for weights is void; GPU memory can be doubled.
- Direction: For isolated node_types, skip host `setup()`/`teardown()` (or make them metadata-only). Run setup/process/teardown entirely in the worker. Consider a long-lived worker if setup is expensive.
- Not "working as designed": the steering text says `process()` runs in the worker so stacks cannot break the platform; it never authorized host `setup()` to load those stacks.

**B2. Isolated plugins are imported into the host at load**

- Files: `app/core/plugins/loader.py` `_import_entry_points`, `app/core/nodes/discovery.py` `_import_file`
- Why: `exec_module` runs plugin top-level code in the server. Unique venv-only imports fail the load; shared-name imports bind **host** packages into `sys.modules`. You cannot have a third-party isolated plugin whose `nodes.py` does `import tensorflow` at module level without either failing load or loading host TF.
- Direction: Host load of isolated plugins should parse metadata without executing plugin code (stub class, inspect AST, or import in the **venv** interpreter and send metadata over IPC). Register a host-side proxy `Node` whose `process`/`setup` only RPC to the worker.

**B3. Pickle IPC is a host RCE primitive (if plugins are untrusted)**

- Files: `app/core/plugins/isolated_executor.py` (`pickle.dump` / `pickle.load`), `app/core/plugins/worker.py`
- Why: Worker-controlled `outputs.pkl` is unpickled in the host. That is not a dependency-isolation issue; it is a trust-boundary issue. Docs (`PLUGIN_GUIDE.md` Security) discuss allowlists and checksums as if remote plugins are a threat, then isolation uses pickle.
- Direction: If plugins stay first-party/trusted, document "not a sandbox" and keep pickle. If third-party: switch to a constrained serializer (JSON + numpy savez, capnp, or artifact-store refs only).
- Classification note: **working as designed under a trusted-plugin model**; **blocker under the threat model implied by `GRAPHYN_PLUGIN_ALLOWED_SOURCES`**. Pick one model and align docs.

### High

**H1. `NodeExecutor._process` swallows registry/import errors and runs in-process**

```python
try:
    spec = get_runtime_registry().get_for_node(str(node_type))
except Exception:
    spec = None
if spec is not None:
    return run_isolated_node(...)
return node.process(inputs)
```

- File: `app/core/node_executor.py` `_process`
- Why: Any failure to import isolation machinery silently defeats isolation. Fail closed.
- Direction: If `node_type` is registered isolated, errors must raise. Do not catch `Exception` around the lookup.

**H2. `disable()` leaves `PluginRuntimeRegistry` entries**

- Files: `PluginManager.disable` vs `_do_uninstall`
- Why: Uninstall calls `get_runtime_registry().unregister_plugin`. Disable only `_unload_node_types`. A later in-process plugin (or re-enabled different plugin) reusing the same `node_type` is still routed to the old venv python.
- Direction: Unregister (and optionally keep the venv until uninstall) in `disable()`.

**H3. `system_site_packages=True` plus skipped `PLATFORM_CONSTRAINTS`**

- Files: `venv_manager.ensure(system_site_packages=True)`, `DependencyChecker.install(..., check_platform=False)`
- Why: Hybrid sharing is intentional, but then isolated venvs can (a) import host TF/Torch without installing optional deps, and (b) pip-install `pydantic<2` / `numpy>=99` and break the worker's `import app`. The commit claim "cannot break the platform env" is false for (a) in the **host** via setup, and (b) in the **worker**.
- Direction: Create venvs with `system_site_packages=False`; install an explicit **platform subset** (pydantic, packaging, numpy pins matching `PLATFORM_CONSTRAINTS`) into every plugin venv; install optional deps into the venv when `runtime=isolated` (or fail `process` if missing rather than falling through to host copies).

**H4. Allowlist bypasses: index download URL + HTTP redirects**

- Files: `installer._resolve_index`, `_download_with_limit(follow_redirects=True)`, `index._fetch_remote`
- Why: `GRAPHYN_PLUGIN_ALLOWED_SOURCES` is documented as a security control (`PLUGIN_GUIDE.md`, `ARCHITECTURE.md`). It is not applied to the URL that is actually fetched after an index lookup, nor to redirect targets.
- Direction: Allowlist every fetched URL (after redirects: `httpx` with `follow_redirects=False` and manual allowlisted hops, or check `response.url`). Check `entry.download_url` before download.

**H5. ZIP members can be symlinks; TAR cannot**

- File: `PluginInstaller._extract_archive_bytes`
- Why: TAR rejects `issym`/`islnk`. ZIP only checks path containment of `filename`. On Unix, a ZIP symlink + a later member can escape `dest_dir`.
- Direction: Reject ZIP symlink/absolute members; use `zipfile`/`tarfile` `filter="data"` (3.12+). Add tests. (Path-`..` zip-slip via `is_relative_to` looks correct.)

**H6. No subprocess timeout from the executor**

- File: `NodeExecutor._process` → `run_isolated_node(..., timeout=None)`
- Why: Hung isolated `process()` blocks a thread forever; in parallel mode it can stall the wave pool. Retry spawns more workers.
- Direction: Honor node/run timeout; kill the worker process group on expiry.

### Medium

**M1. Optional heavy deps are not installed at isolated load**

- `PluginLoader.load` passes only `manifest.dependencies` to `ensure()`. Trainer/edge/realtime keep torch/tf/onnx in `optional_dependencies`.
- Working as designed for CPU-only installs; contradicts "isolated so conflicting stacks don't share an env" unless the operator hits `dependencies/install?include_optional=true`.
- Direction: For `runtime=isolated`, document the extra step loudly, or add `install_optional_on_load` / install optionals into the venv by default for isolated plugins.

**M2. Lockfile is write-only**

- `write_lockfile` runs `pip freeze` (includes system site-packages noise). `ensure()` never installs from the lockfile.
- Direction: `pip freeze --local` (exclude system), and `pip install -r requirements.lock` on ensure when the hash of declared reqs matches.

**M3. Streaming bypasses isolation**

- `NodeExecutor.execute_stream` always calls `node.process_stream` in-host. `realtime_inference` advertises `realtime_support`.
- Direction: Either refuse isolated+streaming, or RPC chunks (hard). Document as unsupported.

**M4. Host secrets and env inherited by worker**

- `os.environ.copy()`. `GRAPHYN_API_TOKEN`, cloud creds, `PYTHONHOME`, `VIRTUAL_ENV` leak.
- Direction: Pass an explicit env allowlist (PATH, HOME, CUDA, GRAPHYN_HOME, GRAPHYN_PROJECT_DIR, TF device vars).

**M5. Cold worker per `process()`**

- No process reuse. Trainer `process()` pays venv Python startup + re-import + (if moved) re-setup every node execution and every retry.
- Direction: Per-plugin worker daemon with a job queue, or at least reuse for retries within one run.

**M6. Checksums optional; git unpinned; PEP 508 URL deps**

- `dependencies = ["evil @ https://..."]` is valid and pip-installed. Allowlist does not apply to pip.
- Direction: Disallow URL/VCS requirements unless allowlisted; require checksums for remote archives in non-dev.

**M7. CLI/SDK install cannot pass `expected_sha256`**

- `app/cli/main.py` `cmd_plugin_install`, `app/core/sdk.py` `install_plugin`
- Direction: Add the argument; API already has it.

**M8. `gc_plugin_venvs` deletes any extra directory under the venvs root**

- Plus `POST /venvs/gc` is unauthenticated when `GRAPHYN_API_TOKEN` is unset (`AUTH-DEFAULT-1` already in KNOWN_ISSUES).
- Direction: Only delete names that look like created venvs (marker file / `pyvenv.cfg`).

**M9. Docs/steering drift**

- `plugin-ecosystem.md` loader sequence omits isolated venv.
- `plugins_home()` default vs steering `"plugins"`.
- `PLUGIN_GUIDE.md` still teaches host `setup()` model loading.
- Isolation is absent from `docs/KNOWN_ISSUES.md`.

### Low / nit

**L1.** `PluginRuntimeRegistry` is process-global; not persisted. After API restart, `load_enabled_plugins` rebuilds it — OK. Multiple uvicorn workers each have their own map — OK until someone assumes shared state.

**L2.** Hashed module names `md5(plugin_dir)[:8]` — 32-bit collision space. Unlikely; use full hash or install-path-derived names.

**L3.** `isolated_executor` `parents[3]` assumes package layout `app/core/plugins/file.py`. Breaks if the module is frozen or installed as a namespace differently.

**L4.** Worker calls `node.process(inputs) or {}` — drops legitimate empty/falsey returns besides `None`. Host `NodeExecutor` already treats `None` as `{}`. Fine, duplicated.

**L5.** First-party isolated plugins still tell users `venv/bin/pip install tensorflow` in error strings (host venv), not the plugin venv.

**L6.** `graphyn-ui` PluginsView runtime badge is UI-only; no extra isolation risk.

**L7.** `c1` commit does not belong on an isolation branch.

### Working as designed (not bugs)

- Default `runtime=inprocess` sharing the host env.
- `PLATFORM_CONSTRAINTS` hard-fail only for **shared-env** installs.
- Allowlist off by default (backward compat). Documented.
- Local paths not allowlisted. Documented.
- `PluginPackage/` is source; `plugins/` / `plugins_home()` is install target.
- Platform must not import `app.domain` — holds.
- `get_backend().execute()` as the interface entry — holds.
- Lazy TF/Torch inside `TrainerNode.process` (not module-level) — correct pattern **if** host `setup()` stays a no-op.
- Per-plugin venvs not seeing each other's site-packages (when both are isolated and deps live in those venvs).

---

## 7. Open questions / incomplete work

1. **What is the actual product goal?** Dep-conflict for 3 first-party ML nodes, or a third-party plugin sandbox? The code is the former; the allowlist/checksum docs imply the latter.
2. **Should isolated `setup()` live in the worker?** Today it does not. Any isolated plugin that follows `PLUGIN_GUIDE.md`'s setup-loads-weights template will load weights in the host.
3. **Should optional ML deps install into the isolated venv automatically?** Today they do not.
4. **Lockfile policy?** Written, never consumed. No extras, no hashes.
5. **`system_site_packages`:** keep hybrid sharing or go fully sealed + explicit platform subset?
6. **Streaming + isolated:** unsupported; undocumented as a limitation.
7. **Worker lifetime:** one subprocess per `process()` will not survive training/realtime latency goals.
8. **Metadata-only host import:** is a proxy `Node` class in-tree planned? Nothing in code suggests it.
9. **Multi-worker API:** each process has its own `PluginRuntimeRegistry` rebuilt at startup — fine; `_install_jobs` for background install is in-memory per process — pre-existing, worse if isolation install is slow (venv create).
10. **Branch `c1`:** isolate the isolation commit from the spec deletion before merge.
11. **Tests:** no isolation regression suite (section 5.3).
12. **Docs:** `KNOWN_ISSUES.md` should list B1/H1/H2 if this ships without fixes.

---

## Suggested fix order (direction only)

1. Fail closed in `NodeExecutor._process` (H1).
2. Skip host `setup()`/`teardown()` for isolated node_types (B1).
3. Unregister runtime spec on disable (H2).
4. Write tests 5.3.1–5.3.4 **before** any further isolation work — today the feature can rot silently.
5. Decide threat model; either strip sandbox language from docs or replace pickle + host `exec_module` (B2/B3).
6. `system_site_packages=False` + explicit platform subset + install isolated optionals into the venv (H3/M1).
7. Allowlist the URL that is actually fetched (H4); ZIP symlink reject (H5); subprocess timeout (H6).
8. Rebase/split `c1` off this branch.

---

## File / symbol index

| Path | Symbols |
|---|---|
| `app/core/plugins/manifest.py` | `PluginManifest.runtime`, `_validate_runtime` |
| `app/core/plugins/loader.py` | `PluginLoader.load` isolated branch, `_import_entry_points` |
| `app/core/plugins/venv_manager.py` | `PluginVenvManager.ensure`, `write_lockfile`, `gc_unused` |
| `app/core/plugins/runtime_registry.py` | `IsolatedPluginSpec`, `get_runtime_registry` |
| `app/core/plugins/isolated_executor.py` | `run_isolated_node` |
| `app/core/plugins/worker.py` | `_run`, `main` |
| `app/core/plugins/dependencies.py` | `PLATFORM_CONSTRAINTS`, `install`, `_installed_version` |
| `app/core/plugins/installer.py` | `resolve`, `_check_allowed_source`, `_extract_archive_bytes` |
| `app/core/plugins/manager.py` | `install`, `_do_uninstall`, `disable`, `install_dependencies`, `gc_plugin_venvs` |
| `app/core/plugins/index.py` | `lookup`, `_fetch_remote` |
| `app/core/node_executor.py` | `setup`, `_process`, `execute_stream` |
| `app/core/orchestrator.py` | executor setup loop |
| `app/core/nodes/discovery.py` | `_import_file`, `run` → `PluginLoader` |
| `app/core/nodes/__init__.py` | `initialize_registry` |
| `app/core/config.py` | `plugin_venvs_dir`, `plugin_allowed_sources`, `plugins_home` |
| `app/api/routers/plugins.py` | deps endpoints, `venvs/gc` |
| `unit_test/core/plugins/test_dep_isolation.py` | current isolation tests |
