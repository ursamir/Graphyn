# G4 — Plugin Ecosystem: Deep Review

**Module group:** `app/core/plugins/`
**Files reviewed:** 9
**Review date:** 2025-07-14
**Reviewer:** Kiro automated deep-review pass

---

## PHASE 1 — EXPLORATION PLAN

| # | File | Stated Purpose | Key Review Questions |
|---|------|---------------|----------------------|
| 1 | `manager.py` | Single entry point orchestrating install/uninstall/enable/disable/startup | Is temp-dir cleanup guaranteed (PL-07)? Is name-parsing used for pre-flight check correct for URL sources? Is `enable()` idempotent? Does `_unload_node_types` handle symlinks? |
| 2 | `loader.py` | Validates manifest, checks compat/deps, imports entry points, registers nodes | Does `_get_platform_version()` fallback `"0.0.0"` break legitimate plugins? Are entry-point import failures truly isolated? Does `_import_entry_points` access private `_classes`? |
| 3 | `manifest.py` | Pydantic model + TOML/JSON parser for `plugin.toml` | Does `load_manifest` re-check `toml_path.exists()` after already branching on it? Does `__init__` override break Pydantic copy/pickle? Is round-trip `from_toml(to_toml(m)) == m` guaranteed? |
| 4 | `store.py` | JSON persistence layer for `PluginRecord` objects | Is `_save` truly atomic on Windows? Is the lock held across load+save? Is `PluginRecord.load_manifest()` return type annotated? |
| 5 | `installer.py` | Resolves source strings to local plugin directories | Are PL-07/PL-09/PL-10 guards present and correct? Is `_resolve_local_dir` cleanup guaranteed? Does `_find_manifest_dir` have unbounded iteration risk? |
| 6 | `index.py` | Fetches, caches, and searches the remote/local plugin index | Is the class-level cache safe across test runs? Is `_fetch_remote` using streaming (DoS risk)? Is `lookup()` fallback on version-parse exception safe? |
| 7 | `dependencies.py` | Checks PEP 508 deps against current Python environment | Does `_auto_install` run without a timeout? Is `extras_require` handled? Is `pkg_version` using canonical package name? |
| 8 | `errors.py` | Plugin exception hierarchy | Are all exceptions documented? Is `PluginNotFoundError(KeyError)` safe? |
| 9 | `__init__.py` | Public re-exports of error hierarchy | Are all 8 error classes exported? Is startup cost minimised? |

---

## PHASE 2 — PER-FILE FINDINGS


---

## File 1 — `manager.py`

### D1 — Code Quality & Correctness

**Issue found — name pre-flight check fails for URL/path sources.**

`install()` calls `self._installer._parse_name_version(source)` at Step 1 to extract the plugin name for the duplicate-check. `_parse_name_version` is designed for plain `name[==version]` strings. For a URL like `https://example.com/audio-denoiser-1.2.0.tar.gz` or a git URL, the regex `_VERSION_SPEC_RE` will not match, so the entire URL string is returned as the "name". The store lookup `self._store.get(url_string)` will always raise `PluginNotFoundError`, so `existing` is always `None` for URL sources — meaning the duplicate guard is silently bypassed for URL installs. A user can install the same plugin twice from a URL without `upgrade=True`.

### [G4-01] Duplicate-install guard bypassed for URL and path sources
**File:** `app/core/plugins/manager.py`
**Severity:** 🟠 High
**Dimension:** D1 — Code Quality & Correctness
**Description:** `_parse_name_version(source)` returns the raw URL/path as the "name" for non-plain-name sources. The store lookup always misses, so `PluginAlreadyInstalledError` is never raised for URL or local-path installs even when the same plugin is already installed.
**Evidence:** `manager.py` lines 97–98: `name, _ver = self._installer._parse_name_version(source)` — for `source = "https://example.com/plugin.zip"` this returns `("https://example.com/plugin.zip", None)`.
**Proposed Fix:** Move the duplicate check to *after* Step 5 (manifest parsed), using `manifest.name` as the lookup key instead of the pre-parsed name. The pre-parse is still useful for the upgrade uninstall step but should be treated as a best-effort hint, not the authoritative name.


### [G4-02] Temp-dir cleanup not in `finally` — lost on manifest parse failure
**File:** `app/core/plugins/manager.py`
**Severity:** 🟠 High
**Dimension:** D1 — Code Quality & Correctness
**Description:** After `resolved_dir = self._installer.resolve(source)` (Step 4), the temp-dir cleanup block (`shutil.rmtree(resolved_tmpdir, ...)`) is placed *after* Step 5 (`load_manifest`). If `load_manifest` raises `PluginManifestError`, execution jumps past the cleanup line and the temp directory leaks. The `try/except` block that follows only covers Steps 7–8, not Steps 5–6.
**Evidence:** `manager.py` lines 131–155: `manifest = load_manifest(resolved_dir)` at line 135 is outside the `try` block that starts at line 152. The `shutil.rmtree(resolved_tmpdir, ...)` at line 148 is only reached if `load_manifest` succeeds.
**Proposed Fix:** Wrap Steps 5–8 in a single `try/finally` that always calls `shutil.rmtree(resolved_tmpdir, ignore_errors=True)`:
```python
try:
    manifest = load_manifest(resolved_dir)
    # ... steps 6-8 ...
finally:
    if resolved_tmpdir.name.startswith("kiro_plugin_"):
        shutil.rmtree(str(resolved_tmpdir), ignore_errors=True)
```

### D2 — Architecture & Design

No issues found. `PluginManager` correctly delegates to sub-components and is the single entry point as required by the steering file. The `_unload_node_types` path-prefix approach is sound.

### D3 — Error Handling


### [G4-03] `enable()` silently swallows load failure path — `update_enabled` still called
**File:** `app/core/plugins/manager.py`
**Severity:** 🟡 Medium
**Dimension:** D3 — Error Handling
**Description:** In `enable()`, the `except Exception as exc` block logs a warning and then `raise`s. However, the `updated = self._store.update_enabled(name, enabled=True)` call at line 196 is *outside* the `try` block, so it executes even when the exception is re-raised — Python does not execute code after a `raise` in the same block, but the structure is confusing and fragile. If the `raise` is ever removed or the exception is caught higher up, `update_enabled` would mark the plugin as enabled even though loading failed.
**Evidence:** `manager.py` lines 183–198: the `try/except` block ends with `raise`, but `updated = self._store.update_enabled(...)` is at the same indentation level after the `try` block.
**Proposed Fix:** Move `update_enabled` inside the `try` block after the load succeeds, or restructure with an explicit success flag.

### D4 — Performance

