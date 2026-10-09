# app/core/trust/oidc.py
"""
Bounded Context:  BC6 — Observability & Storage (identity / access)
Responsibility:   Optional OpenID Connect (OIDC) login for humans. Discovery,
                  authorization-code + PKCE, callback token exchange, ID-token
                  JWKS verification (RS256/ES256) with userinfo fallback, and
                  short-lived one-time tickets so the console can pick up the
                  same session credential shape as password login.
Owns:             OidcConfig, OidcError, oidc_config(), oidc_enabled(),
                  password_login_allowed(), public_status(), begin_login(),
                  finish_callback(), redeem_ticket(), clear_oidc_caches().
Public Surface:   The functions above (used by app.api.routers.auth).
Must NOT:         Import app.api / app.domain / execution; log client secrets,
                  authorization codes, tokens, or PKCE verifiers.
Dependencies:     stdlib, httpx, cryptography, app.core.trust.users (lazy).
Reason To Change: IdP flow, claim mapping, or ticket/session policy changes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_STATE_TTL_S = 600.0
_TICKET_TTL_S = 120.0
_DISCOVERY_TTL_S = 3600.0
_JWKS_TTL_S = 3600.0
_HTTP_TIMEOUT_S = 15.0

_USERNAME_SANITIZE = re.compile(r"[^a-z0-9._-]+")


class OidcError(Exception):
    """User-facing OIDC failure with an HTTP-ish status code."""

    def __init__(self, message: str, status_code: int = 400, code: str = "oidc_error") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class OidcConfig:
    enabled: bool
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: str
    auto_provision: bool
    default_roles: tuple[str, ...]
    password_login: bool
    ui_origin: str
    username_claim: str
    display_name_claim: str
    email_claim: str
    audience: str

    def public(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "issuer": self.issuer or None,
            "client_id": self.client_id or None,
            "scopes": self.scopes,
            "auto_provision": self.auto_provision,
            "password_login": self.password_login,
            "redirect_uri_configured": bool(self.redirect_uri),
            "ui_origin": self.ui_origin or None,
        }


def _truthy(raw: str | None, default: bool = False) -> bool:
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _csv_roles(raw: str | None) -> tuple[str, ...]:
    from app.core.trust.users import ROLE_NAMES

    out: list[str] = []
    for part in (raw or "viewer").split(","):
        s = part.strip().lower()
        if s and s in ROLE_NAMES and s not in out:
            out.append(s)
    return tuple(out) or ("viewer",)


def oidc_config() -> OidcConfig:
    issuer = (os.environ.get("GRAPHYN_OIDC_ISSUER") or "").strip().rstrip("/")
    client_id = (os.environ.get("GRAPHYN_OIDC_CLIENT_ID") or "").strip()
    enabled = _truthy(os.environ.get("GRAPHYN_OIDC_ENABLED"), False) and bool(issuer and client_id)
    return OidcConfig(
        enabled=enabled,
        issuer=issuer,
        client_id=client_id,
        client_secret=(os.environ.get("GRAPHYN_OIDC_CLIENT_SECRET") or "").strip(),
        redirect_uri=(os.environ.get("GRAPHYN_OIDC_REDIRECT_URI") or "").strip(),
        scopes=(os.environ.get("GRAPHYN_OIDC_SCOPES") or "openid profile email").strip(),
        auto_provision=_truthy(os.environ.get("GRAPHYN_OIDC_AUTO_PROVISION"), True),
        default_roles=_csv_roles(os.environ.get("GRAPHYN_OIDC_DEFAULT_ROLES")),
        password_login=_truthy(os.environ.get("GRAPHYN_OIDC_PASSWORD_LOGIN"), True),
        ui_origin=(os.environ.get("GRAPHYN_OIDC_UI_ORIGIN") or "").strip().rstrip("/"),
        username_claim=(os.environ.get("GRAPHYN_OIDC_USERNAME_CLAIM") or "preferred_username").strip(),
        display_name_claim=(os.environ.get("GRAPHYN_OIDC_DISPLAY_NAME_CLAIM") or "name").strip(),
        email_claim=(os.environ.get("GRAPHYN_OIDC_EMAIL_CLAIM") or "email").strip(),
        audience=(os.environ.get("GRAPHYN_OIDC_AUDIENCE") or client_id).strip(),
    )


def oidc_enabled() -> bool:
    return oidc_config().enabled


def password_login_allowed() -> bool:
    cfg = oidc_config()
    if not cfg.enabled:
        return True
    return cfg.password_login


def public_status() -> dict[str, Any]:
    cfg = oidc_config()
    return {
        "oidc_enabled": cfg.enabled,
        "oidc": cfg.public(),
        "password_login": password_login_allowed(),
    }


# ── durable state / tickets ────────────────────────────────────────────────────


def _store_path() -> Path:
    override = (os.environ.get("GRAPHYN_OIDC_STATE_DB") or "").strip()
    if override:
        return Path(override).expanduser()
    try:
        from app.core.config import graphyn_home

        root = graphyn_home()
    except Exception:
        root = Path(os.environ.get("GRAPHYN_HOME") or (Path.home() / ".graphyn"))
    return Path(root) / "auth" / "oidc_state.db"


_DB_LOCK = threading.RLock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS oidc_states (
  state TEXT PRIMARY KEY,
  code_verifier TEXT NOT NULL,
  nonce TEXT NOT NULL,
  return_to TEXT NOT NULL DEFAULT '/',
  redirect_uri TEXT NOT NULL,
  created_at REAL NOT NULL,
  consumed_at REAL
);
CREATE TABLE IF NOT EXISTS oidc_tickets (
  ticket TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  consumed_at REAL
);
"""


