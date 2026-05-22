# unit_test/core/plugins/test_index.py
"""Tests for PluginIndexClient (Req 6, Req 16 criterion 5)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.plugins.index import PluginIndexClient, PluginIndexEntry
from app.core.plugins.errors import PluginIndexError, PluginNotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_ENTRY = {
    "name": "audio-denoiser",
    "version": "1.0.0",
    "description": "Removes background noise from audio.",
    "author": "Graphyn",
    "tags": ["audio", "denoising"],
    "platform_version": ">=0.0",
    "download_url": "https://example.com/audio-denoiser-1.0.0.zip",
    "homepage": None,
    "checksum": None,
}

SAMPLE_INDEX = {"plugins": [SAMPLE_ENTRY]}


def _make_client() -> PluginIndexClient:
    """Return a fresh PluginIndexClient with cleared cache."""
    PluginIndexClient._cache = None
    return PluginIndexClient()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_remote_fetch_calls_httpx_get() -> None:
    """Remote fetch calls httpx.get with the configured URL."""
    client = _make_client()

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = SAMPLE_INDEX

    with (
        patch("app.core.plugins.index.httpx.get", return_value=mock_response) as mock_get,
        patch(
            "app.core.plugins.index.PluginIndexClient._fetch_remote",
            wraps=client._fetch_remote,
        ),
        patch(
            "app.core.config.plugin_index_url",
            return_value="https://example.com/index.json",
        ),
    ):
        PluginIndexClient._cache = None
        entries = client._fetch_remote("https://example.com/index.json")

    mock_get.assert_called_once_with("https://example.com/index.json", timeout=10)
    assert len(entries) == 1
    assert entries[0].name == "audio-denoiser"


def test_http_error_raises_plugin_index_error() -> None:
    """HTTP error response raises PluginIndexError."""
    client = _make_client()

    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 404

    with patch("app.core.plugins.index.httpx.get", return_value=mock_response):
        with pytest.raises(PluginIndexError):
            client._fetch_remote("https://example.com/index.json")


def test_network_error_raises_plugin_index_error() -> None:
    """Network exception raises PluginIndexError."""
    import httpx as _httpx

    client = _make_client()

    with patch(
        "app.core.plugins.index.httpx.get",
        side_effect=_httpx.RequestError("connection refused"),
    ):
        with pytest.raises(PluginIndexError):
            client._fetch_remote("https://example.com/index.json")


def test_local_fetch_reads_file(tmp_path: Path) -> None:
    """Local fetch reads the index.json file."""
    index_file = tmp_path / "index.json"
    index_file.write_text(json.dumps(SAMPLE_INDEX), encoding="utf-8")

    client = _make_client()

    with patch(
        "app.core.config.plugin_index_local_path",
        return_value=index_file,
    ):
        entries = client._fetch_local()

    assert len(entries) == 1
    assert entries[0].name == "audio-denoiser"


def test_local_fetch_missing_file_returns_empty(tmp_path: Path) -> None:
    """Local fetch returns [] when index.json does not exist."""
    missing = tmp_path / "nonexistent_index.json"
    client = _make_client()

    with patch(
        "app.core.config.plugin_index_local_path",
        return_value=missing,
    ):
        entries = client._fetch_local()

    assert entries == []


def test_no_source_returns_empty() -> None:
    """fetch() returns [] when no URL and no local file."""
    client = _make_client()

    with (
        patch("app.core.config.plugin_index_url", return_value=""),
        patch(
            "app.core.config.plugin_index_local_path",
            return_value=Path("/nonexistent/path/index.json"),
        ),
    ):
        entries = client.fetch()

    assert entries == []


def test_caching_returns_same_list() -> None:
    """fetch() returns the cached list on second call without re-fetching."""
    client = _make_client()

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = SAMPLE_INDEX

    with (
        patch("app.core.plugins.index.httpx.get", return_value=mock_response) as mock_get,
        patch(
            "app.core.config.plugin_index_url",
            return_value="https://example.com/index.json",
        ),
    ):
        first = client.fetch()
        second = client.fetch()

    # httpx.get should only be called once (second call uses cache)
    assert mock_get.call_count == 1
    assert first is second


def test_search_by_name() -> None:
    """search() finds entries matching the query in name."""
    client = _make_client()
    PluginIndexClient._cache = [PluginIndexEntry(**SAMPLE_ENTRY)]

    results = client.search("audio-denoiser")
    assert len(results) == 1
    assert results[0].name == "audio-denoiser"


def test_search_by_description() -> None:
    """search() finds entries matching the query in description."""
    client = _make_client()
    PluginIndexClient._cache = [PluginIndexEntry(**SAMPLE_ENTRY)]

    results = client.search("background noise")
    assert len(results) == 1


def test_search_by_tag() -> None:
    """search() finds entries matching the query in tags."""
    client = _make_client()
    PluginIndexClient._cache = [PluginIndexEntry(**SAMPLE_ENTRY)]

    results = client.search("denoising")
    assert len(results) == 1


def test_search_no_match_returns_empty() -> None:
    """search() returns [] when no entries match."""
    client = _make_client()
    PluginIndexClient._cache = [PluginIndexEntry(**SAMPLE_ENTRY)]

    results = client.search("zzz-no-match-xyz")
    assert results == []


def test_search_empty_query_returns_all() -> None:
    """search('') returns all entries."""
    client = _make_client()
    PluginIndexClient._cache = [PluginIndexEntry(**SAMPLE_ENTRY)]

    results = client.search("")
    assert len(results) == 1


def test_lookup_by_name() -> None:
    """lookup() returns the entry matching the name."""
    client = _make_client()
    PluginIndexClient._cache = [PluginIndexEntry(**SAMPLE_ENTRY)]

    entry = client.lookup("audio-denoiser")
    assert entry.name == "audio-denoiser"
    assert entry.version == "1.0.0"


def test_lookup_by_name_and_version() -> None:
    """lookup(name, version) returns the entry matching name and version."""
    entry_v2 = {**SAMPLE_ENTRY, "version": "2.0.0"}
    client = _make_client()
    PluginIndexClient._cache = [
        PluginIndexEntry(**SAMPLE_ENTRY),
        PluginIndexEntry(**entry_v2),
    ]

    result = client.lookup("audio-denoiser", version="2.0.0")
    assert result.version == "2.0.0"


def test_lookup_unknown_name_raises() -> None:
    """lookup() raises PluginNotFoundError for unknown plugin name."""
    client = _make_client()
    PluginIndexClient._cache = [PluginIndexEntry(**SAMPLE_ENTRY)]

    with pytest.raises(PluginNotFoundError):
        client.lookup("nonexistent-plugin")


def test_lookup_unknown_version_raises() -> None:
    """lookup(name, version) raises PluginNotFoundError for unknown version."""
    client = _make_client()
    PluginIndexClient._cache = [PluginIndexEntry(**SAMPLE_ENTRY)]

    with pytest.raises(PluginNotFoundError):
        client.lookup("audio-denoiser", version="99.0.0")


def test_lookup_returns_latest_when_no_version() -> None:
    """lookup(name) returns the highest version when version is None."""
    entry_v2 = {**SAMPLE_ENTRY, "version": "2.0.0"}
    entry_v1 = {**SAMPLE_ENTRY, "version": "1.0.0"}
    client = _make_client()
    PluginIndexClient._cache = [
        PluginIndexEntry(**entry_v1),
        PluginIndexEntry(**entry_v2),
    ]

    result = client.lookup("audio-denoiser")
    assert result.version == "2.0.0"