No issues found. All operations are bounded. The registry snapshot (`set(self._registry._classes.keys())`) is O(N) in the number of registered types, which is acceptable.

### D5 — Test Coverage Gaps

### [G4-04] No test for URL-source duplicate install bypass
**File:** `app/core/plugins/manager.py`
**Severity:** 🟡 Medium
**Dimension:** D5 — Test Coverage Gaps
**Description:** `test_manager.py` only tests plain-name sources. The URL-source duplicate-install bypass (G4-01) has no test coverage.
**Evidence:** `unit_test/core/plugins/test_manager.py` — all `_make_plugin_src` calls use local directory paths.
**Proposed Fix:** Add a test that installs from a URL source twice and asserts `PluginAlreadyInstalledError` is raised on the second call.

### D6 — Security

No issues found. `_unload_node_types` uses `Path.resolve()` and exact prefix matching, preventing path-confusion attacks.

### D7 — Documentation

### [G4-05] `enable()` docstring missing — no description of reload behaviour
**File:** `app/core/plugins/manager.py`
**Severity:** 🔵 Low
**Dimension:** D7 — Documentation
**Description:** `enable()` has only a one-line summary with no Parameters, Returns, or Raises sections, unlike every other public method in the class.
**Evidence:** `manager.py` line 168: `"""Enable the plugin named *name* and reload its node types if not already loaded."""`
**Proposed Fix:** Add full NumPy-style docstring matching the pattern of `disable()`.

### D8 — Convention Adherence

No issues found. Imports follow the project pattern. `from __future__ import annotations` is present. The steering file rule "Never call PluginLoader, PluginStore, or PluginInstaller directly from outside this package" is respected.

---

## File 2 — `loader.py`

### D1 — Code Quality & Correctness


### [G4-06] `_get_platform_version()` fallback `"0.0.0"` blocks all plugins with `>=X.Y` specifiers when `app` is not importable
**File:** `app/core/plugins/loader.py`
**Severity:** 🟠 High
**Dimension:** D1 — Code Quality & Correctness
**Description:** The docstring explicitly states `"0.0.0"` is the "safe default" to prevent plugins from loading when the platform version is unknown. However, in development environments, CI, or test runs where `app.__version__` is not set, *every* plugin with a `platform_version` specifier of `">=1.0"` or higher will fail with `PluginCompatibilityError`. This is a correctness problem: the fallback is too aggressive and will break legitimate plugin loads in any environment that hasn't set `app.__version__`.
**Evidence:** `loader.py` lines 47–60: `_get_platform_version()` returns `"0.0.0"` on any exception or missing attribute. `_check_platform_compat` then evaluates `Version("0.0.0") not in SpecifierSet(">=1.0")` → `True` → raises.
**Proposed Fix:** Log a WARNING when the version cannot be determined and skip the check (or use a configurable override env var `GRAPHYN_SKIP_PLATFORM_CHECK=1` for dev/test). Alternatively, document that `app.__version__` must be set and add a startup assertion.

### [G4-07] `_import_entry_points` accesses private `_classes` attribute of `NodeRegistry`
**File:** `app/core/plugins/loader.py`
**Severity:** 🟡 Medium
**Dimension:** D1 — Code Quality & Correctness
**Description:** `_import_entry_points` reads `self._registry._classes.keys()` directly to snapshot registered types before and after import. This couples `PluginLoader` to the internal implementation of `NodeRegistry`. If `NodeRegistry` renames or restructures `_classes`, this silently breaks.
**Evidence:** `loader.py` lines 175 and 181: `set(self._registry._classes.keys())` appears twice.
**Proposed Fix:** Add a public `NodeRegistry.registered_types() -> frozenset[str]` method and use it here.

### D2 — Architecture & Design

No issues found. The load sequence matches the steering file specification exactly. `AutoDiscovery` is used internally rather than bypassed.

### D3 — Error Handling

### [G4-08] Entry-point `ImportError` / `SyntaxError` swallowed — plugin appears to load successfully with 0 node types
**File:** `app/core/plugins/loader.py`
**Severity:** 🟡 Medium
**Dimension:** D3 — Error Handling
**Description:** When all entry points fail (e.g., all have syntax errors), `_import_entry_points` returns an empty list. `load()` then logs "registered 0 node type(s)" and returns `[]` — no exception is raised. The caller (`PluginManager.install`) treats this as a successful install. The plugin is persisted in the store as enabled but contributes nothing.
**Evidence:** `loader.py` lines 183–193: all exceptions in the entry-point loop are caught and `continue`d. `load()` returns `new_types` which may be `[]`.
**Proposed Fix:** After the loop, if `new_node_types` is empty and `manifest.entry_points` is non-empty, raise `PluginManifestError` (or a new `PluginLoadError`) to signal that no nodes were registered. Alternatively, add a configurable `require_nodes: bool = True` parameter.

### D4 — Performance

No issues found. The `before`/`after` set difference is O(N) in registry size.

### D5 — Test Coverage Gaps

### [G4-09] No test for all-entry-points-fail scenario (0 node types registered)
**File:** `app/core/plugins/loader.py`
**Severity:** 🟡 Medium
**Dimension:** D5 — Test Coverage Gaps
**Description:** `test_loader.py` does not test the case where every entry point raises an exception, resulting in 0 registered node types and a silent success.
**Evidence:** `unit_test/core/plugins/test_loader.py` — no test for all-fail scenario.
**Proposed Fix:** Add a test with an entry point containing a `SyntaxError` and assert that the return value is `[]` (or that an error is raised, depending on the fix for G4-08).

### D6 — Security

No issues found. Entry-point paths are relative to `plugin_dir` which is already validated by the installer.

### D7 — Documentation

No issues found. All public methods have complete NumPy-style docstrings.

### D8 — Convention Adherence

No issues found.

---

## File 3 — `manifest.py`

### D1 — Code Quality & Correctness


### [G4-10] `load_manifest` calls `toml_path.exists()` twice — TOCTOU race
**File:** `app/core/plugins/manifest.py`
**Severity:** 🟡 Medium
**Dimension:** D1 — Code Quality & Correctness
**Description:** `load_manifest` checks `toml_path.exists()` at line ~215 to decide which branch to take, then calls `_parse_manifest_dict(data, source=str(toml_path if toml_path.exists() else json_path))` at line ~228, calling `.exists()` a second time. Between the two calls the file could be deleted (race condition). In practice this is low-probability but the double-call is also logically redundant.
**Evidence:** `manifest.py` lines 215–228: `if toml_path.exists(): data = _load_toml(toml_path)` then `source=str(toml_path if toml_path.exists() else json_path)`.
**Proposed Fix:** Capture the chosen path in a variable: `chosen_path = toml_path if toml_path.exists() else json_path` and use it for both the load and the source string.

