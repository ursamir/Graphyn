"""SEC-003: HTTP egress policy (trusted default / restricted SSRF hardening)."""
from __future__ import annotations

import ipaddress
from unittest.mock import patch

import pytest

from app.core.config import http_egress_allowlist, http_egress_mode
from app.core.egress import (
    HttpEgressError,
    host_on_allowlist,
    is_blocked_ip,
    validate_http_egress_url,
)


@pytest.fixture
def trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_MODE", "trusted")
    monkeypatch.delenv("GRAPHYN_HTTP_EGRESS_ALLOWLIST", raising=False)


@pytest.fixture
def restricted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_MODE", "restricted")
    monkeypatch.delenv("GRAPHYN_HTTP_EGRESS_ALLOWLIST", raising=False)


def test_default_mode_is_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRAPHYN_HTTP_EGRESS_MODE", raising=False)
    assert http_egress_mode() == "trusted"


def test_invalid_mode_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_MODE", "maybe")
    with pytest.raises(ValueError, match="invalid"):
        http_egress_mode()


def test_trusted_permits_private_literal(trusted: None) -> None:
    validate_http_egress_url("http://127.0.0.1:8080/admin")
    validate_http_egress_url("http://169.254.169.254/latest/meta-data/")


def test_restricted_blocks_loopback(restricted: None) -> None:
    with pytest.raises(HttpEgressError, match="blocked"):
        validate_http_egress_url("http://127.0.0.1/secret")


def test_restricted_blocks_rfc1918(restricted: None) -> None:
    for url in (
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://172.16.0.1/x",
    ):
        with pytest.raises(HttpEgressError, match="blocked"):
            validate_http_egress_url(url)


def test_restricted_blocks_metadata_ip(restricted: None) -> None:
    with pytest.raises(HttpEgressError, match="blocked"):
        validate_http_egress_url("http://169.254.169.254/latest/meta-data/")


def test_restricted_blocks_metadata_hostname(restricted: None) -> None:
    with pytest.raises(HttpEgressError, match="metadata"):
        validate_http_egress_url("http://metadata.google.internal/computeMetadata/v1/")


def test_restricted_blocks_ipv6_ula_and_link_local(restricted: None) -> None:
    with pytest.raises(HttpEgressError, match="blocked"):
        validate_http_egress_url("http://[fc00::1]/")
    with pytest.raises(HttpEgressError, match="blocked"):
        validate_http_egress_url("http://[fe80::1]/")


def test_restricted_blocks_non_http_scheme(restricted: None) -> None:
    with pytest.raises(HttpEgressError, match="scheme"):
        validate_http_egress_url("file:///etc/passwd")


def test_allowlist_allow_and_deny(restricted: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_ALLOWLIST", "example.com,hooks.example.com")
    assert host_on_allowlist("api.example.com")
    assert host_on_allowlist("hooks.example.com")
    assert not host_on_allowlist("evil.com")

    # Public IP for example.com — mock resolution so CI is offline-safe.
    public = [ipaddress.ip_address("93.184.216.34")]
    with patch("app.core.egress._resolve_ips", return_value=public):
        validate_http_egress_url("https://api.example.com/v1")

    with patch("app.core.egress._resolve_ips", return_value=public):
        with pytest.raises(HttpEgressError, match="ALLOWLIST"):
            validate_http_egress_url("https://evil.com/x")


def test_allowlist_does_not_bypass_private_ip(
    restricted: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_ALLOWLIST", "internal.example.com")
    with patch(
        "app.core.egress._resolve_ips",
        return_value=[ipaddress.ip_address("10.1.2.3")],
    ):
        with pytest.raises(HttpEgressError, match="blocked"):
            validate_http_egress_url("https://internal.example.com/x")


def test_is_blocked_ip_flags() -> None:
    assert is_blocked_ip(ipaddress.ip_address("169.254.169.254"))
    assert is_blocked_ip(ipaddress.ip_address("127.0.0.1"))
    assert is_blocked_ip(ipaddress.ip_address("10.0.0.1"))
    assert not is_blocked_ip(ipaddress.ip_address("8.8.8.8"))


def test_allowlist_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_ALLOWLIST", " A.com , B.org ")
    assert http_egress_allowlist() == ["a.com", "b.org"]
