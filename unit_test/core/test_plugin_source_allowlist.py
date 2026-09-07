"""SEC-001: structural plugin source allowlist matching."""
from __future__ import annotations

import pytest

from app.core.config import plugin_source_is_allowed


REPO = "https://github.com/trusted/repo"
ORG = "https://github.com/myorg/"
HOST = "https://plugins.internal.example.com/"


@pytest.fixture
def allow_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", REPO)


@pytest.fixture
def allow_org(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", ORG)


@pytest.fixture
def allow_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", HOST)


def test_unset_allowlist_allows_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", raising=False)
    assert plugin_source_is_allowed("https://evil.example/x.zip") is True


def test_local_paths_always_allowed(allow_repo: None) -> None:
    assert plugin_source_is_allowed("/tmp/my-plugin") is True
    assert plugin_source_is_allowed("./plugins/local") is True


def test_exact_repository_allowed(allow_repo: None) -> None:
    assert plugin_source_is_allowed(REPO) is True
    assert plugin_source_is_allowed(REPO + ".git") is True
    assert plugin_source_is_allowed("git+https://github.com/trusted/repo.git") is True
    assert plugin_source_is_allowed("git+https://github.com/trusted/repo.git@v1.2.3") is True


def test_valid_archive_under_exact_repository_allowed(allow_repo: None) -> None:
    assert (
        plugin_source_is_allowed(
            "https://github.com/trusted/repo/archive/refs/heads/main.zip"
        )
        is True
    )
    assert (
        plugin_source_is_allowed(
            "https://github.com/trusted/repo/archive/main.tar.gz"
        )
        is True
    )
    # GitHub CDN / raw shapes under the same owner/repo
    assert (
        plugin_source_is_allowed(
            "https://codeload.github.com/trusted/repo/zip/refs/heads/main"
        )
        is True
    )
    assert (
        plugin_source_is_allowed(
            "https://raw.githubusercontent.com/trusted/repo/main/plugin.toml"
        )
        is True
    )


def test_gitlab_archive_under_exact_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "GRAPHYN_PLUGIN_ALLOWED_SOURCES",
        "https://gitlab.com/trusted/repo",
    )
    assert (
        plugin_source_is_allowed(
            "https://gitlab.com/trusted/repo/-/archive/main/repo-main.zip"
        )
        is True
    )
    assert (
        plugin_source_is_allowed(
            "https://gitlab.com/trusted/repo-evil/-/archive/main/x.zip"
        )
        is False
    )


def test_similarly_prefixed_repository_rejected(allow_repo: None) -> None:
    assert plugin_source_is_allowed("https://github.com/trusted/repo-evil") is False
    assert (
        plugin_source_is_allowed(
            "https://github.com/trusted/repo-evil/archive/main.zip"
        )
        is False
    )
    assert plugin_source_is_allowed("https://github.com/trusted/repo2") is False
    assert (
        plugin_source_is_allowed("https://github.com/trusted/repo2/plugin.zip")
        is False
    )
    # Classic startswith false-positive that SEC-001 closes
    assert "https://github.com/trusted/repo-evil".startswith(REPO)
    assert plugin_source_is_allowed("https://github.com/trusted/repo-evil") is False


def test_org_allowlist_uses_segment_boundary(allow_org: None) -> None:
    assert plugin_source_is_allowed("https://github.com/myorg/cool-plugin") is True
    assert plugin_source_is_allowed("git+https://github.com/myorg/cool-plugin.git") is True
    assert plugin_source_is_allowed("https://github.com/myorg-evil/x") is False
    assert plugin_source_is_allowed("https://github.com/myorg2/x") is False


def test_host_root_allowlist(allow_host: None) -> None:
    assert plugin_source_is_allowed("https://plugins.internal.example.com/a.zip") is True
    assert plugin_source_is_allowed("https://plugins.internal.example.com/") is True


def test_malicious_host_rejected(allow_repo: None) -> None:
    assert plugin_source_is_allowed("https://evil.example/trusted/repo") is False
    assert plugin_source_is_allowed("https://github.com.evil.com/trusted/repo") is False
    assert plugin_source_is_allowed("https://github.com@evil.com/trusted/repo") is False
    assert plugin_source_is_allowed("https://evil.com/https://github.com/trusted/repo") is False
    assert (
        plugin_source_is_allowed("https://raw.githubusercontent.com.evil/trusted/repo/x")
        is False
    )


def test_path_traversal_rejected(allow_repo: None) -> None:
    assert (
        plugin_source_is_allowed("https://github.com/trusted/repo/../repo-evil/x")
        is False
    )
    assert (
        plugin_source_is_allowed(
            "https://github.com/trusted/repo/%2e%2e/repo-evil/x"
        )
        is False
    )
    assert (
        plugin_source_is_allowed(
            "https://github.com/trusted/repo/%2E%2E/%2E%2E/etc/passwd"
        )
        is False
    )
    assert (
        plugin_source_is_allowed("https://github.com/trusted/%2e%2e/other/x")
        is False
    )


def test_scheme_mismatch_rejected(allow_repo: None) -> None:
    assert plugin_source_is_allowed("http://github.com/trusted/repo") is False


def test_redirect_policy_documented_and_revalidated_elsewhere() -> None:
    """Redirect hops are re-checked fail-closed in installer/index (not here).

    See ``PluginInstaller._download_with_limit`` and
    ``PluginIndexClient`` fetch path: every hop + final URL call
    ``plugin_source_is_allowed``. Covered by
    ``test_allowlist_applies_to_redirect_target`` in
    ``unit_test/core/plugins/test_dep_isolation.py``.
    """
    assert "Redirect policy" in (plugin_source_is_allowed.__doc__ or "")