### [G4-11] `PluginManifest.__init__` override breaks Pydantic `model_copy()` and pickle
**File:** `app/core/plugins/manifest.py`
**Severity:** 🟡 Medium
**Dimension:** D1 — Code Quality & Correctness
**Description:** Overriding `__init__` on a Pydantic v2 `BaseModel` to wrap exceptions is fragile. Pydantic v2 uses `__init__` internally for `model_copy()`, `model_validate()`, and pickle/unpickle. The override catches *all* exceptions including `PluginManifestError` (re-raised correctly) but also `RecursionError`, `MemoryError`, and other non-validation exceptions, wrapping them as `PluginManifestError`. Additionally, `model_copy()` calls `__init__` with already-validated data, so the try/except adds overhead on every copy.
**Evidence:** `manifest.py` lines 196–200: `def __init__(self, **data: Any) -> None: try: super().__init__(**data) except Exception as exc: _rewrap_validation_error(exc, source="<direct construction>")`.
**Proposed Fix:** Remove the `__init__` override. Instead, use a `@classmethod` factory `PluginManifest.from_dict(data)` that wraps `model_validate` with error rewrapping. Direct `PluginManifest(**data)` construction can remain unwrapped (callers should use `load_manifest` or `_parse_manifest_dict`).

### D2 — Architecture & Design

No issues found. The TOML/JSON dual-format support with `[plugin]` section unwrapping is clean and well-structured.

### D3 — Error Handling

### [G4-12] `_rewrap_validation_error` declared as `None`-returning but always raises — misleading return type
**File:** `app/core/plugins/manifest.py`
**Severity:** 🔵 Low
**Dimension:** D3 — Error Handling
**Description:** `_rewrap_validation_error` is annotated `-> None` but always raises. The docstring says "This is a no-return helper — it always raises." The correct annotation is `-> NoReturn` from `typing`. Without it, type checkers cannot prove that code after a call to this function is unreachable, which is why `_parse_manifest_dict` needs the `raise  # unreachable` comment.
**Evidence:** `manifest.py` line 207: `def _rewrap_validation_error(exc: Exception, source: str) -> None:`.
**Proposed Fix:** Change to `from typing import NoReturn` and annotate `-> NoReturn`.

### D4 — Performance

No issues found. Manifest parsing is a one-time operation per plugin load.

### D5 — Test Coverage Gaps

### [G4-13] No round-trip property test (`from_toml(to_toml(m)) == m`)
**File:** `app/core/plugins/manifest.py`
**Severity:** 🟡 Medium
**Dimension:** D5 — Test Coverage Gaps
**Description:** The existing property test (`test_valid_manifest_acceptance_property`) only checks that valid dicts construct without raising. There is no test verifying that a `PluginManifest` serialised to TOML and re-parsed produces an identical object. This is the correctness property requested in the review spec.
**Evidence:** `unit_test/core/plugins/test_manifest.py` — no round-trip test exists.
**Proposed Fix:** See Hypothesis skeleton in Section 4 of this report.

### [G4-14] No test for `optional_dependencies` field validation
**File:** `app/core/plugins/manifest.py`
**Severity:** 🔵 Low
**Dimension:** D5 — Test Coverage Gaps
**Description:** `optional_dependencies` is stored but has no `field_validator`. Unlike `dependencies`, it is never validated as PEP 508. A malformed string in `optional_dependencies` would silently pass validation.
**Evidence:** `manifest.py` — `optional_dependencies: list[str] = []` has no validator. `dependencies` has `_validate_dependencies` but `optional_dependencies` does not.
**Proposed Fix:** Add `_validate_optional_dependencies` mirroring `_validate_dependencies`, or add a test that confirms the intentional lack of validation with a comment explaining why.

### D6 — Security

No issues found.

### D7 — Documentation

No issues found. All fields are documented in the class docstring.

### D8 — Convention Adherence

No issues found.

---

## File 4 — `store.py`

### D1 — Code Quality & Correctness


