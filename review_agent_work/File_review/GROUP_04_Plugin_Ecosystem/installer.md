# Functional Review — app/core/plugins/installer.py

**Group:** 4 — Plugin Ecosystem  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/plugins/installer.py
FUNCTION:    PluginInstaller._resolve_git
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Clone a git URL with `--depth 1` and return the manifest directory inside the cloned repo.

WHAT IT ACTUALLY DOES:
Creates `tmpdir` via `tempfile.mkdtemp()`, then calls `self._find_manifest_dir(tmpdir)`. If `_find_manifest_dir` raises `PluginInstallError` (no manifest found), the `except PluginInstallError` block calls `shutil.rmtree(tmpdir)` and re-raises — correct. However, `_find_manifest_dir` returns a *subdirectory* of `tmpdir` (e.g. `tmpdir/plugin_name/`). The caller (`PluginManager.install()`) later cleans up `resolved_tmpdir = resolved_dir.parent`. If `_find_manifest_dir` returns `tmpdir` itself (level 0 match), then `resolved_dir.parent` is the system temp directory — `shutil.rmtree` is called on the system temp dir's parent, which is guarded by the `startswith("kiro_plugin_")` check. But if `_find_manifest_dir` returns a grandchild (level 2), `resolved_dir.parent` is a child of `tmpdir`, not `tmpdir` itself, so `tmpdir` is never cleaned up.

THE BUG / RISK:
When the manifest is found at level 2 (grandchild), `resolved_tmpdir = resolved_dir.parent` points to the level-1 child directory. The `startswith("kiro_plugin_")` guard in `manager.py` checks `resolved_tmpdir.name`, which is the child's name (not the `kiro_plugin_git_` prefixed tmpdir). The guard fails, and the top-level tmpdir is never deleted. Disk space leaks on every git install where the manifest is nested two levels deep.

EVIDENCE:
```python
# _resolve_git:
tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_git_"))
# ...
return self._find_manifest_dir(tmpdir)
# _find_manifest_dir can return tmpdir/child/grandchild

# manager.py:
resolved_tmpdir: Path = resolved_dir.parent   # = tmpdir/child, not tmpdir
if resolved_tmpdir.name.startswith("kiro_plugin_"):  # child name, not kiro_plugin_git_*
    shutil.rmtree(...)   # NOT called
```

REPRODUCTION SCENARIO:
Clone a git repo where the plugin manifest is at `repo_root/plugin_subdir/plugin.toml`. `_find_manifest_dir` returns `tmpdir/repo_root/plugin_subdir`. `resolved_dir.parent` = `tmpdir/repo_root`. `tmpdir` is never cleaned up.

IMPACT:
Disk space leak. On a busy system with many installs, this can exhaust `/tmp`.

FIX DIRECTION:
`_resolve_git` (and all `_resolve_*` methods) should return a tuple `(manifest_dir, tmpdir_to_cleanup)` so the caller always has the root tmpdir. Alternatively, store the tmpdir as an instance attribute or use a context manager.

--------------------------------------------------------------------
FILE:        app/core/plugins/installer.py
FUNCTION:    PluginInstaller._resolve_local_dir
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Copy a local plugin directory to a temporary location and return the copied directory path.

WHAT IT ACTUALLY DOES:
Creates `tmpdir`, copies the plugin into `tmpdir/path.name`, and returns `dest = tmpdir/path.name`. The docstring says "The parent tmpdir is stored as `resolved_dir.parent`". In `manager.py`, `resolved_tmpdir = resolved_dir.parent = tmpdir`. The `startswith("kiro_plugin_")` check uses `resolved_tmpdir.name` which is `kiro_plugin_local_XXXXXX` — this works correctly for the local dir case.

However, if `shutil.copytree` raises (e.g. permission error on a file inside the source), the `except` block calls `shutil.rmtree(tmpdir)` and re-raises `PluginInstallError`. But `shutil.copytree` may have partially created `dest` before failing. `shutil.rmtree(tmpdir)` will clean up the partial copy — this is correct. No leak here.

THE BUG / RISK:
Actually no resource leak in this specific method. However, there is a subtle issue: `shutil.copytree` follows symlinks by default (`symlinks=False`). A malicious plugin directory could contain a symlink pointing outside the plugin directory (e.g. to `/etc/passwd`). The copy would include the symlink target's content, potentially exposing sensitive files to the plugin load process.

EVIDENCE:
```python
shutil.copytree(str(path), str(dest))   # symlinks=False by default — dereferences symlinks
```

REPRODUCTION SCENARIO:
A local plugin directory contains `nodes.py -> /etc/shadow`. `shutil.copytree` copies the content of `/etc/shadow` into the temp directory. The plugin is then loaded from the temp directory.

IMPACT:
Information disclosure: sensitive files could be read by the plugin loading process. Low severity in practice since local path installs are trusted, but worth noting.

FIX DIRECTION:
Use `shutil.copytree(str(path), str(dest), symlinks=True)` to preserve symlinks rather than dereference them, preventing content exfiltration.

