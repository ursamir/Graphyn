"""OIDC helpers: PKCE/state tickets, claim mapping, ID-token verify, user upsert."""
from __future__ import annotations

import base64
import hashlib
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.trust import oidc as oidc_mod
from app.core.trust.oidc import (
    OidcError,
    begin_login,
    claims_to_profile,
    clear_oidc_caches,
    finish_callback,
    oidc_config,
    password_login_allowed,
    redeem_ticket,
    sanitize_username,
    verify_id_token,
)
from app.core.trust.users import get_user_store, reset_user_store


@pytest.fixture(autouse=True)
def _oidc_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("GRAPHYN_OIDC_STATE_DB", str(tmp_path / "oidc_state.db"))
    monkeypatch.setenv("GRAPHYN_OIDC_ENABLED", "1")
    monkeypatch.setenv("GRAPHYN_OIDC_ISSUER", "https://idp.example.test")
    monkeypatch.setenv("GRAPHYN_OIDC_CLIENT_ID", "graphyn-console")
    monkeypatch.setenv("GRAPHYN_OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GRAPHYN_OIDC_REDIRECT_URI", "http://localhost:5173/api/v1/auth/oidc/callback")
    monkeypatch.setenv("GRAPHYN_OIDC_UI_ORIGIN", "http://localhost:5173")
    monkeypatch.setenv("GRAPHYN_OIDC_AUTO_PROVISION", "1")
    monkeypatch.setenv("GRAPHYN_OIDC_DEFAULT_ROLES", "viewer")
    monkeypatch.setenv("GRAPHYN_OIDC_PASSWORD_LOGIN", "1")
    monkeypatch.delenv("GRAPHYN_LEGACY_TOKEN_DISABLED", raising=False)
    reset_user_store()
    clear_oidc_caches()
    yield
    reset_user_store()
    clear_oidc_caches()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_rsa():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    def _int(val: int) -> str:
        length = (val.bit_length() + 7) // 8
        return _b64url(val.to_bytes(length, "big"))
    jwk = {"kty": "RSA", "kid": "k1", "alg": "RS256", "use": "sig", "n": _int(pub.n), "e": _int(pub.e)}
    return key, {"keys": [jwk]}


def _sign_jwt(private_key, claims: dict, kid: str = "k1") -> str:
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT", "kid": kid}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64url(sig)}"


def test_sanitize_and_claims():
    assert sanitize_username("Alice.Smith") == "alice.smith"
    assert sanitize_username("bob@corp.example") == "bob"
    cfg = oidc_config()
    prof = claims_to_profile(
        {"sub": "s1", "preferred_username": "Ann!", "name": "Ann Example", "email": "ann@ex.test"},
        cfg,
    )
    assert prof["username"] == "ann" and prof["email"] == "ann@ex.test" and prof["sub"] == "s1"


def test_password_login_flag(monkeypatch):
    assert password_login_allowed() is True
    monkeypatch.setenv("GRAPHYN_OIDC_PASSWORD_LOGIN", "0")
    assert password_login_allowed() is False
    monkeypatch.setenv("GRAPHYN_OIDC_ENABLED", "0")
    assert password_login_allowed() is True


def test_verify_id_token_happy_and_bad_aud():
    key, jwks = _make_rsa()
    now = int(time.time())
    claims = {
        "iss": "https://idp.example.test",
        "sub": "sub-1",
        "aud": "graphyn-console",
        "exp": now + 300,
        "iat": now,
        "nonce": "n1",
    }
    tok = _sign_jwt(key, claims)
    got = verify_id_token(
        tok,
        jwks=jwks,
        issuer="https://idp.example.test",
        audience="graphyn-console",
        nonce="n1",
        client_id="graphyn-console",
    )
    assert got["sub"] == "sub-1"
    bad = _sign_jwt(key, {**claims, "aud": "other"})
    with pytest.raises(OidcError):
        verify_id_token(
            bad,
            jwks=jwks,
            issuer="https://idp.example.test",
            audience="graphyn-console",
            nonce="n1",
            client_id="graphyn-console",
        )


def test_begin_login_stores_pkce(monkeypatch):
    monkeypatch.setattr(
        oidc_mod,
        "discover",
        lambda issuer: {
            "authorization_endpoint": "https://idp.example.test/auth",
            "token_endpoint": "https://idp.example.test/token",
            "jwks_uri": "https://idp.example.test/jwks",
        },
    )
    started = begin_login(return_to="/projects/alpha", request_base="http://localhost:5173")
    assert "code_challenge=" in started["authorize_url"] and "code_challenge_method=S256" in started["authorize_url"]
    assert started["state"] and started["return_to"] == "/projects/alpha"


def test_finish_callback_provisions_admin_first(monkeypatch):
    key, jwks = _make_rsa()
    now = int(time.time())

    monkeypatch.setattr(
        oidc_mod,
        "discover",
        lambda issuer: {
            "authorization_endpoint": "https://idp.example.test/auth",
            "token_endpoint": "https://idp.example.test/token",
            "jwks_uri": "https://idp.example.test/jwks",
            "userinfo_endpoint": "https://idp.example.test/userinfo",
        },
    )
    monkeypatch.setattr(oidc_mod, "_fetch_jwks", lambda uri: jwks)

    started = begin_login(return_to="/", request_base="http://localhost:5173")
    # Pull nonce/verifier via redeem path internals: finish will load state.
    # Build token response with matching nonce from DB.
    import sqlite3

    row = sqlite3.connect(str(oidc_mod._store_path())).execute(
        "SELECT nonce, state FROM oidc_states WHERE state=?", (started["state"],)
    ).fetchone()
    nonce = row[0]
    claims = {
        "iss": "https://idp.example.test",
        "sub": "first-user",
        "aud": "graphyn-console",
        "exp": now + 300,
        "iat": now,
        "nonce": nonce,
        "preferred_username": "root.sso",
        "name": "Root SSO",
        "email": "root@ex.test",
    }
    id_token = _sign_jwt(key, claims)

    def fake_post(url, data, auth=None):
        assert data["code"] == "auth-code"
        assert data["code_verifier"]
        return {"id_token": id_token, "access_token": "atk"}

    monkeypatch.setattr(oidc_mod, "_http_post_form", fake_post)
    monkeypatch.setattr(oidc_mod, "_userinfo", lambda doc, at: {})

    done = finish_callback(code="auth-code", state=started["state"])
    assert done["ticket"] and done["user"]["username"] == "root.sso"
    assert done["user"]["roles"] == ["admin"]  # first user bootstrap
    assert "oidc_ticket=" in done["complete_url"]

    payload = redeem_ticket(done["ticket"])
    assert payload["token"].startswith("gxs_")
    store = get_user_store()
    assert store.resolve_token(payload["token"])[1].username == "root.sso"
    with pytest.raises(OidcError):
        redeem_ticket(done["ticket"])  # one-time


def test_upsert_links_existing_local_user():
    store = get_user_store()
    local = store.create_user("jane", "correct-horse-1", roles=["builder"])
    user = store.upsert_oidc_user(
        issuer="https://idp.example.test",
        sub="idp-jane",
        username="jane",
        display_name="Jane Doe",
        email="jane@ex.test",
        default_roles=("viewer",),
        auto_provision=True,
    )
    assert user.id == local.id and user.oidc_sub == "idp-jane" and user.has_password
