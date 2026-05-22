# design-03 — PluginInstaller and PluginIndexClient

## Overview

`PluginInstaller` resolves a source string to a local plugin directory. `PluginIndexClient` fetches and searches the plugin index. Both are stateless and use `httpx` for HTTP operations.

## PluginInstaller

### File: `app/core/plugins/installer.py`

```python
from __future__ import annotations
import hashlib
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from app.core.plugins.errors import PluginInstallError

class PluginInstaller:
    """Resolves a source string to a local plugin directory."""

    def resolve(self, source: str, version_constraint: str | None = None) -> Path:
        """Return a Path to a local plugin directory. Caller is responsible for cleanup."""
        s = source.strip()
        if s.startswith("git+") or s.endswith(".git"):
            return self._resolve_git(s)
        if s.startswith("http://") or s.startswith("https://"):
            if s.endswith(".zip") or s.endswith(".tar.gz"):
                return self._resolve_http_archive(s)
            # Treat as git URL
            return self._resolve_git(s)
        local = Path(s)
        if local.exists():
            if local.is_dir():
                return self._resolve_local_dir(local)
            if local.suffix in (".zip",) or s.endswith(".tar.gz"):
                return self._resolve_local_archive(local)
        # Plain name — look up in index
        name, version = self._parse_name_version(s)
        return self._resolve_index(name, version or version_constraint)

    def _resolve_git(self, url: str) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_git_"))
        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(tmpdir)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise PluginInstallError(
                f"git clone failed for '{url}': {result.stderr.strip()}"
            )
        return self._find_manifest_dir(tmpdir, url)

    def _resolve_http_archive(self, url: str, expected_checksum: str | None = None) -> Path:
        import httpx
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PluginInstallError(
                f"HTTP {exc.response.status_code} downloading '{url}'"
            ) from exc
        except Exception as exc:
            raise PluginInstallError(f"Failed to download '{url}': {exc}") from exc

        data = resp.content
        if expected_checksum:
            self._verify_checksum(data, expected_checksum, url)

        suffix = ".zip" if url.endswith(".zip") else ".tar.gz"
        tmpfile = Path(tempfile.mktemp(suffix=suffix, prefix="kiro_plugin_"))
        tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_arch_"))
        try:
            tmpfile.write_bytes(data)
            self._extract_archive(tmpfile, tmpdir, url)
            return self._find_manifest_dir(tmpdir, url)
        finally:
            tmpfile.unlink(missing_ok=True)

    def _resolve_local_dir(self, path: Path) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_local_"))
        shutil.copytree(path, tmpdir / path.name)
        return self._find_manifest_dir(tmpdir / path.name, str(path))

    def _resolve_local_archive(self, path: Path) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_larch_"))
        self._extract_archive(path, tmpdir, str(path))
        return self._find_manifest_dir(tmpdir, str(path))

    def _resolve_index(self, name: str, version: str | None) -> Path:
        from app.core.plugins.index import PluginIndexClient
        client = PluginIndexClient()
        entry = client.lookup(name, version)
        return self._resolve_http_archive(entry.download_url, entry.checksum)

    def _extract_archive(self, archive: Path, dest: Path, source_label: str) -> None:
        try:
            if str(archive).endswith(".zip"):
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(dest)
            else:
                with tarfile.open(archive) as tf:
                    tf.extractall(dest)
        except Exception as exc:
            raise PluginInstallError(
                f"Failed to extract archive '{source_label}': {exc}"
            ) from exc

    def _find_manifest_dir(self, root: Path, source_label: str) -> Path:
        """Search up to 2 levels deep for a directory containing plugin.toml."""
        for candidate in [root] + list(root.iterdir() if root.is_dir() else []):
            if isinstance(candidate, Path) and candidate.is_dir():
                if (candidate / "plugin.toml").exists() or (candidate / "plugin.json").exists():
                    return candidate
                for sub in candidate.iterdir():
                    if sub.is_dir():
                        if (sub / "plugin.toml").exists() or (sub / "plugin.json").exists():
                            return sub
        raise PluginInstallError(
            f"No plugin.toml found within 2 directory levels of '{source_label}'"
        )

    def _verify_checksum(self, data: bytes, checksum: str, url: str) -> None:
        if checksum.startswith("sha256:"):
            expected = checksum[7:]
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                raise PluginInstallError(
                    f"Checksum mismatch for '{url}': expected {expected}, got {actual}"
                )

    def _parse_name_version(self, s: str) -> tuple[str, str | None]:
        if "==" in s:
            name, version = s.split("==", 1)
            return name.strip(), version.strip()
        return s, None
```

