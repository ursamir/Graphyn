"""SEC-P0: plugin source allowlist must not be skipped by scheme tricks."""
from __future__ import annotations

import pytest

from app.core.config import plugin_source_is_allowed
from app.core.plugins.errors import PluginInstallError
from app.core.plugins.installer import PluginInstaller, redact_url_userinfo


REPO = "https://github.com/trusted/repo"


@pytest.fixture
def allow_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", REPO)
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("GRAPHYN_ENV", "development")


@pytest.mark.parametrize(
    "evil",
    [
        "git://evil.example/repo.git",
        "ssh://git@evil.example/repo.git",
        "SSH://git@evil.example/repo.git",
        "HTTPS://evil.example/x.zip",
        "HTTP://evil.example/x.zip",
        "GIT+https://evil.example/repo.git",
        "Git+HTTPS://evil.example/repo.git",
        "file:///etc/passwd",
    ],
)
def test_bypass_schemes_denied_when_allowlist_set(allow_repo: None, evil: str) -> None:
    assert plugin_source_is_allowed(evil) is False


@pytest.mark.parametrize(
    "ok",
    [
        "HTTPS://github.com/trusted/repo",
        "https://github.com/trusted/repo.git",
        "GIT+https://github.com/trusted/repo.git",
        "Git+HTTPS://github.com/trusted/repo.git@v1",
    ],
)
def test_mixed_case_allowed_schemes_still_match(allow_repo: None, ok: str) -> None:
    assert plugin_source_is_allowed(ok) is True


def test_installer_rejects_ssh_before_clone(allow_repo: None) -> None:
    inst = PluginInstaller()
    with pytest.raises(PluginInstallError, match="Unsupported plugin source scheme|not in the allowed"):
        inst.resolve("ssh://git@evil.example/repo.git")


def test_installer_rejects_mixed_case_https_off_allowlist(allow_repo: None) -> None:
    inst = PluginInstaller()
    with pytest.raises(PluginInstallError, match="not in the allowed"):
        inst.resolve("HTTPS://evil.example/plugin.zip")


def test_installer_rejects_git_scheme_off_allowlist(allow_repo: None) -> None:
    inst = PluginInstaller()
    with pytest.raises(PluginInstallError, match="not in the allowed|Unsupported"):
        inst.resolve("git://evil.example/repo.git")


def test_redact_url_userinfo_strips_credentials() -> None:
    raw = "https://user:TOKEN@github.com/org/repo.git"
    out = redact_url_userinfo(raw)
    assert "TOKEN" not in out
    assert "user:" not in out
    assert out.startswith("https://***@github.com/")
    assert redact_url_userinfo("git+https://u:p@host/r.git") == "git+https://***@host/r.git"
    assert "TOKEN" not in redact_url_userinfo(f"Git clone failed for {raw!r}")


def test_install_error_messages_redact_credentials(allow_repo: None) -> None:
    inst = PluginInstaller()
    evil = "https://user:s3cretTOKEN@evil.example/plugin.zip"
    with pytest.raises(PluginInstallError) as ei:
        inst.resolve(evil)
    msg = str(ei.value)
    assert "s3cretTOKEN" not in msg
    assert "user:s3cret" not in msg