--------------------------------------------------------------------
FILE:        app/core/plugins/installer.py
FUNCTION:    PluginInstaller.resolve
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Route 3 & 4: handle existing local paths. If a local path exists but is a file that is not `.zip` or `.tar.gz`, fall through to the index lookup.

WHAT IT ACTUALLY DOES:
```python
local = Path(source)
if local.exists():
    if local.is_dir():
        ...
    if local.is_file() and (source.endswith(".zip") or source.endswith(".tar.gz")):
        return self._resolve_local_archive(local)
# Falls through to index lookup if file exists but is not zip/tar.gz
```

If a local file exists but is not a recognized archive (e.g. a `.whl` file or a `.tar.bz2`), the code silently falls through to the index lookup using the full file path as the plugin name. The index lookup will fail with a confusing `PluginInstallError: Cannot resolve plugin '/path/to/file.whl' from index`.

THE BUG / RISK:
Silent wrong routing: a user who passes a local `.tar.bz2` archive gets a confusing "index lookup failed" error instead of "unsupported archive format".

EVIDENCE:
```python
if local.is_file() and (source.endswith(".zip") or source.endswith(".tar.gz")):
    return self._resolve_local_archive(local)
# No else: falls through silently
```

REPRODUCTION SCENARIO:
`installer.resolve("/tmp/my_plugin.tar.bz2")` → `local.exists()` is True, `local.is_file()` is True, but `source.endswith(".tar.gz")` is False → falls through to `_resolve_index("/tmp/my_plugin.tar.bz2", None)` → raises `PluginInstallError: Cannot resolve plugin '/tmp/my_plugin.tar.bz2' from index`.

IMPACT:
Confusing error message; user cannot diagnose the real problem.

FIX DIRECTION:
Add an explicit check: if `local.is_file()` and the file exists but is not a recognized archive, raise `PluginInstallError` with a clear message listing supported formats.

--------------------------------------------------------------------
FILE:        app/core/plugins/installer.py
FUNCTION:    PluginInstaller._resolve_git
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Clone a git URL and return the manifest directory.

WHAT IT ACTUALLY DOES:
Uses `subprocess.run` without a `timeout` parameter. A git clone of a large or slow repository will block indefinitely.

THE BUG / RISK:
If the remote git server is slow or unresponsive, `subprocess.run` hangs forever. The platform API request that triggered the install will never complete. No timeout means no recovery without killing the process.

EVIDENCE:
```python
result = subprocess.run(
    ["git", "clone", "--depth", "1", "--", clone_url, str(tmpdir)],
    capture_output=True,
    text=True,
    # no timeout=
)
```

REPRODUCTION SCENARIO:
`installer.resolve("git+https://slow-server.example.com/plugin.git")` — the git clone hangs indefinitely.

IMPACT:
Hang / resource exhaustion. The API worker thread is blocked forever.

FIX DIRECTION:
Add `timeout=120` (or a configurable value) to `subprocess.run`. Catch `subprocess.TimeoutExpired` and raise `PluginInstallError`.

--------------------------------------------------------------------
FILE:        app/core/plugins/installer.py
FUNCTION:    PluginInstaller._extract_archive_bytes
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Extract zip or tar archive bytes into `dest_dir`.

WHAT IT ACTUALLY DOES:
For tar archives, uses `tarfile.is_tarfile(buf)` to detect the format. `tarfile.is_tarfile()` accepts gzip, bz2, and xz compressed tars. However, the path traversal guard iterates `tf.getmembers()` and checks each member path. For symlink members in a tar archive, `member.name` is the symlink name (safe), but `member.linkname` (the symlink target) is not checked. A tar archive with a symlink pointing outside `dest_dir` would pass the path traversal check but could be exploited after extraction.

THE BUG / RISK:
Symlink in tar archive: `member.name = "plugin/nodes.py"` (safe), `member.linkname = "../../../../etc/cron.d/evil"`. The path traversal guard only checks `member.name`, not `member.linkname`. After extraction, `plugin/nodes.py` is a symlink to `/etc/cron.d/evil`. When the plugin is loaded, writing to `nodes.py` writes to the cron directory.

EVIDENCE:
```python
for member in tf.getmembers():
    member_path = (dest_dir / member.name).resolve()
    if not member_path.is_relative_to(dest_resolved):
        raise PluginInstallError(...)
# member.linkname not checked
tf.extractall(dest_dir)
```

REPRODUCTION SCENARIO:
Craft a tar.gz with a symlink entry: `name="plugin/evil.py"`, `linkname="../../../../tmp/evil"`. The guard passes. After extraction, `plugin/evil.py` points outside `dest_dir`.

IMPACT:
Potential path traversal via symlink. Severity depends on what the plugin loader does with the extracted files.

FIX DIRECTION:
Filter out symlink and hardlink members, or check `member.linkname` for absolute paths and `..` components:
```python
if member.issym() or member.islnk():
    raise PluginInstallError(f"Archive contains symlink '{member.name}' — not allowed.")
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | NO |
| Top Risk | `_resolve_git` tmpdir cleanup fails when manifest is found at level 2 depth, leaking disk space on every such install |