def _conn() -> sqlite3.Connection:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    c = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=10000")
    c.executescript(_SCHEMA)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return c


def _purge(c: sqlite3.Connection) -> None:
    now = time.time()
    c.execute("DELETE FROM oidc_states WHERE created_at < ? OR consumed_at IS NOT NULL", (now - _STATE_TTL_S,))
    c.execute("DELETE FROM oidc_tickets WHERE expires_at < ? OR consumed_at IS NOT NULL", (now,))


def clear_oidc_caches() -> None:
    """Test helper: drop discovery/JWKS memory caches and state DB rows."""
    with _cache_lock:
        _discovery_cache.clear()
        _jwks_cache.clear()
    with _DB_LOCK, _conn() as c:
        c.execute("DELETE FROM oidc_states")
        c.execute("DELETE FROM oidc_tickets")


# ── discovery / JWKS ───────────────────────────────────────────────────────────

_cache_lock = threading.Lock()
_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _http_get_json(url: str) -> dict[str, Any]:
    import httpx

    with httpx.Client(timeout=_HTTP_TIMEOUT_S, follow_redirects=True) as client:
        r = client.get(url, headers={"Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, dict):
        raise OidcError("OIDC discovery returned a non-object document", 502, "oidc_discovery")
    return data


def _http_post_form(url: str, data: dict[str, str], *, auth: tuple[str, str] | None = None) -> dict[str, Any]:
    import httpx

    with httpx.Client(timeout=_HTTP_TIMEOUT_S, follow_redirects=True) as client:
        r = client.post(url, data=data, auth=auth, headers={"Accept": "application/json"})
        try:
            body = r.json()
        except Exception:
            body = {"error": "invalid_response", "error_description": r.text[:300]}
        if r.status_code >= 400:
            desc = body.get("error_description") or body.get("error") or r.text[:200]
            raise OidcError(f"Token endpoint refused the code ({desc})", 401, "oidc_token")
        if not isinstance(body, dict):
            raise OidcError("Token endpoint returned a non-object", 502, "oidc_token")
        return body


def discover(issuer: str) -> dict[str, Any]:
    iss = issuer.rstrip("/")
    now = time.time()
    with _cache_lock:
        hit = _discovery_cache.get(iss)
        if hit and now - hit[0] < _DISCOVERY_TTL_S:
            return hit[1]
    url = f"{iss}/.well-known/openid-configuration"
    try:
        doc = _http_get_json(url)
    except Exception as exc:
        raise OidcError(f"OIDC discovery failed for issuer: {exc}", 502, "oidc_discovery") from exc
    if not doc.get("authorization_endpoint") or not doc.get("token_endpoint"):
        raise OidcError("OIDC discovery document missing authorization/token endpoints", 502, "oidc_discovery")
    with _cache_lock:
        _discovery_cache[iss] = (now, doc)
    return doc


def _fetch_jwks(uri: str) -> dict[str, Any]:
    now = time.time()
    with _cache_lock:
        hit = _jwks_cache.get(uri)
        if hit and now - hit[0] < _JWKS_TTL_S:
            return hit[1]
    try:
        doc = _http_get_json(uri)
    except Exception as exc:
        raise OidcError(f"JWKS fetch failed: {exc}", 502, "oidc_jwks") from exc
    with _cache_lock:
        _jwks_cache[uri] = (now, doc)
    return doc


# ── PKCE / JWT helpers ─────────────────────────────────────────────────────────


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_json(data: dict[str, Any]) -> str:
    return _b64url(json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _decode_segment(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def _parse_jwt_unverified(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    parts = str(token or "").split(".")
    if len(parts) != 3:
        raise OidcError("ID token is not a JWT", 401, "oidc_id_token")
    try:
        header = json.loads(_decode_segment(parts[0]))
        payload = json.loads(_decode_segment(parts[1]))
    except Exception as exc:
        raise OidcError("ID token could not be decoded", 401, "oidc_id_token") from exc
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    signature = _decode_segment(parts[2])
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise OidcError("ID token header/payload must be objects", 401, "oidc_id_token")
    return header, payload, signing_input, signature


def _public_key_from_jwk(jwk: dict[str, Any]):
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, SECP384R1, SECP521R1
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    kty = str(jwk.get("kty") or "")
    if kty == "RSA":
        n = int.from_bytes(_decode_segment(jwk["n"]), "big")
        e = int.from_bytes(_decode_segment(jwk["e"]), "big")
        return rsa.RSAPublicNumbers(e, n).public_key()
    if kty == "EC":
        crv = str(jwk.get("crv") or "")
        curve = {"P-256": SECP256R1(), "P-384": SECP384R1(), "P-521": SECP521R1()}.get(crv)
        if curve is None:
            raise OidcError(f"Unsupported EC curve '{crv}'", 401, "oidc_id_token")
        x = int.from_bytes(_decode_segment(jwk["x"]), "big")
        y = int.from_bytes(_decode_segment(jwk["y"]), "big")
        return ec.EllipticCurvePublicNumbers(x, y, curve).public_key()
    raise OidcError(f"Unsupported JWK kty '{kty}'", 401, "oidc_id_token")


def verify_id_token(
    token: str,
    *,
    jwks: dict[str, Any],
    issuer: str,
    audience: str,
    nonce: str | None,
    client_id: str,
) -> dict[str, Any]:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

    header, claims, signing_input, signature = _parse_jwt_unverified(token)
    alg = str(header.get("alg") or "")
    kid = header.get("kid")
    keys = [k for k in (jwks.get("keys") or []) if isinstance(k, dict)]
    if kid:
        keys = [k for k in keys if k.get("kid") == kid] or keys
    if not keys:
        raise OidcError("No matching JWKS key for ID token", 401, "oidc_id_token")

    last_err: Exception | None = None
    verified = False
    for jwk in keys:
        try:
            key = _public_key_from_jwk(jwk)
            if alg == "RS256" and isinstance(key, rsa.RSAPublicKey):
                key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
                verified = True
                break
            if alg == "ES256" and isinstance(key, ec.EllipticCurvePublicKey):
                key.verify(signature, signing_input, ec.ECDSA(hashes.SHA256()))
                verified = True
                break
        except InvalidSignature as exc:
            last_err = exc
            continue
        except Exception as exc:
            last_err = exc
            continue
    if not verified:
        raise OidcError(f"ID token signature invalid ({last_err})", 401, "oidc_id_token")

    iss = str(claims.get("iss") or "").rstrip("/")
    if iss != issuer.rstrip("/"):
        raise OidcError("ID token issuer mismatch", 401, "oidc_id_token")
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    auds = [str(a) for a in auds if a]
    expected = audience or client_id
    if expected not in auds and client_id not in auds:
        raise OidcError("ID token audience mismatch", 401, "oidc_id_token")
    now = int(time.time())
    exp = claims.get("exp")
    iat = claims.get("iat")
    if exp is not None and int(exp) < now - 60:
        raise OidcError("ID token expired", 401, "oidc_id_token")
    if iat is not None and int(iat) > now + 120:
        raise OidcError("ID token issued in the future", 401, "oidc_id_token")
    if nonce and str(claims.get("nonce") or "") != nonce:
        raise OidcError("ID token nonce mismatch", 401, "oidc_id_token")
    if not claims.get("sub"):
        raise OidcError("ID token missing sub", 401, "oidc_id_token")
    return claims


# ── claim → user ───────────────────────────────────────────────────────────────


def sanitize_username(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if "@" in s:
        s = s.split("@", 1)[0]
    s = _USERNAME_SANITIZE.sub("-", s)
    s = re.sub(r"[-._]{2,}", "-", s).strip("-._")
    if len(s) < 2:
        digest = hashlib.sha256(str(raw or "x").encode("utf-8")).hexdigest()[:10]
        s = f"u{digest}"
    return s[:64]


def claims_to_profile(claims: dict[str, Any], cfg: OidcConfig) -> dict[str, str]:
    username_raw = (
        claims.get(cfg.username_claim)
        or claims.get("preferred_username")
        or claims.get(cfg.email_claim)
        or claims.get("email")
        or claims.get("sub")
    )
    display = claims.get(cfg.display_name_claim) or claims.get("name") or username_raw
    email = claims.get(cfg.email_claim) or claims.get("email") or ""
    return {
        "sub": str(claims.get("sub") or ""),
        "username": sanitize_username(str(username_raw or "")),
        "display_name": str(display or "")[:128],
        "email": str(email or "").strip()[:256],
    }


def resolve_oidc_user(cfg: OidcConfig, claims: dict[str, Any]):
    from app.core.trust.users import get_user_store

    profile = claims_to_profile(claims, cfg)
    if not profile["sub"]:
        raise OidcError("OIDC subject missing", 401, "oidc_claims")
    store = get_user_store()
    return store.upsert_oidc_user(
        issuer=cfg.issuer,
        sub=profile["sub"],
        username=profile["username"],
        display_name=profile["display_name"],
        email=profile["email"],
        default_roles=cfg.default_roles,
        auto_provision=cfg.auto_provision,
    )


# ── login flow ─────────────────────────────────────────────────────────────────


def resolve_redirect_uri(cfg: OidcConfig, request_base: str | None = None) -> str:
    if cfg.redirect_uri:
        return cfg.redirect_uri
    base = (request_base or "").rstrip("/")
    if not base:
        raise OidcError(
            "GRAPHYN_OIDC_REDIRECT_URI is required when the request base URL is unknown",
            500,
            "oidc_config",
        )
    return f"{base}/api/v1/auth/oidc/callback"


def begin_login(*, return_to: str = "/", request_base: str | None = None) -> dict[str, str]:
    cfg = oidc_config()
    if not cfg.enabled:
        raise OidcError("OIDC is not enabled", 404, "oidc_disabled")
    doc = discover(cfg.issuer)
    redirect_uri = resolve_redirect_uri(cfg, request_base)
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    safe_return = return_to if str(return_to or "").startswith("/") and not str(return_to).startswith("//") else "/"
    with _DB_LOCK, _conn() as c:
        _purge(c)
        c.execute(
            "INSERT INTO oidc_states (state, code_verifier, nonce, return_to, redirect_uri, created_at) VALUES (?,?,?,?,?,?)",
            (state, verifier, nonce, safe_return, redirect_uri, time.time()),
        )
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri,
        "scope": cfg.scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = str(doc["authorization_endpoint"])
    sep = "&" if "?" in auth_url else "?"
    return {
        "authorize_url": f"{auth_url}{sep}{urllib.parse.urlencode(params)}",
        "state": state,
        "redirect_uri": redirect_uri,
        "return_to": safe_return,
    }


def _userinfo(doc: dict[str, Any], access_token: str) -> dict[str, Any]:
    uri = doc.get("userinfo_endpoint")
    if not uri or not access_token:
        return {}
    import httpx

    with httpx.Client(timeout=_HTTP_TIMEOUT_S, follow_redirects=True) as client:
        r = client.get(str(uri), headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
        if r.status_code >= 400:
            return {}
        data = r.json()
    return data if isinstance(data, dict) else {}


def finish_callback(*, code: str, state: str) -> dict[str, Any]:
    cfg = oidc_config()
    if not cfg.enabled:
        raise OidcError("OIDC is not enabled", 404, "oidc_disabled")
    if not code or not state:
        raise OidcError("Missing code or state", 400, "oidc_callback")
    with _DB_LOCK, _conn() as c:
        _purge(c)
        row = c.execute("SELECT * FROM oidc_states WHERE state=?", (state,)).fetchone()
        if row is None or row["consumed_at"] is not None:
            raise OidcError("Invalid or expired OIDC state", 400, "oidc_state")
        if time.time() - float(row["created_at"]) > _STATE_TTL_S:
            raise OidcError("OIDC state expired — start sign-in again", 400, "oidc_state")
        c.execute("UPDATE oidc_states SET consumed_at=? WHERE state=?", (time.time(), state))
        verifier = row["code_verifier"]
        nonce = row["nonce"]
        return_to = row["return_to"] or "/"
        redirect_uri = row["redirect_uri"]

    doc = discover(cfg.issuer)
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": cfg.client_id,
        "code_verifier": verifier,
    }
    auth = (cfg.client_id, cfg.client_secret) if cfg.client_secret else None
    if not cfg.client_secret:
        form["client_id"] = cfg.client_id
    token_body = _http_post_form(str(doc["token_endpoint"]), form, auth=auth)
    id_token = token_body.get("id_token")
    access_token = str(token_body.get("access_token") or "")
    claims: dict[str, Any] = {}
    if id_token and doc.get("jwks_uri"):
        jwks = _fetch_jwks(str(doc["jwks_uri"]))
        claims = verify_id_token(
            str(id_token),
            jwks=jwks,
            issuer=cfg.issuer,
            audience=cfg.audience or cfg.client_id,
            nonce=nonce,
            client_id=cfg.client_id,
        )
    else:
        claims = _userinfo(doc, access_token)
        if not claims.get("sub"):
            raise OidcError("IdP did not return a verifiable ID token or userinfo subject", 401, "oidc_claims")
    # Merge userinfo extras (email/name) when ID token is present but sparse.
    extra = _userinfo(doc, access_token)
    for k, v in extra.items():
        claims.setdefault(k, v)

    from app.core.trust.users import SESSION_TTL_S, get_user_store

    user = resolve_oidc_user(cfg, claims)
    token, cred = get_user_store().issue_credential(
        "session",
        user_id=user.id,
        name="oidc console session",
        ttl_s=SESSION_TTL_S,
        created_by=user.username,
        meta={"auth_method": "oidc", "oidc_issuer": cfg.issuer, "oidc_sub": claims.get("sub")},
    )
    ticket = secrets.token_urlsafe(24)
    payload = {
        "token": token,
        "expires_at": cred.public()["expires_at"],
        "credential_id": cred.id,
        "user": user.public(),
        "return_to": return_to,
    }
    with _DB_LOCK, _conn() as c:
        _purge(c)
        c.execute(
            "INSERT INTO oidc_tickets (ticket, payload, created_at, expires_at) VALUES (?,?,?,?)",
            (ticket, json.dumps(payload), time.time(), time.time() + _TICKET_TTL_S),
        )
    ui = cfg.ui_origin
    if ui:
        q = urllib.parse.urlencode({"oidc_ticket": ticket, "returnTo": return_to})
        complete_url = f"{ui}/login?{q}"
    else:
        complete_url = f"/login?{urllib.parse.urlencode({'oidc_ticket': ticket, 'returnTo': return_to})}"
    return {
        "ticket": ticket,
        "complete_url": complete_url,
        "return_to": return_to,
        "user": user.public(),
        "credential_id": cred.id,
    }


def redeem_ticket(ticket: str) -> dict[str, Any]:
    if not ticket:
        raise OidcError("Missing ticket", 400, "oidc_ticket")
    with _DB_LOCK, _conn() as c:
        _purge(c)
        row = c.execute("SELECT * FROM oidc_tickets WHERE ticket=?", (ticket,)).fetchone()
        if row is None or row["consumed_at"] is not None:
            raise OidcError("Invalid or already-used OIDC ticket", 400, "oidc_ticket")
        if float(row["expires_at"]) < time.time():
            raise OidcError("OIDC ticket expired — sign in again", 400, "oidc_ticket")
        c.execute("UPDATE oidc_tickets SET consumed_at=? WHERE ticket=?", (time.time(), ticket))
        payload = json.loads(row["payload"])
    if not isinstance(payload, dict) or not payload.get("token"):
        raise OidcError("Corrupt OIDC ticket", 500, "oidc_ticket")
    return payload


__all__ = [
    "OidcConfig",
    "OidcError",
    "begin_login",
    "claims_to_profile",
    "clear_oidc_caches",
    "discover",
    "finish_callback",
    "oidc_config",
    "oidc_enabled",
    "password_login_allowed",
    "public_status",
    "redeem_ticket",
    "resolve_redirect_uri",
    "sanitize_username",
    "verify_id_token",
]
