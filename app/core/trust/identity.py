# app/core/trust/identity.py
"""
Bounded Context:  BC6 — Observability & Storage (audit identity)
Responsibility:   Bind audit identity to the API bearer token. Loads the
                  token→name map (GRAPHYN_API_TOKENS / GRAPHYN_API_TOKENS_FILE),
                  checks tokens (mapped or the single GRAPHYN_API_TOKEN), and
                  carries the per-request identity in a ContextVar so core
                  audit emitters (record_audit) stamp the caller even when
                  they were handed a generic actor ("api" / "system").
Owns:             parse_token_map(), load_token_map(), lookup_token(),
                  token_auth_configured(), token_accepted(),
                  identity_from_credentials(), set_request_identity(),
                  reset_request_identity(), current_identity(), bind_actor(),
                  GENERIC_ACTORS, UNIDENTIFIED.
Public Surface:   The functions above. Identity dict shape:
                  ``{actor, actor_verified, token_mapped, claimed_actor}``.
Must NOT:         Import app.api / app.domain / execution; log or return
                  token values.
Dependencies:     stdlib (contextvars, hmac, json, os), app.core.config.api_token.
Reason To Change: Token map format, identity policy or verification rules change.

Policy:
  * token maps to a name → ``actor`` = that name, ``actor_verified`` = True; an
    X-Actor header / body actor that differs is kept as ``claimed_actor`` only.
  * unmapped token (single GRAPHYN_API_TOKEN, or no auth in dev) → ``actor`` =
    X-Actor / body actor, else ``"unidentified"``; ``actor_verified`` = False.
  * ``"system"`` is reserved for internal background jobs (no request context).
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import threading
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

UNIDENTIFIED = "unidentified"
# Placeholder actors that a request identity may replace inside record_audit.
GENERIC_ACTORS = frozenset({"", "api", "system", "unknown", "human", "anonymous", UNIDENTIFIED})

_MAX_NAME = 128
_IDENTITY: ContextVar[dict[str, Any] | None] = ContextVar("graphyn_request_identity", default=None)
_file_cache: dict[str, tuple[float, dict[str, str]]] = {}
_file_lock = threading.Lock()


def _clean_name(raw: Any) -> str:
    return str(raw or "").strip()[:_MAX_NAME]


def parse_token_map(raw: str | None) -> dict[str, str]:
    """Parse ``{"token": "name"}`` JSON or ``name:token,name:token`` text.

    Text form also accepts newlines as separators and ``#`` comment lines.
    Entries with an empty token or name are dropped. Returns token → name.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    out: dict[str, str] = {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            log.warning("GRAPHYN_API_TOKENS: invalid JSON — ignored")
            return {}
        if isinstance(data, dict):
            for tok, name in data.items():
                t, n = str(tok or "").strip(), _clean_name(name)
                if t and n:
                    out[t] = n
        return out
    for chunk in text.replace("\n", ",").split(","):
        item = chunk.strip()
        if not item or item.startswith("#"):
            continue
        name, sep, tok = item.partition(":")
        t, n = tok.strip(), _clean_name(name)
        if sep and t and n:
            out[t] = n
    return out


def _file_map(path_s: str) -> dict[str, str]:
    path = Path(path_s).expanduser()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    with _file_lock:
        hit = _file_cache.get(path_s)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    try:
        parsed = parse_token_map(path.read_text(encoding="utf-8"))
    except OSError as exc:
        log.warning("GRAPHYN_API_TOKENS_FILE unreadable: %s", exc)
        parsed = {}
    with _file_lock:
        _file_cache[path_s] = (mtime, parsed)
    return parsed


def load_token_map() -> dict[str, str]:
    """token → name from GRAPHYN_API_TOKENS_FILE then GRAPHYN_API_TOKENS (env wins).

    Read on every call (file cached by mtime) so rotation needs no restart.
    """
    merged: dict[str, str] = {}
    fpath = (os.environ.get("GRAPHYN_API_TOKENS_FILE") or "").strip()
    if fpath:
        merged.update(_file_map(fpath))
    merged.update(parse_token_map(os.environ.get("GRAPHYN_API_TOKENS")))
    return merged


def _single_token() -> str:
    try:
        from app.core.config import api_token

        return api_token() or ""
    except Exception:
        return (os.environ.get("GRAPHYN_API_TOKEN") or "").strip()


def lookup_token(token: str | None) -> str | None:
    """Mapped identity name for ``token`` (constant-time compare per entry)."""
    tok = str(token or "")
    if not tok:
        return None
    found: str | None = None
    for known, name in load_token_map().items():
        if hmac.compare_digest(known.encode("utf-8"), tok.encode("utf-8")) and found is None:
            found = name
    return found


def token_auth_configured() -> bool:
    """True when any bearer token (single or mapped) is configured."""
    return bool(_single_token()) or bool(load_token_map())


def token_accepted(token: str | None) -> bool:
    """True when ``token`` equals GRAPHYN_API_TOKEN or a mapped token."""
    tok = str(token or "")
    if not tok:
        return False
    single = _single_token()
    if single and hmac.compare_digest(single.encode("utf-8"), tok.encode("utf-8")):
        return True
    return lookup_token(tok) is not None


def bearer_from_header(value: str | None) -> str | None:
    scheme, _, cred = str(value or "").partition(" ")
    if scheme.lower() != "bearer" or not cred.strip():
        return None
    return cred.strip()


def identity_from_credentials(
    token: str | None,
    claimed: str | None = None,
    explicit: str | None = None,
) -> dict[str, Any]:
    """Identity dict for one request (see module policy)."""
    claim = _clean_name(explicit) or _clean_name(claimed) or None
    name = lookup_token(token)
    if name:
        return {
            "actor": name,
            "actor_verified": True,
            "token_mapped": True,
            "claimed_actor": claim if claim and claim != name else None,
        }
    return {
        "actor": claim or UNIDENTIFIED,
        "actor_verified": False,
        "token_mapped": False,
        "claimed_actor": None,
    }


def set_request_identity(identity: dict[str, Any] | None) -> Token:
    return _IDENTITY.set(dict(identity) if isinstance(identity, dict) else None)


def reset_request_identity(token: Token) -> None:
    try:
        _IDENTITY.reset(token)
    except (ValueError, RuntimeError):
        _IDENTITY.set(None)


def current_identity() -> dict[str, Any] | None:
    """Identity of the HTTP request being served, or None (background job)."""
    ident = _IDENTITY.get()
    return dict(ident) if isinstance(ident, dict) else None


def bind_actor(
    actor: str | None,
    verified: bool | None = None,
    claimed: str | None = None,
) -> tuple[str, bool, str | None, str]:
    """Merge an explicit actor with the current request identity.

    Returns ``(actor, actor_verified, claimed_actor, origin)``; ``origin`` is
    ``"http"`` inside an API request, else ``"internal"``. Inside a request a
    generic actor (``api`` / ``system`` / ``human`` / empty) becomes the
    request identity; ``actor_verified`` is true only when the final actor is
    the token-mapped name. Outside a request an empty actor is ``"system"``.
    """
    act = _clean_name(actor)
    ident = current_identity()
    if ident is None:
        return act or "system", bool(verified), claimed, "internal"
    if act.lower() in GENERIC_ACTORS:
        act = str(ident.get("actor") or UNIDENTIFIED)
    same = act == ident.get("actor")
    if verified is None:
        verified = bool(ident.get("actor_verified")) and same
    if claimed is None and same:
        claimed = ident.get("claimed_actor")
    return act, bool(verified), claimed, "http"


__all__ = [
    "bind_actor",
    "GENERIC_ACTORS",
    "UNIDENTIFIED",
    "bearer_from_header",
    "current_identity",
    "identity_from_credentials",
    "load_token_map",
    "lookup_token",
    "parse_token_map",
    "reset_request_identity",
    "set_request_identity",
    "token_accepted",
    "token_auth_configured",
]
