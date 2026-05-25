# app/core/plugins/installer.py
"""
Bounded Context:  BC3 — Node Catalog (Plugin Ecosystem)
Responsibility:   Resolve a plugin source string to a local directory
                  containing plugin.toml. Supports git URLs, HTTP archives,
                  local paths/archives, and plugin index lookups.
Owns:             Source routing logic, git clone, HTTP download, archive
                  extraction, manifest directory search, checksum verification,
                  and remote source allowlist enforcement.
Public Surface:   PluginInstaller.resolve(source, version_constraint, expected_sha256)
Must NOT:         Import from app.domain, app.api, or app.models.
                  Must not register node types or touch the registry.
Dependencies:     stdlib (hashlib, io, re, shutil, subprocess, tarfile,
                  tempfile, zipfile), httpx, app.core.plugins.errors,
                  app.core.config (plugin_allowed_sources — lazy import).
Security:         Remote sources validated against GRAPHYN_PLUGIN_ALLOWED_SOURCES
                  allowlist before any network request (SEC-6 fix).
                  HTTP archives optionally verified via SHA-256 checksum.
                  Archive extraction uses is_relative_to() path traversal guard.
                  Git clone uses "--" separator to prevent flag injection (G4-23).
Reason To Change: New source type added, allowlist logic changes, or archive
                  format support extended.
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from app.core.plugins.errors import PluginInstallError

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum archive download size (PL-09 fix — prevents DoS via huge archives)
_MAX_DOWNLOAD_BYTES: int = 100 * 1024 * 1024  # 100 MB

# Version specifier pattern: name==1.0, name>=1.0, or just name
_VERSION_SPEC_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_\-]+)\s*(?P<op>==|>=|<=|!=|~=|>|<)\s*(?P<ver>\S+)$"
)


class PluginInstaller:
    """Resolves a plugin source string to a local directory containing
    ``plugin.toml`` (or ``plugin.json``).

    Parameters
    ----------
    index_client:
        Optional ``PluginIndexClient`` instance used for plain-name lookups.
        If ``None``, index lookups will raise ``PluginInstallError``.
    """

    def __init__(self, index_client: Any = None) -> None:
        self._index_client = index_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        source: str,
        version_constraint: str | None = None,
        expected_sha256: str | None = None,
    ) -> Path:
        """Resolve *source* to a local directory containing ``plugin.toml``.

        Routing logic (in order):

        1. Starts with ``git+`` or ends with ``.git``  → Git clone
        2. Starts with ``http://`` / ``https://`` and ends with ``.zip``
           or ``.tar.gz``                              → HTTP archive
        3. Existing local directory with ``plugin.toml``
           or ``plugin.json``                          → local dir copy
        4. Existing local ``.zip`` / ``.tar.gz`` file  → local archive
        5. Otherwise (plain name, optionally versioned) → index lookup

        Parameters
        ----------
        source:
            Source string as provided by the user / caller.
        version_constraint:
            Optional PEP 440 version constraint string (e.g. ``">=1.0"``).
            Only used for index lookups; ignored for URL / path sources.
        expected_sha256:
            Optional expected SHA-256 hex digest of the downloaded archive.
            When provided for HTTP archive sources, the digest is verified
            before extraction and ``PluginInstallError`` is raised on mismatch.
            Ignored for local path and git sources (SEC-6 fix).

        Returns
        -------
        Path
            Path to a *temporary* directory containing ``plugin.toml``.
            The caller is responsible for moving this directory before it
            is cleaned up.

        Raises
        ------
        PluginInstallError
            On any fetch, clone, extraction, validation, or allowlist failure.
        """
        # SEC-6 fix: validate remote sources against the allowlist before
        # fetching any content.  Local path sources are never restricted.
        if source.startswith(("git+", "http://", "https://")):
            self._check_allowed_source(source)

        # --- 1. Git source ---
        if source.startswith("git+") or source.endswith(".git"):
            return self._resolve_git(source)

        # --- 2. HTTP archive ---
        if source.startswith(("http://", "https://")):
            if source.endswith(".zip") or source.endswith(".tar.gz"):
                return self._resolve_http_archive(source, expected_sha256=expected_sha256)
            # Non-archive HTTP URL: treat as git URL (e.g. bare GitHub URL)
            return self._resolve_git(source)

        # --- 3 & 4. Local path ---
        local = Path(source)
        if local.exists():
            if local.is_dir():
                if (local / "plugin.toml").exists() or (local / "plugin.json").exists():
                    return self._resolve_local_dir(local)
                raise PluginInstallError(
                    f"Local directory {source!r} does not contain 'plugin.toml' or 'plugin.json'."
                )
            if local.is_file() and (
                source.endswith(".zip") or source.endswith(".tar.gz")
            ):
                return self._resolve_local_archive(local)

        # --- 5. Plain name / index lookup ---
        name, ver = self._parse_name_version(source)
        effective_version = version_constraint or ver
        return self._resolve_index(name, effective_version)

    # ------------------------------------------------------------------
    # Resolver implementations (Task 9.2)
    # ------------------------------------------------------------------

    def _check_allowed_source(self, source: str) -> None:
        """Raise PluginInstallError if *source* is not on the allowlist.

        The allowlist is read from ``GRAPHYN_PLUGIN_ALLOWED_SOURCES`` via
        ``app.core.config.plugin_allowed_sources()``.  When the list is empty
        (the default), all sources are permitted.

        Parameters
        ----------
        source:
            Remote source string to validate.

        Raises
        ------
        PluginInstallError
            When the allowlist is non-empty and *source* does not start with
            any of the listed prefixes.
        """
        from app.core.config import plugin_allowed_sources as _allowed_sources  # noqa: PLC0415

        allowed = _allowed_sources()
        if not allowed:
            return  # allowlist not configured — permit all (backward compat)

        for prefix in allowed:
            if source.startswith(prefix):
                return

        raise PluginInstallError(
            f"Plugin source {source!r} is not in the allowed sources list. "
            f"Set GRAPHYN_PLUGIN_ALLOWED_SOURCES to include this prefix, "
            f"or leave it unset to allow all sources. "
            f"Current allowed prefixes: {allowed}"
        )

    def _resolve_git(self, url: str) -> Path:
        """Clone *url* with ``git clone --depth 1`` and return the manifest dir."""
        # PL-08 fix: check that git is available before attempting the clone
        if shutil.which("git") is None:
            raise PluginInstallError(
                "git is not installed or not on PATH. "
                "Install git to use git+URL plugin sources."
            )

        clone_url = url[len("git+"):] if url.startswith("git+") else url

        tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_git_"))
        try:
            result = subprocess.run(
                # G4-23 fix: use "--" before the URL to prevent git from
                # interpreting a crafted URL like "--upload-pack=cmd" as a flag.
                ["git", "clone", "--depth", "1", "--", clone_url, str(tmpdir)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise PluginInstallError(
                    f"Git clone failed for {url!r}.\n"
                    f"git stderr:\n{result.stderr.strip()}"
                )
            return self._find_manifest_dir(tmpdir)
        except PluginInstallError:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise PluginInstallError(
                f"Unexpected error cloning {url!r}: {exc}"
            ) from exc

    def _resolve_http_archive(self, url: str, expected_sha256: str | None = None) -> Path:
        """Download an HTTP archive and extract it to a temporary directory.

        Enforces a ``_MAX_DOWNLOAD_BYTES`` size limit to prevent DoS via
        oversized archives (PL-09 fix).

        When *expected_sha256* is provided, the downloaded bytes are verified
        against the digest before extraction.  A mismatch raises
        ``PluginInstallError`` (SEC-6 fix).
        """
        tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_http_"))
        try:
            data = self._download_with_limit(url)
            if expected_sha256:
                self._verify_checksum(data, f"sha256:{expected_sha256}")
            extracted = self._extract_archive_bytes(data, url, tmpdir)
            return self._find_manifest_dir(extracted)
        except PluginInstallError:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise PluginInstallError(
                f"Unexpected error downloading {url!r}: {exc}"
            ) from exc

    def _download_with_limit(self, url: str) -> bytes:
        """Stream-download *url* and return bytes, enforcing _MAX_DOWNLOAD_BYTES.

        Raises PluginInstallError on HTTP errors, network errors, or size exceeded.
        """
        chunks: list[bytes] = []
        total = 0
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=30.0) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(chunk_size=65_536):
                    total += len(chunk)
                    if total > _MAX_DOWNLOAD_BYTES:
                        raise PluginInstallError(
                            f"Download from {url!r} exceeds the maximum allowed size "
                            f"of {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB."
                        )
                    chunks.append(chunk)
        except httpx.HTTPStatusError as exc:
            raise PluginInstallError(
                f"HTTP download failed for {url!r}: status {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise PluginInstallError(
                f"Network error downloading {url!r}: {exc}"
            ) from exc
        return b"".join(chunks)

    def _resolve_local_dir(self, path: Path) -> Path:
        """Copy a local plugin directory to a temporary location.

        Returns the copied directory path. The parent tmpdir is stored as
        ``resolved_dir.parent`` — callers should clean it up after use.
        """
        tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_local_"))
        dest = tmpdir / path.name
        try:
            shutil.copytree(str(path), str(dest))
            return dest
        except Exception as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise PluginInstallError(
                f"Failed to copy local plugin directory {path!r}: {exc}"
            ) from exc

    def _resolve_local_archive(self, path: Path) -> Path:
        """Extract a local archive to a temporary directory.

        Parameters
        ----------
        path:
            Existing ``.zip`` or ``.tar.gz`` file.

        Returns
        -------
        Path
            Directory inside the extracted archive that contains ``plugin.toml``.
        """
        tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_archive_"))
        try:
            data = path.read_bytes()
            extracted = self._extract_archive_bytes(data, str(path), tmpdir)
            return self._find_manifest_dir(extracted)
        except PluginInstallError:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise PluginInstallError(
                f"Failed to extract local archive {path!r}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Helper methods (Task 9.3)
    # ------------------------------------------------------------------

    def _find_manifest_dir(self, root: Path) -> Path:
        """Search up to 2 directory levels deep for ``plugin.toml`` or
        ``plugin.json`` and return the containing directory.

        Parameters
        ----------
        root:
            Root directory to search from.

        Returns
        -------
        Path
            Directory that directly contains the manifest file.

        Raises
        ------
        PluginInstallError
            If no manifest is found within 2 levels.
        """
        # Level 0: root itself
        if (root / "plugin.toml").exists() or (root / "plugin.json").exists():
            return root

        # Level 1: immediate children
        for child in root.iterdir():
            if not child.is_dir():
                continue
            if (child / "plugin.toml").exists() or (child / "plugin.json").exists():
                return child

            # Level 2: grandchildren
            for grandchild in child.iterdir():
                if not grandchild.is_dir():
                    continue
                if (
                    (grandchild / "plugin.toml").exists()
                    or (grandchild / "plugin.json").exists()
                ):
                    return grandchild

        raise PluginInstallError(
            f"No 'plugin.toml' or 'plugin.json' found within two directory levels "
            f"of {root!r}."
        )

    def _verify_checksum(self, data: bytes, checksum: str) -> None:
        """Verify *data* against a ``sha256:<hex>`` checksum string.

        Parameters
        ----------
        data:
            Raw bytes to verify.
        checksum:
            Expected checksum in ``sha256:<hex>`` format.

        Raises
        ------
        PluginInstallError
            If the format is unrecognised or the digest does not match.
        """
        if not checksum.startswith("sha256:"):
            raise PluginInstallError(
                f"Unsupported checksum format {checksum!r}. "
                "Only 'sha256:<hex>' is supported."
            )
        expected_hex = checksum[len("sha256:"):]
        actual_hex = hashlib.sha256(data).hexdigest()
        if actual_hex != expected_hex:
            raise PluginInstallError(
                f"Checksum mismatch: expected sha256:{expected_hex}, "
                f"got sha256:{actual_hex}."
            )

    def _parse_name_version(self, source: str) -> tuple[str, str | None]:
        """Parse a plain plugin name with an optional version specifier.

        Supported formats:
          - ``name``              → ``("name", None)``
          - ``name==1.2.0``       → ``("name", "==1.2.0")``
          - ``name>=1.0``         → ``("name", ">=1.0")``
          - ``name<=2.0``         → ``("name", "<=2.0")``
          - ``name!=1.0``         → ``("name", "!=1.0")``
          - ``name~=1.0``         → ``("name", "~=1.0")``
          - ``name>1.0``          → ``("name", ">1.0")``
          - ``name<2.0``          → ``("name", "<2.0")``

        Parameters
        ----------
        source:
            Raw source string (plain name or name+version specifier).

        Returns
        -------
        tuple[str, str | None]
            ``(name, version_constraint_or_None)``
        """
        match = _VERSION_SPEC_RE.match(source.strip())
        if match:
            name = match.group("name")
            op = match.group("op")
            ver = match.group("ver")
            return name, f"{op}{ver}"
        # No version specifier — return the whole string as the name
        return source.strip(), None

    def _resolve_index(self, name: str, version: str | None) -> Path:
        """Look up *name* in the plugin index and download the archive."""
        if self._index_client is None:
            raise PluginInstallError(
                f"Cannot resolve plugin {name!r} from index: "
                "no index client is configured."
            )

        try:
            entry = self._index_client.lookup(name, version)
        except Exception as exc:
            raise PluginInstallError(
                f"Plugin index lookup failed for {name!r} "
                f"(version={version!r}): {exc}"
            ) from exc

        url: str = entry.download_url
        checksum: str | None = getattr(entry, "checksum", None)

        tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_index_"))
        try:
            # Use streaming download with size limit (PL-09 fix)
            data = self._download_with_limit(url)

            if checksum:
                self._verify_checksum(data, checksum)

            extracted = self._extract_archive_bytes(data, url, tmpdir)
            return self._find_manifest_dir(extracted)
        except PluginInstallError:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise PluginInstallError(
                f"Unexpected error installing {name!r} from index: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Private extraction helper
    # ------------------------------------------------------------------

    def _extract_archive_bytes(
        self, data: bytes, source_hint: str, dest_dir: Path
    ) -> Path:
        """Extract *data* (zip or tar.gz) into *dest_dir* and return *dest_dir*.

        Parameters
        ----------
        data:
            Raw archive bytes.
        source_hint:
            URL or file path used in error messages.
        dest_dir:
            Directory to extract into (must already exist).

        Returns
        -------
        Path
            *dest_dir* after extraction.

        Raises
        ------
        PluginInstallError
            If the archive format is not recognised or extraction fails.
        """
        buf = io.BytesIO(data)

        # Try zip first
        if zipfile.is_zipfile(buf):
            buf.seek(0)
            try:
                with zipfile.ZipFile(buf) as zf:
                    dest_resolved = dest_dir.resolve()
                    for member in zf.infolist():
                        member_path = (dest_dir / member.filename).resolve()
                        # PL-10 fix: use is_relative_to() — safe on
                        # case-insensitive filesystems (macOS/Windows)
                        if not member_path.is_relative_to(dest_resolved):
                            raise PluginInstallError(
                                f"Unsafe ZIP entry '{member.filename}' would extract "
                                f"outside the destination directory."
                            )
                    zf.extractall(dest_dir)
            except PluginInstallError:
                raise
            except Exception as exc:
                raise PluginInstallError(
                    f"Failed to extract ZIP archive from {source_hint!r}: {exc}"
                ) from exc
            return dest_dir

        # Try tar (gzip / bz2 / xz)
        buf.seek(0)
        if tarfile.is_tarfile(buf):
            buf.seek(0)
            try:
                with tarfile.open(fileobj=buf) as tf:
                    dest_resolved = dest_dir.resolve()
                    for member in tf.getmembers():
                        member_path = (dest_dir / member.name).resolve()
                        # PL-10 fix: use is_relative_to()
                        if not member_path.is_relative_to(dest_resolved):
                            raise PluginInstallError(
                                f"Unsafe TAR entry '{member.name}' would extract "
                                f"outside the destination directory."
                            )
                    tf.extractall(dest_dir)
            except PluginInstallError:
                raise
            except Exception as exc:
                raise PluginInstallError(
                    f"Failed to extract TAR archive from {source_hint!r}: {exc}"
                ) from exc
            return dest_dir

        raise PluginInstallError(
            f"Unrecognised archive format for {source_hint!r}. "
            "Expected a .zip or .tar.gz file."
        )
