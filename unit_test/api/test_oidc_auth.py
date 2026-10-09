"""API: OIDC public routes + password fallback + auth-status fields."""
from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.trust import oidc as oidc_mod
from app.core.trust.oidc import clear_oidc_caches
from app.core.trust.users import get_user_store, reset_user_store


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    yield


@pytest.fixture
def oidc_api(tmp_path, monkeypatch, api_client):
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("GRAPHYN_OIDC_STATE_DB", str(tmp_path / "oidc_state.db"))
    monkeypatch.setenv("GRAPHYN_OIDC_ENABLED", "1")
    monkeypatch.setenv("GRAPHYN_OIDC_ISSUER", "https://idp.example.test")
    monkeypatch.setenv("GRAPHYN_OIDC_CLIENT_ID", "graphyn-console")
    monkeypatch.setenv("GRAPHYN_OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GRAPHYN_OIDC_REDIRECT_URI", "http://testserver/api/v1/auth/oidc/callback")
    monkeypatch.setenv("GRAPHYN_OIDC_UI_ORIGIN", "http://ui.test")
    monkeypatch.setenv("GRAPHYN_OIDC_PASSWORD_LOGIN", "1")
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_LEGACY_TOKEN_DISABLED", raising=False)
    reset_user_store()
    clear_oidc_caches()
    from app.api.routers import auth as auth_router
    with auth_router._fail_lock:
        auth_router._failures.clear()
    monkeypatch.setattr(
        oidc_mod,
        "discover",
        lambda issuer: {
            "authorization_endpoint": "https://idp.example.test/auth",
            "token_endpoint": "https://idp.example.test/token",
            "jwks_uri": "https://idp.example.test/jwks",
        },
    )
    yield api_client
    reset_user_store()
    clear_oidc_caches()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _rsa_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()

    def _int(val: int) -> str:
        length = (val.bit_length() + 7) // 8
        return _b64url(val.to_bytes(length, "big"))

    jwks = {"keys": [{"kty": "RSA", "kid": "k1", "alg": "RS256", "n": _int(pub.n), "e": _int(pub.e)}]}
    return key, jwks


def _jwt(key, claims):
    header = _b64url(json.dumps({"alg": "RS256", "kid": "k1"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    sig = key.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64url(sig)}"


def test_auth_status_reports_oidc(oidc_api):
    r = oidc_api.get("/api/v1/system/auth-status")
    assert r.status_code == 200
    body = r.json()
    assert body["oidc_enabled"] is True and body["password_login"] is True
    assert body["oidc"]["client_id"] == "graphyn-console"


def test_oidc_start_json_and_callback_finish(oidc_api, monkeypatch):
    key, jwks = _rsa_pair()
    monkeypatch.setattr(oidc_mod, "_fetch_jwks", lambda uri: jwks)
    start = oidc_api.get("/api/v1/auth/oidc/start", params={"returnTo": "/runs", "format": "json"})
    assert start.status_code == 200
    data = start.json()
    assert "authorize_url" in data and data["state"]

    import sqlite3

    nonce = sqlite3.connect(str(oidc_mod._store_path())).execute(
        "SELECT nonce FROM oidc_states WHERE state=?", (data["state"],)
    ).fetchone()[0]
    now = int(time.time())
    id_token = _jwt(
        key,
        {
            "iss": "https://idp.example.test",
            "sub": "s-42",
            "aud": "graphyn-console",
            "exp": now + 300,
            "iat": now,
            "nonce": nonce,
            "preferred_username": "samir",
            "name": "Samir",
            "email": "samir@ex.test",
        },
    )
    monkeypatch.setattr(oidc_mod, "_http_post_form", lambda *a, **k: {"id_token": id_token, "access_token": "x"})
    monkeypatch.setattr(oidc_mod, "_userinfo", lambda *a, **k: {})

    cb = oidc_api.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "c1", "state": data["state"]},
        follow_redirects=False,
    )
    assert cb.status_code == 302
    loc = cb.headers["location"]
    assert loc.startswith("http://ui.test/login?") and "oidc_ticket=" in loc
    from urllib.parse import parse_qs, urlparse

    ticket = parse_qs(urlparse(loc).query)["oidc_ticket"][0]
    fin = oidc_api.post("/api/v1/auth/oidc/finish", json={"ticket": ticket})
    assert fin.status_code == 200, fin.text
    body = fin.json()
    assert body["token"].startswith("gxs_") and body["user"]["username"] == "samir"
    me = oidc_api.get("/api/v1/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200 and me.json()["kind"] == "user" and me.json()["roles"] == ["admin"]


def test_password_login_disabled_when_flag_off(oidc_api, monkeypatch):
    store = get_user_store()
    store.create_user("alice", "correct-horse-1", roles=["builder"])
    monkeypatch.setenv("GRAPHYN_OIDC_PASSWORD_LOGIN", "0")
    r = oidc_api.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse-1"})
    assert r.status_code == 403


def test_password_fallback_still_works(oidc_api):
    store = get_user_store()
    store.create_user("alice", "correct-horse-1", roles=["builder"])
    r = oidc_api.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse-1"})
    assert r.status_code == 200 and r.json()["token"].startswith("gxs_")
