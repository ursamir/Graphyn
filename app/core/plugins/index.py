"""
PluginIndexClient — fetches, caches, and searches the plugin index.

The index is a JSON document with a top-level ``plugins`` array. It can be
hosted remotely (configured via ``GRAPHYN_PLUGIN_INDEX_URL``) or stored locally
at ``{GRAPHYN_HOME}/plugins/index.json``.

Requirements: req-05 §6.1–§6.9
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

import httpx
from pydantic import BaseModel

from app.core.plugins.errors import PluginIndexError, PluginNotFoundError

logger = logging.getLogger(__name__)


class PluginIndexEntry(BaseModel):
    """A single entry in the plugin index representing one available plugin version.

    Requirements: req-05 §6.1
    """

    name: str
    version: str
    description: str
    author: str
    tags: list[str]
    platform_version: str
    download_url: str
    homepage: str | None = None
    checksum: str | None = None


class PluginIndexClient:
    """Fetches and searches the plugin index.

    The fetched index is cached in memory at the class level for the duration
    of the process (no disk caching). Reset ``_cache`` to ``None`` in tests to
    prevent cross-test contamination.

    Requirements: req-05 §6.1–§6.9
    """

    # Class-level cache shared across all instances — req-05 §6.7
    _cache: list[PluginIndexEntry] | None = None
    _cache_lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def fetch(self) -> list[PluginIndexEntry]:
        """Return the plugin index, using the in-memory cache when available.

        Fetch strategy (req-05 §6.2, §6.3, §6.4):
        1. If ``GRAPHYN_PLUGIN_INDEX_URL`` is set → fetch from remote URL.
        2. Else → read local ``{GRAPHYN_HOME}/plugins/index.json``.
        3. If neither is available → log WARNING and return ``[]``.

        The result is stored in ``_cache`` after the first successful fetch.

        Returns:
            List of ``PluginIndexEntry`` objects (may be empty).

        Raises:
            PluginIndexError: When the remote fetch fails (network error or
                non-2xx response). req-05 §6.8
        """
        if PluginIndexClient._cache is not None:
            return PluginIndexClient._cache

        with PluginIndexClient._cache_lock:
            # Double-checked locking: re-check after acquiring the lock
            if PluginIndexClient._cache is not None:
                return PluginIndexClient._cache

            from app.core.config import plugin_index_url as _plugin_index_url
            url = _plugin_index_url()

            if url:
                entries = self._fetch_remote(url)
            else:
                entries = self._fetch_local()

            if not entries and not url:
                # Neither remote URL nor local file produced results
                from app.core.config import plugin_index_local_path as _plugin_index_local_path
                local_path = _plugin_index_local_path()
                if not local_path.exists():
                    logger.warning(
                        "No plugin index available: GRAPHYN_PLUGIN_INDEX_URL is not set "
                        "and local index file '%s' does not exist. "
                        "Returning empty plugin index.",
                        local_path,
                    )

            PluginIndexClient._cache = entries
            return entries

    def search(self, query: str) -> list[PluginIndexEntry]:
        """Return all index entries where *query* appears (case-insensitive)
        in ``name``, ``description``, or any element of ``tags``.

        Requirements: req-05 §6.5

        Args:
            query: Search string. An empty query returns all entries.

        Returns:
            Filtered list of ``PluginIndexEntry`` objects.
        """
        entries = self.fetch()
        if not query:
            return list(entries)

        needle = query.lower()
        results: list[PluginIndexEntry] = []
        for entry in entries:
            if (
                needle in entry.name.lower()
                or needle in entry.description.lower()
                or any(needle in tag.lower() for tag in entry.tags)
            ):
                results.append(entry)
        return results

    def lookup(self, name: str, version: str | None = None) -> PluginIndexEntry:
        """Find a plugin by name, optionally filtered by a version constraint.

        When *version* is ``None``, the entry with the highest version is returned.
        When *version* is a PEP 440 specifier string (e.g. ``">=1.0"``,
        ``"==1.2.0"``), all matching entries are filtered and the highest
        satisfying version is returned. A bare version string (e.g. ``"1.2.0"``)
        is treated as ``"==1.2.0"``.

        Requirements: req-05 §6.1, §6.9

        Args:
            name: Exact plugin name (case-sensitive).
            version: PEP 440 version specifier string, or ``None`` for latest.

        Returns:
            The matching ``PluginIndexEntry``.

        Raises:
            PluginNotFoundError: When no entry matches the name (and optional
                version constraint). req-05 §6.9
        """
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version

        entries = self.fetch()
        matches = [e for e in entries if e.name == name]

        if not matches:
            raise PluginNotFoundError(
                f"Plugin '{name}' not found in the index."
            )

        if version is not None:
            # Normalise bare version strings to an exact specifier
            version_str = version.strip()
            if version_str and version_str[0].isdigit():
                version_str = f"=={version_str}"
            try:
                spec = SpecifierSet(version_str)
                versioned = [
                    e for e in matches
                    if Version(e.version) in spec
                ]
            except Exception:
                # Fallback: exact string match if specifier parsing fails
                versioned = [e for e in matches if e.version == version_str]

            if not versioned:
                raise PluginNotFoundError(
                    f"Plugin '{name}' has no version satisfying '{version}' in the index. "
                    f"Available versions: {sorted(e.version for e in matches)}"
                )
            try:
                return max(versioned, key=lambda e: Version(e.version))
            except Exception:
                return versioned[0]

        # Return the entry with the highest version
        try:
            return max(matches, key=lambda e: Version(e.version))
        except Exception:
            # Fallback: lexicographic sort if version is non-PEP-440
            return max(matches, key=lambda e: e.version)

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _fetch_remote(self, url: str) -> list[PluginIndexEntry]:
        """Fetch the plugin index from a remote URL.

        G4-25 fix: uses streaming with a 10 MB size limit to prevent DoS via
        an oversized index response (previously used blocking httpx.get with
        no size cap).

        Requirements: req-05 §6.2, §6.8
        """
        _MAX_INDEX_BYTES = 10 * 1024 * 1024  # 10 MB
        chunks: list[bytes] = []
        total = 0
        try:
            with httpx.stream("GET", url, timeout=10, follow_redirects=True) as response:
                if not response.is_success:
                    raise PluginIndexError(
                        f"Plugin index fetch from '{url}' returned HTTP {response.status_code}."
                    )
                for chunk in response.iter_bytes(chunk_size=65_536):
                    total += len(chunk)
                    if total > _MAX_INDEX_BYTES:
                        raise PluginIndexError(
                            f"Plugin index from '{url}' exceeds the maximum allowed size "
                            f"of {_MAX_INDEX_BYTES // (1024 * 1024)} MB."
                        )
                    chunks.append(chunk)
        except PluginIndexError:
            raise
        except Exception as exc:
            raise PluginIndexError(
                f"Failed to fetch plugin index from '{url}': {exc}"
            ) from exc

        try:
            data = json.loads(b"".join(chunks))
            plugins_raw = data.get("plugins", [])
            return [PluginIndexEntry(**item) for item in plugins_raw]
        except PluginIndexError:
            raise
        except Exception as exc:
            raise PluginIndexError(
                f"Failed to parse plugin index from '{url}': {exc}"
            ) from exc

    def _fetch_local(self) -> list[PluginIndexEntry]:
        """Read the plugin index from the local workspace file.

        Reads ``{GRAPHYN_HOME}/plugins/index.json``. Returns ``[]`` if the
        file does not exist.

        Requirements: req-05 §6.3, §6.4

        Returns:
            Parsed list of ``PluginIndexEntry`` objects, or ``[]`` if the
            local index file is absent.

        Raises:
            PluginIndexError: If the file exists but cannot be parsed.
        """
        from app.core.config import plugin_index_local_path as _plugin_index_local_path
        index_path = _plugin_index_local_path()

        if not index_path.exists():
            return []

        try:
            with index_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            plugins_raw = data.get("plugins", [])
            return [PluginIndexEntry(**item) for item in plugins_raw]
        except Exception as exc:
            raise PluginIndexError(
                f"Failed to parse local plugin index at '{index_path}': {exc}"
            ) from exc