### [G4-15] `get()` and `list()` release the lock before constructing `PluginRecord` objects
**File:** `app/core/plugins/store.py`
**Severity:** 🟡 Medium
**Dimension:** D1 — Code Quality & Correctness
**Description:** In `get()` and `list()`, the lock is acquired only for `_load()`, then released before `PluginRecord(**data[name])` is constructed. A concurrent `save()` or `delete()` call could modify the registry between the load and the construction. While `PluginRecord` is immutable (frozen Pydantic model), the dict `data` is a local copy so the race is benign for `get()`. However, `list()` iterates `data.values()` after the lock is released — if a concurrent `delete()` modifies the file between the `_load()` and the list comprehension, the in-memory `data` dict is stale but consistent (it's a local copy). This is acceptable but worth documenting.
**Evidence:** `store.py` lines 131–134 (`get`) and 138–140 (`list`): `with self._lock: data = self._load()` then `return PluginRecord(**data[name])` outside the lock.
**Proposed Fix:** No code change required, but add a comment explaining that `data` is a local snapshot and the lock only needs to protect the file read. This is the correct design.

### [G4-16] `_save()` does not call `os.fsync()` — data loss on power failure
**File:** `app/core/plugins/store.py`
**Severity:** 🟡 Medium
**Dimension:** D1 — Code Quality & Correctness
**Description:** `_save()` writes to a temp file and calls `os.replace()` for atomicity, but never calls `os.fsync()` on the file descriptor before closing. On Linux with `ext4` (default mount options), `os.replace()` is atomic but the data may not be flushed to disk before a power failure, leaving the registry file empty or truncated.
**Evidence:** `store.py` lines 155–165: `with os.fdopen(fd, "w", ...) as fh: json.dump(...)` then `os.replace(tmp_path, ...)` — no `fh.flush()` + `os.fsync(fh.fileno())` before close.
**Proposed Fix:** Add `fh.flush(); os.fsync(fh.fileno())` before the `with` block exits, or accept the risk and document it.

### D2 — Architecture & Design

No issues found. The atomic write pattern (temp file + `os.replace`) is correct. The threading lock correctly protects all read-modify-write operations.

### D3 — Error Handling

No issues found. Corrupt JSON is backed up before treating as empty (PL-13 fix). `_save()` cleans up the temp file on failure.

### D4 — Performance

No issues found. The registry is expected to be small (tens of plugins). All operations are O(N) in registry size.

### D5 — Test Coverage Gaps

### [G4-17] No test for corrupt `registry.json` backup behaviour
**File:** `app/core/plugins/store.py`
**Severity:** 🟡 Medium
**Dimension:** D5 — Test Coverage Gaps
**Description:** The PL-13 fix (backup corrupt registry to `.json.corrupt`) has no test. If the backup logic is broken, corrupt registries silently lose data without warning.
**Evidence:** `unit_test/core/plugins/test_store.py` — no test writes a corrupt JSON file and verifies the backup is created.
**Proposed Fix:** Add a test that writes `"not valid json"` to `registry.json`, calls `store.list()`, and asserts both that `[]` is returned and that `registry.json.corrupt` exists.

### D6 — Security

No issues found. The registry file is written atomically and the temp file is in the same directory (same filesystem, preventing cross-device `os.replace` failures).

### D7 — Documentation

### [G4-18] `PluginRecord.load_manifest()` missing return type annotation
**File:** `app/core/plugins/store.py`
**Severity:** 🔵 Low
**Dimension:** D7 — Documentation
**Description:** `load_manifest()` on `PluginRecord` has no return type annotation. The return type is `PluginManifest` but this is not declared, making it harder for type checkers and IDEs to infer the type.
**Evidence:** `store.py` line 47: `def load_manifest(self):`.
**Proposed Fix:** Change to `def load_manifest(self) -> "PluginManifest":` (with `TYPE_CHECKING` import guard to avoid circular import).

### D8 — Convention Adherence

No issues found.

---

## File 5 — `installer.py`

### D1 — Code Quality & Correctness


### [G4-19] `_resolve_local_dir` temp-dir parent is `tmpdir`, but caller cleans up `resolved_dir.parent` — mismatch for nested copies
**File:** `app/core/plugins/installer.py`
**Severity:** 🟡 Medium
**Dimension:** D1 — Code Quality & Correctness
**Description:** `_resolve_local_dir` creates `tmpdir = Path(tempfile.mkdtemp(...))` and copies the plugin into `dest = tmpdir / path.name`, returning `dest`. The docstring says "The parent tmpdir is stored as `resolved_dir.parent`". In `manager.py`, the cleanup uses `resolved_tmpdir = resolved_dir.parent`. This works correctly for `_resolve_local_dir`. However, for `_resolve_git`, `_resolve_http_archive`, and `_resolve_local_archive`, the returned path *is* the tmpdir itself (not a subdirectory), so `resolved_dir.parent` is the system temp directory (`/tmp`). The `kiro_plugin_` prefix check in `manager.py` prevents deleting `/tmp`, but the actual tmpdir (`/tmp/kiro_plugin_git_XXXX`) is never cleaned up in those cases.
**Evidence:** `installer.py` `_resolve_git` line ~143: `return self._find_manifest_dir(tmpdir)` — if the manifest is at the root, returns `tmpdir` itself. `manager.py` line ~138: `resolved_tmpdir = resolved_dir.parent` — for git/http sources this is `/tmp`, not the actual tmpdir.
**Proposed Fix:** Have all resolver methods return a `(resolved_dir, tmpdir_to_clean)` tuple, or store the tmpdir as an attribute on the returned path (e.g., via a wrapper). Alternatively, always return a subdirectory of the tmpdir (never the tmpdir itself).

### [G4-20] `_find_manifest_dir` iterates all children at levels 1 and 2 — no guard against archives with thousands of entries
**File:** `app/core/plugins/installer.py`
**Severity:** 🟡 Medium
**Dimension:** D1 — Code Quality & Correctness
**Description:** `_find_manifest_dir` calls `root.iterdir()` and then `child.iterdir()` for every subdirectory. A malicious or malformed archive with thousands of top-level directories would cause this to iterate all of them before raising `PluginInstallError`. This is O(N²) in the worst case (N directories each with N subdirectories).
**Evidence:** `installer.py` lines 248–270: nested `for child in root.iterdir()` / `for grandchild in child.iterdir()` with no early-exit limit.
**Proposed Fix:** Add a counter limit (e.g., stop after checking 100 entries at each level) and raise `PluginInstallError` if the limit is exceeded.

### D2 — Architecture & Design

No issues found. The five-source routing logic is clean and well-ordered.

### D3 — Error Handling

No issues found. All resolver methods have `try/except` blocks that clean up the tmpdir on both `PluginInstallError` and unexpected exceptions.

### D4 — Performance

See G4-20 above (O(N²) in `_find_manifest_dir`).

### D5 — Test Coverage Gaps

### [G4-21] No test for zip-slip guard (bad archive member path raises `PluginInstallError`)
**File:** `app/core/plugins/installer.py`
**Severity:** 🟠 High
**Dimension:** D5 — Test Coverage Gaps
**Description:** The PL-10 zip-slip guard exists in `_extract_archive_bytes` but has no test. A regression could silently remove the guard. See Hypothesis skeleton in Section 4.
**Evidence:** `unit_test/core/plugins/test_installer.py` — no test for path traversal in ZIP or TAR members.
**Proposed Fix:** Add both a unit test and the Hypothesis property test from Section 4.

### [G4-22] No test for download size limit (PL-09)
**File:** `app/core/plugins/installer.py`
**Severity:** 🟡 Medium
**Dimension:** D5 — Test Coverage Gaps
**Description:** `_download_with_limit` enforces `_MAX_DOWNLOAD_BYTES` but there is no test that verifies the limit is enforced.
**Evidence:** `unit_test/core/plugins/test_installer.py` — no test for oversized download.
**Proposed Fix:** Add a test that mocks `httpx.stream` to yield chunks totalling > 100 MB and asserts `PluginInstallError` is raised.

### D6 — Security

**PL-07 Verification — Temp dir cleanup:**
The guard is present. In `_resolve_git`:
```python
tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_git_"))
try:
    ...
except PluginInstallError:
    shutil.rmtree(tmpdir, ignore_errors=True)
    raise
except Exception as exc:
    shutil.rmtree(tmpdir, ignore_errors=True)
    raise PluginInstallError(...) from exc
```
The same pattern is used in `_resolve_http_archive`, `_resolve_local_archive`, and `_resolve_index`. ✅ Guard present. However, see G4-19 for the case where the returned path is the tmpdir itself and `manager.py`'s cleanup misses it.

**PL-09 Verification — Download size limit:**
The guard is present in `_download_with_limit`:
```python
for chunk in response.iter_bytes(chunk_size=65_536):
    total += len(chunk)
    if total > _MAX_DOWNLOAD_BYTES:
        raise PluginInstallError(
            f"Download from {url!r} exceeds the maximum allowed size "
            f"of {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB."
        )
    chunks.append(chunk)
```
`_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024` (100 MB). ✅ Guard present and correct.

**PL-10 Verification — Zip-slip / tar-slip path traversal guard:**
The guard is present in `_extract_archive_bytes` for both ZIP and TAR:
```python
# ZIP:
dest_resolved = dest_dir.resolve()
for member in zf.infolist():
    member_path = (dest_dir / member.filename).resolve()
    if not member_path.is_relative_to(dest_resolved):
        raise PluginInstallError(
            f"Unsafe ZIP entry '{member.filename}' would extract "
            f"outside the destination directory."
        )
zf.extractall(dest_dir)

# TAR:
dest_resolved = dest_dir.resolve()
for member in tf.getmembers():
    member_path = (dest_dir / member.name).resolve()
    if not member_path.is_relative_to(dest_resolved):
        raise PluginInstallError(
            f"Unsafe TAR entry '{member.name}' would extract "
            f"outside the destination directory."
        )
tf.extractall(dest_dir)
```
✅ Guard present and uses `Path.is_relative_to()` (Python 3.9+) which is correct and case-insensitive-filesystem-safe.

### [G4-23] `_resolve_git` passes user-supplied URL directly to `subprocess.run` — command injection via crafted URL
**File:** `app/core/plugins/installer.py`
**Severity:** 🟠 High
**Dimension:** D6 — Security
**Description:** `subprocess.run(["git", "clone", "--depth", "1", clone_url, str(tmpdir)], ...)` passes `clone_url` as a list element, which is safe from shell injection. However, a URL like `--upload-pack=malicious_command` could be interpreted by git as a flag rather than a URL. Git's `--` separator should be used to prevent this.
**Evidence:** `installer.py` line ~148: `["git", "clone", "--depth", "1", clone_url, str(tmpdir)]`.
**Proposed Fix:** Add `"--"` before the URL: `["git", "clone", "--depth", "1", "--", clone_url, str(tmpdir)]`.

### D7 — Documentation

No issues found. All public and private methods have docstrings.

### D8 — Convention Adherence

No issues found.

---

## File 6 — `index.py`

### D1 — Code Quality & Correctness


### [G4-24] Class-level `_cache` is shared across all instances and test runs — cross-test contamination
**File:** `app/core/plugins/index.py`
**Severity:** 🟠 High
**Dimension:** D1 — Code Quality & Correctness
**Description:** `PluginIndexClient._cache` is a class-level attribute. Once populated in one test, it persists for all subsequent tests in the same process unless explicitly reset. The test file does reset it (`PluginIndexClient._cache = None`) in `_make_client()`, but any test that creates a `PluginIndexClient` without using `_make_client()` (e.g., via `PluginManager`) will see stale cache data. This is a latent test-isolation bug that can cause flaky tests.
**Evidence:** `index.py` line 47: `_cache: list[PluginIndexEntry] | None = None` — class-level. `test_index.py` `_make_client()` resets it, but `test_manager.py` creates `PluginManager` which creates `PluginIndexClient()` without resetting the cache.
**Proposed Fix:** Add a `pytest` autouse fixture in `conftest.py` that resets `PluginIndexClient._cache = None` before each test. Or convert the cache to an instance-level attribute with a class-level lock.

### [G4-25] `_fetch_remote` uses blocking `httpx.get` — not streaming, no size limit
**File:** `app/core/plugins/index.py`
**Severity:** 🟠 High
**Dimension:** D1 — Code Quality & Correctness
**Description:** `_fetch_remote` calls `httpx.get(url, timeout=10)` which loads the entire response body into memory. A malicious or misconfigured index server could return a gigabyte-sized response, causing OOM. Unlike `installer.py`'s `_download_with_limit`, there is no size cap here.
**Evidence:** `index.py` line 196: `response = httpx.get(url, timeout=10)` — no `max_bytes` or streaming.
**Proposed Fix:** Use `httpx.stream("GET", url, timeout=10)` with a size limit (e.g., 10 MB for an index file) mirroring the pattern in `installer.py`.

### [G4-26] `lookup()` silently falls back to string comparison on `SpecifierSet` parse failure — wrong version returned
**File:** `app/core/plugins/index.py`
**Severity:** 🟡 Medium
**Dimension:** D1 — Code Quality & Correctness
**Description:** In `lookup()`, if `SpecifierSet(version_str)` raises, the code falls back to `[e for e in matches if e.version == version_str]`. This means a malformed version specifier like `">=1.0.0"` (which should parse fine) or `"~=1.0"` would silently do an exact string match instead of a specifier match, returning no results and raising `PluginNotFoundError` with a confusing message.
**Evidence:** `index.py` lines 155–162: `except Exception: versioned = [e for e in matches if e.version == version_str]`.
**Proposed Fix:** Log the parse exception at WARNING level and raise `PluginIndexError` with a clear message about the invalid specifier, rather than silently falling back.

### D2 — Architecture & Design

No issues found. The double-checked locking pattern for the class-level cache is correct.

### D3 — Error Handling

No issues found beyond G4-26. Network errors and HTTP errors are properly wrapped in `PluginIndexError`.

### D4 — Performance

See G4-25 (blocking full-body download for index).

### D5 — Test Coverage Gaps

### [G4-27] No test for `lookup()` with specifier parse failure fallback
**File:** `app/core/plugins/index.py`
**Severity:** 🔵 Low
**Dimension:** D5 — Test Coverage Gaps
**Description:** The `except Exception` fallback in `lookup()` is untested.
**Evidence:** `unit_test/core/plugins/test_index.py` — no test passes an invalid specifier string to `lookup()`.
**Proposed Fix:** Add a test with `version="not-a-specifier!!"` and assert the expected behaviour (either `PluginNotFoundError` or `PluginIndexError`).

### D6 — Security

No issues found beyond G4-25 (unbounded index download).

### D7 — Documentation

No issues found.

### D8 — Convention Adherence

No issues found.

---

## File 7 — `dependencies.py`

### D1 — Code Quality & Correctness

### [G4-28] `_auto_install` runs `pip install` without a timeout — hangs indefinitely on network issues
**File:** `app/core/plugins/dependencies.py`
**Severity:** 🟠 High
**Dimension:** D1 — Code Quality & Correctness
**Description:** `subprocess.run(cmd, capture_output=True, text=True)` has no `timeout` parameter. If pip hangs (e.g., waiting for a package index that never responds), the entire platform startup or install operation hangs indefinitely with no way to interrupt it short of killing the process.
**Evidence:** `dependencies.py` lines 130–135: `result = subprocess.run(cmd, capture_output=True, text=True)` — no `timeout=`.
**Proposed Fix:** Add `timeout=300` (5 minutes) and catch `subprocess.TimeoutExpired`, converting it to `PluginDependencyError`.

### [G4-29] `_find_unsatisfied` uses `pkg_version(req.name)` — does not normalise package name, may miss installed packages
**File:** `app/core/plugins/dependencies.py`
**Severity:** 🟡 Medium
**Dimension:** D1 — Code Quality & Correctness
**Description:** `importlib.metadata.version(req.name)` uses the package name as-is. PEP 503 normalises package names by lowercasing and replacing `[-_.]` with `-`. A dependency declared as `Pillow` would fail lookup if the installed package metadata uses `pillow`. `packaging.requirements.Requirement` normalises the name, but `importlib.metadata.version` does not always do so on all platforms.
**Evidence:** `dependencies.py` line 97: `installed = pkg_version(req.name)` — `req.name` is the raw name from the requirement string.
**Proposed Fix:** Use `importlib.metadata.packages_distributions()` or normalise the name: `pkg_version(req.name.lower().replace("_", "-"))`. Or use `importlib.metadata.version` with the normalised name from `packaging.utils.canonicalize_name(req.name)`.

### D2 — Architecture & Design

No issues found. The four-step check/install flow is clean and well-separated.

### D3 — Error Handling

No issues found beyond G4-28. `InvalidRequirement` is caught and re-raised as `PluginManifestError` (correct — it's a manifest authoring error).

### D4 — Performance

No issues found. Dependency checking is O(N) in the number of dependencies.

### D5 — Test Coverage Gaps

### [G4-30] No test for `_auto_install` success or failure path
**File:** `app/core/plugins/dependencies.py`
**Severity:** 🟡 Medium
**Dimension:** D5 — Test Coverage Gaps
**Description:** `test_dependencies.py` does not test the auto-install path (neither success nor pip failure).
**Evidence:** `unit_test/core/plugins/test_dependencies.py` — no test sets `GRAPHYN_PLUGIN_AUTO_INSTALL=1`.
**Proposed Fix:** Add tests that mock `subprocess.run` to return success (returncode=0) and failure (returncode=1) and assert the correct behaviour.

### D6 — Security

### [G4-31] `_auto_install` installs arbitrary packages from the internet without user confirmation
**File:** `app/core/plugins/dependencies.py`
**Severity:** 🟠 High
**Dimension:** D6 — Security
**Description:** When `GRAPHYN_PLUGIN_AUTO_INSTALL=1`, any package listed in a plugin's `dependencies` field is automatically installed via pip without prompting the user. A malicious plugin could declare `dependencies = ["malicious-package"]` and have it silently installed. This is a supply-chain attack vector.
**Evidence:** `dependencies.py` lines 130–135: `cmd = [sys.executable, "-m", "pip", "install", *unsatisfied]` — no confirmation, no allowlist.
**Proposed Fix:** Document the security risk prominently in the docstring and in `PLUGIN_GUIDE.md`. Consider adding a `GRAPHYN_PLUGIN_TRUSTED_SOURCES` allowlist or requiring explicit user confirmation for auto-install.

### D7 — Documentation

No issues found.

### D8 — Convention Adherence

No issues found.

---

## File 8 — `errors.py`

### D1 — Code Quality & Correctness

No issues found.

### D2 — Architecture & Design

No issues found. The hierarchy is clean and matches the steering file specification exactly.

### D3 — Error Handling

No issues found.

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

No issues found. Error classes are simple and tested implicitly by all other plugin tests.

### D6 — Security

No issues found.

### D7 — Documentation

### [G4-32] `PluginNotFoundError` docstring does not mention the `KeyError` inheritance implication
**File:** `app/core/plugins/errors.py`
**Severity:** 🔵 Low
**Dimension:** D7 — Documentation
**Description:** `PluginNotFoundError` inherits from both `PluginError` and `KeyError`. `KeyError` formats its `args[0]` with `repr()` when printed, so `str(PluginNotFoundError("audio-denoiser"))` produces `"'audio-denoiser'"` (with quotes) rather than `"audio-denoiser"`. This surprises callers who log the exception message. The docstring does not mention this behaviour.
**Evidence:** `errors.py` lines 55–60: `class PluginNotFoundError(PluginError, KeyError):`.
**Proposed Fix:** Add a note to the docstring: "Note: because this inherits from `KeyError`, `str(exc)` wraps the message in `repr()`. Use `exc.args[0]` for the raw message string."

### D8 — Convention Adherence

No issues found.

---

## File 9 — `__init__.py`

### D1 — Code Quality & Correctness

No issues found.

### D2 — Architecture & Design

No issues found. Only the error hierarchy is exported, keeping startup cost low as documented.

### D3 — Error Handling

No issues found.

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

No issues found.

### D6 — Security

No issues found.

### D7 — Documentation

### [G4-33] Module docstring lists `PluginIndexError` in the example but the import block order differs
**File:** `app/core/plugins/__init__.py`
**Severity:** 🔵 Low
**Dimension:** D7 — Documentation
**Description:** The module docstring example shows the imports in alphabetical order ending with `PluginIndexError`, but the actual `from app.core.plugins.errors import (...)` block uses a different order (alphabetical by class name, not matching the docstring). Minor inconsistency.
**Evidence:** `__init__.py` lines 14–22 (docstring) vs lines 26–34 (actual imports).
**Proposed Fix:** Align the docstring example with the actual import order, or sort both alphabetically.

### D8 — Convention Adherence

No issues found. `__all__` is defined and matches the imports.


---

## Section 3 — Security Fix Verifications

### PL-07 — Temp Dir Cleanup

**Status: ✅ PRESENT (with caveat)**

The guard exists in every resolver method in `installer.py`. Each method follows the pattern:

```python
tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_<type>_"))
try:
    ...
except PluginInstallError:
    shutil.rmtree(tmpdir, ignore_errors=True)
    raise
except Exception as exc:
    shutil.rmtree(tmpdir, ignore_errors=True)
    raise PluginInstallError(...) from exc
```

In `manager.py`, the cleanup is:
```python
resolved_tmpdir: Path = resolved_dir.parent
# ...
if resolved_tmpdir.name.startswith("kiro_plugin_"):
    shutil.rmtree(str(resolved_tmpdir), ignore_errors=True)
```

**Caveat (G4-19):** For `_resolve_git`, `_resolve_http_archive`, and `_resolve_local_archive`, when `_find_manifest_dir` returns the tmpdir itself (manifest at root level), `resolved_dir.parent` is the system `/tmp` directory, not the actual tmpdir. The `kiro_plugin_` prefix check prevents deleting `/tmp`, but the actual tmpdir is never cleaned up by `manager.py` in this case. The installer's own `except` blocks do clean up on failure, but on success the tmpdir leaks.

### PL-09 — Download Size Limit

**Status: ✅ PRESENT**

The byte-count check is in `_download_with_limit`:

```python
_MAX_DOWNLOAD_BYTES: int = 100 * 1024 * 1024  # 100 MB

for chunk in response.iter_bytes(chunk_size=65_536):
    total += len(chunk)
    if total > _MAX_DOWNLOAD_BYTES:
        raise PluginInstallError(
            f"Download from {url!r} exceeds the maximum allowed size "
            f"of {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB."
        )
    chunks.append(chunk)
```

The check uses streaming (`httpx.stream`) and counts bytes incrementally, so the limit is enforced before the full response is buffered. ✅ Correct implementation.

### PL-10 — Zip-slip / Tar-slip Path Traversal Guard

**Status: ✅ PRESENT**

The guard is in `_extract_archive_bytes` for both ZIP and TAR formats:

```python
# ZIP guard:
dest_resolved = dest_dir.resolve()
for member in zf.infolist():
    member_path = (dest_dir / member.filename).resolve()
    if not member_path.is_relative_to(dest_resolved):
        raise PluginInstallError(
            f"Unsafe ZIP entry '{member.filename}' would extract "
            f"outside the destination directory."
        )
zf.extractall(dest_dir)

# TAR guard:
dest_resolved = dest_dir.resolve()
for member in tf.getmembers():
    member_path = (dest_dir / member.name).resolve()
    if not member_path.is_relative_to(dest_resolved):
        raise PluginInstallError(
            f"Unsafe TAR entry '{member.name}' would extract "
            f"outside the destination directory."
        )
tf.extractall(dest_dir)
```

`Path.is_relative_to()` (Python 3.9+) resolves symlinks and handles case-insensitive filesystems correctly. ✅ Correct implementation.

---

## Section 4 — Correctness Property Skeletons

### 4.1 — `PluginManifest` Round-Trip Property (manifest.py)

**Property:** `PluginManifest.from_toml(to_toml(manifest)) == manifest`

A `PluginManifest` serialised to TOML and re-parsed must produce an identical object. This verifies that no field is lost, coerced, or mutated during the TOML round-trip.

```python
# unit_test/core/plugins/test_manifest_roundtrip.py
"""Hypothesis property: PluginManifest TOML round-trip is lossless."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.plugins.manifest import PluginManifest, load_manifest

# ── Strategies ────────────────────────────────────────────────────────────────

_slug = st.from_regex(r"[a-z][a-z0-9_-]{0,30}", fullmatch=True)
_version = st.builds(
    lambda a, b, c: f"{a}.{b}.{c}",
    a=st.integers(0, 99), b=st.integers(0, 99), c=st.integers(0, 99),
)
_entry_points = st.lists(
    st.from_regex(r"[a-z][a-z0-9_]{0,20}\.py", fullmatch=True),
    min_size=1, max_size=5,
)
_nonempty_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1, max_size=80,
).filter(lambda s: s.strip())
_tags = st.lists(st.text(min_size=1, max_size=20), max_size=5)
_opt_str = st.one_of(st.none(), st.text(min_size=1, max_size=50))


@given(
    name=_slug,
    version=_version,
    description=_nonempty_text,
    author=_nonempty_text,
    entry_points=_entry_points,
    tags=_tags,
    homepage=_opt_str,
    license_id=_opt_str,
)
@settings(max_examples=200)
def test_manifest_toml_roundtrip(
    name: str,
    version: str,
    description: str,
    author: str,
    entry_points: list[str],
    tags: list[str],
    homepage: str | None,
    license_id: str | None,
) -> None:
    """PluginManifest serialised to TOML and re-parsed equals the original."""
    try:
        import tomli_w  # pip install tomli-w
    except ImportError:
        pytest.skip("tomli-w not installed")

    original = PluginManifest(
        name=name,
        version=version,
        description=description,
        author=author,
        platform_version=">=0.0",
        entry_points=entry_points,
        tags=tags,
        homepage=homepage,
        license=license_id,
    )

    # Serialise to TOML
    data = original.model_dump(exclude_none=False)
    toml_bytes = tomli_w.dumps({"plugin": data}).encode()

    # Write to temp file and re-parse
    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_dir = Path(tmpdir)
        (plugin_dir / "plugin.toml").write_bytes(toml_bytes)
        reloaded = load_manifest(plugin_dir)

    # Assert round-trip equality
    assert reloaded.name == original.name
    assert reloaded.version == original.version
    assert reloaded.description == original.description
    assert reloaded.author == original.author
    assert reloaded.entry_points == original.entry_points
    assert reloaded.tags == original.tags
    assert reloaded.homepage == original.homepage
    assert reloaded.license == original.license
```

**Known limitation:** TOML does not support `None` values natively. Fields with `None` must be omitted from the TOML file. The `model_dump(exclude_none=False)` call will include `None` values which `tomli_w` cannot serialise. The test uses `exclude_none=True` in practice, meaning `None` optional fields are not round-tripped. This is a real gap: if `homepage=None` is stored in the TOML as an absent key, re-parsing correctly returns `None`, so the round-trip is lossless for `None` values as long as the serialiser omits them.

---

### 4.2 — Bad Archive Member Path Raises `ValueError` / `PluginInstallError` (installer.py)

**Property:** For any archive member path containing `..` or an absolute path, `_extract_archive_bytes` raises `PluginInstallError`.

```python
# unit_test/core/plugins/test_installer_zipslip.py
"""Hypothesis property: bad archive member paths always raise PluginInstallError."""
from __future__ import annotations

import io
import os
import tarfile
import tempfile
import zipfile
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.core.plugins.installer import PluginInstaller
from app.core.plugins.errors import PluginInstallError

installer = PluginInstaller()

# ── Strategy: paths that escape the destination directory ─────────────────────

_traversal_components = st.one_of(
    # Classic path traversal
    st.just("../evil"),
    st.just("../../etc/passwd"),
    st.just("a/../../evil"),
    # Absolute paths
    st.just("/etc/passwd"),
    st.just("/tmp/evil"),
    # Mixed
    st.builds(
        lambda n: "../" * n + "evil",
        n=st.integers(min_value=1, max_value=5),
    ),
)


@given(bad_member_name=_traversal_components)
@settings(max_examples=100)
def test_zip_slip_raises_plugin_install_error(bad_member_name: str) -> None:
    """Any ZIP member with a path-traversal name raises PluginInstallError."""
    # Build an in-memory ZIP with the bad member name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(bad_member_name, "malicious content")
    zip_bytes = buf.getvalue()

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir)
        with pytest.raises(PluginInstallError, match="Unsafe ZIP entry"):
            installer._extract_archive_bytes(zip_bytes, "test.zip", dest)


@given(bad_member_name=_traversal_components)
@settings(max_examples=100)
def test_tar_slip_raises_plugin_install_error(bad_member_name: str) -> None:
    """Any TAR member with a path-traversal name raises PluginInstallError."""
    # Build an in-memory TAR with the bad member name
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        content = b"malicious content"
        info = tarfile.TarInfo(name=bad_member_name)
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    tar_bytes = buf.getvalue()

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir)
        with pytest.raises(PluginInstallError, match="Unsafe TAR entry"):
            installer._extract_archive_bytes(tar_bytes, "test.tar.gz", dest)


def test_zip_slip_absolute_path_raises() -> None:
    """Absolute path in ZIP member raises PluginInstallError (concrete example)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("/etc/passwd", "root:x:0:0:root:/root:/bin/bash")
    zip_bytes = buf.getvalue()

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir)
        with pytest.raises(PluginInstallError):
            installer._extract_archive_bytes(zip_bytes, "evil.zip", dest)


def test_safe_zip_member_does_not_raise() -> None:
    """A ZIP with only safe member paths does not raise."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.toml", '[plugin]\nname = "test"\n')
        zf.writestr("nodes/node.py", "# node")
    zip_bytes = buf.getvalue()

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir)
        # Should not raise
        installer._extract_archive_bytes(zip_bytes, "safe.zip", dest)
```

---

## Section 5 — Summary Table

| ID | File | Severity | Dimension | Title |
|----|------|----------|-----------|-------|
| G4-01 | `manager.py` | 🟠 High | D1 | Duplicate-install guard bypassed for URL/path sources |
| G4-02 | `manager.py` | 🟠 High | D1 | Temp-dir cleanup not in `finally` — leaks on manifest parse failure |
| G4-03 | `manager.py` | 🟡 Medium | D3 | `enable()` `update_enabled` called after `raise` — fragile structure |
| G4-04 | `manager.py` | 🟡 Medium | D5 | No test for URL-source duplicate install bypass |
| G4-05 | `manager.py` | 🔵 Low | D7 | `enable()` missing full docstring |
| G4-06 | `loader.py` | 🟠 High | D1 | `"0.0.0"` fallback blocks all plugins when `app.__version__` unset |
| G4-07 | `loader.py` | 🟡 Medium | D1 | Accesses private `_classes` attribute of `NodeRegistry` |
| G4-08 | `loader.py` | 🟡 Medium | D3 | All-entry-points-fail returns `[]` silently — no error raised |
| G4-09 | `loader.py` | 🟡 Medium | D5 | No test for all-entry-points-fail scenario |
| G4-10 | `manifest.py` | 🟡 Medium | D1 | `load_manifest` calls `toml_path.exists()` twice — TOCTOU race |
| G4-11 | `manifest.py` | 🟡 Medium | D1 | `__init__` override breaks Pydantic `model_copy()` and pickle |
| G4-12 | `manifest.py` | 🔵 Low | D3 | `_rewrap_validation_error` annotated `-> None` instead of `-> NoReturn` |
| G4-13 | `manifest.py` | 🟡 Medium | D5 | No round-trip property test |
| G4-14 | `manifest.py` | 🔵 Low | D5 | `optional_dependencies` has no validator and no test |
| G4-15 | `store.py` | 🟡 Medium | D1 | Lock released before `PluginRecord` construction — undocumented design |
| G4-16 | `store.py` | 🟡 Medium | D1 | `_save()` missing `os.fsync()` — data loss on power failure |
| G4-17 | `store.py` | 🟡 Medium | D5 | No test for corrupt registry backup behaviour |
| G4-18 | `store.py` | 🔵 Low | D7 | `PluginRecord.load_manifest()` missing return type annotation |
| G4-19 | `installer.py` | 🟡 Medium | D1 | Temp-dir cleanup mismatch — tmpdir leaks when manifest is at archive root |
| G4-20 | `installer.py` | 🟡 Medium | D1 | `_find_manifest_dir` O(N²) iteration — no limit on directory entries |
| G4-21 | `installer.py` | 🟠 High | D5 | No test for zip-slip guard |
| G4-22 | `installer.py` | 🟡 Medium | D5 | No test for download size limit (PL-09) |
| G4-23 | `installer.py` | 🟠 High | D6 | Git URL passed without `--` separator — flag injection via crafted URL |
| G4-24 | `index.py` | 🟠 High | D1 | Class-level cache causes cross-test contamination |
| G4-25 | `index.py` | 🟠 High | D1 | `_fetch_remote` uses blocking full-body download — no size limit |
| G4-26 | `index.py` | 🟡 Medium | D1 | `lookup()` silently falls back to string match on specifier parse failure |
| G4-27 | `index.py` | 🔵 Low | D5 | No test for `lookup()` specifier parse failure fallback |
| G4-28 | `dependencies.py` | 🟠 High | D1 | `_auto_install` has no timeout — hangs indefinitely |
| G4-29 | `dependencies.py` | 🟡 Medium | D1 | `pkg_version(req.name)` does not normalise package name |
| G4-30 | `dependencies.py` | 🟡 Medium | D5 | No test for `_auto_install` success/failure path |
| G4-31 | `dependencies.py` | 🟠 High | D6 | Auto-install installs arbitrary packages without user confirmation |
| G4-32 | `errors.py` | 🔵 Low | D7 | `PluginNotFoundError` docstring missing `KeyError` repr behaviour note |
| G4-33 | `__init__.py` | 🔵 Low | D7 | Docstring import order differs from actual import order |

### Totals by Severity

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟠 High | 10 |
| 🟡 Medium | 16 |
| 🔵 Low | 7 |
| **Total** | **33** |

### Priority Remediation Order

1. **G4-02** — Temp-dir leak on manifest parse failure (data hygiene, easy fix)
2. **G4-01** — Duplicate-install guard bypass for URL sources (correctness)
3. **G4-23** — Git flag injection via crafted URL (security, one-line fix)
4. **G4-25** — Unbounded index download (DoS, mirrors existing installer pattern)
5. **G4-28** — Auto-install subprocess timeout (reliability)
6. **G4-06** — Platform version `"0.0.0"` fallback blocks plugins in dev/CI (DX)
7. **G4-31** — Auto-install supply-chain risk (documentation + policy)
8. **G4-21** — Add zip-slip property test (test coverage for existing guard)
9. **G4-24** — Class-level cache cross-test contamination (test reliability)
10. **G4-11** — `PluginManifest.__init__` override (Pydantic compatibility)