## PluginIndexClient

### File: `app/core/plugins/index.py`

```python
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from pydantic import BaseModel
from app.core.plugins.errors import PluginIndexError, PluginNotFoundError

log = logging.getLogger(__name__)

class PluginIndexEntry(BaseModel):
    name: str
    version: str
    description: str
    author: str
    tags: list[str] = []
    platform_version: str
    download_url: str
    homepage: str | None = None
    checksum: str | None = None

class PluginIndexClient:
    _cache: list[PluginIndexEntry] | None = None  # class-level in-memory cache

    def fetch(self) -> list[PluginIndexEntry]:
        if PluginIndexClient._cache is not None:
            return PluginIndexClient._cache
        url = os.environ.get("GRAPHYN_PLUGIN_INDEX_URL", "")
        if url:
            entries = self._fetch_remote(url)
        else:
            entries = self._fetch_local()
        PluginIndexClient._cache = entries
        return entries

    def _fetch_remote(self, url: str) -> list[PluginIndexEntry]:
        import httpx
        try:
            resp = httpx.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise PluginIndexError(f"Failed to fetch plugin index from '{url}': {exc}") from exc
        return self._parse_index(data)

    def _fetch_local(self) -> list[PluginIndexEntry]:
        workspace = os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")
        local_path = Path(workspace) / "plugins" / "index.json"
        if not local_path.exists():
            log.warning("No plugin index available (set GRAPHYN_PLUGIN_INDEX_URL or create workspace/plugins/index.json)")
            return []
        try:
            with open(local_path) as f:
                data = json.load(f)
        except Exception as exc:
            raise PluginIndexError(f"Failed to read local index at '{local_path}': {exc}") from exc
        return self._parse_index(data)

    def _parse_index(self, data: dict) -> list[PluginIndexEntry]:
        return [PluginIndexEntry.model_validate(e) for e in data.get("plugins", [])]

    def search(self, query: str) -> list[PluginIndexEntry]:
        q = query.lower()
        return [
            e for e in self.fetch()
            if q in e.name.lower()
            or q in e.description.lower()
            or any(q in t.lower() for t in e.tags)
        ]

    def lookup(self, name: str, version: str | None = None) -> PluginIndexEntry:
        entries = [e for e in self.fetch() if e.name == name]
        if not entries:
            raise PluginNotFoundError(f"Plugin '{name}' not found in index.")
        if version:
            from packaging.version import Version
            from packaging.specifiers import SpecifierSet
            spec = SpecifierSet(f"=={version}" if not any(c in version for c in "<>=!~") else version)
            entries = [e for e in entries if Version(e.version) in spec]
            if not entries:
                raise PluginNotFoundError(f"Plugin '{name}' version '{version}' not found in index.")
        # Return highest version
        return sorted(entries, key=lambda e: Version(e.version), reverse=True)[0]
```

## Design Decisions

1. **Class-level cache for `PluginIndexClient`**: The index is fetched once per process and cached in memory. This avoids repeated network calls during a session. The cache is reset between test runs by clearing `PluginIndexClient._cache = None`.

2. **`PluginInstaller.resolve()` returns a `Path` but does not clean up**: The caller (`PluginManager.install()`) is responsible for cleanup. This allows `PluginManager` to copy the directory before cleanup, avoiding a race condition.

3. **`_find_manifest_dir` searches 2 levels deep**: Archives from GitHub (e.g., `repo-main.zip`) typically extract to a single top-level directory. Searching 2 levels handles both flat archives and nested archives.

4. **`httpx` for HTTP**: `httpx` is already a project dependency (used by FastAPI's test client). Using it avoids adding `requests` as a new dependency.
