"""``http_auth`` credential kind (bearer | basic | header) — validation + redaction."""
from __future__ import annotations

import pytest

from app.core.credentials import (
    CredentialError,
    NeedsCredentialsError,
    create_connection,
    get_payload,
    list_connections,
    list_kinds,
    resolve_connection,
)
from app.core.credentials.kinds import redact_payload, secret_field_names, validate_payload


@pytest.fixture
def cred_home(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "ghome"))
    monkeypatch.delenv("GRAPHYN_CREDENTIALS_KEY", raising=False)
    return tmp_path


def test_kind_registered_with_secret_fields():
    assert "http_auth" in {k.id for k in list_kinds()}
    secrets = secret_field_names("http_auth")
    assert {"token", "password", "header_value"} <= secrets
    assert "username" not in secrets and "header_name" not in secrets


@pytest.mark.parametrize(
    "payload",
    [
        {"scheme": "bearer", "token": "t"},
        {"scheme": "basic", "username": "u", "password": "p"},
        {"scheme": "HEADER", "header_name": "X-API-Key", "header_value": "v"},
    ],
)
def test_valid_payloads(payload):
    cleaned = validate_payload("http_auth", payload)
    assert cleaned["scheme"] == payload["scheme"].lower()


@pytest.mark.parametrize(
    "payload,match",
    [
        ({"scheme": "oauth", "token": "t"}, "scheme"),
        ({"scheme": "bearer"}, "token"),
        ({"scheme": "basic", "username": "u"}, "password"),
        ({"scheme": "header", "header_name": "X-Key"}, "header_value"),
        ({"scheme": "header", "header_name": "X Key\r\nEvil: 1", "header_value": "v"}, "header token"),
        ({"scheme": "bearer", "token": "t", "nope": 1}, "Unknown field"),
    ],
)
def test_invalid_payloads(payload, match):
    with pytest.raises(CredentialError, match=match):
        validate_payload("http_auth", payload)


def test_partial_update_checks_scheme_only():
    assert validate_payload("http_auth", {"token": "new"}, partial=True) == {"token": "new"}
    with pytest.raises(CredentialError):
        validate_payload("http_auth", {"scheme": "nope"}, partial=True)


def test_redaction_never_echoes_secrets():
    red = redact_payload("http_auth", {"scheme": "header", "header_name": "X-Key",
                                       "header_value": "SECRETV", "token": "", "password": "PW"})
    assert red == {"scheme": "header", "header_name": "X-Key", "header_value": "***",
                   "token": "", "password": "***"}


def test_store_roundtrip_and_explicit_resolve(cred_home):
    meta = create_connection(name="gh", kind="http_auth",
                             payload={"scheme": "bearer", "token": "ghp_SECRET", "allowed_hosts": "api.github.com"})
    assert meta["fields"]["token"] == "***"
    assert "ghp_SECRET" not in str(list_connections())
    kind, payload = get_payload(meta["id"])
    assert kind == "http_auth" and payload["token"] == "ghp_SECRET"
    res = resolve_connection(kind="http_auth", connection_id=meta["id"])
    assert res["source"] == "connection"


def test_no_env_fallback_for_http_auth(cred_home):
    with pytest.raises(NeedsCredentialsError):
        resolve_connection(kind="http_auth")
