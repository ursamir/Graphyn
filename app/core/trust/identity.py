# app/core/trust/identity.py
"""
Bounded Context:  BC6 — Observability & Storage (audit identity)
Responsibility:   Bind audit identity to the API bearer token. Loads the
                  token→name map (GRAPHYN_API_TOKENS / GRAPHYN_API_TOKENS_FILE),
                  checks tokens (mapped or the single GRAPHYN_API_TOKEN), and
                  carries the per-request identity in a ContextVar so core
                  audit emitters (record_audit) stamp the caller even when
                  they were handed a generic actor ("api" / "system").
                  Mode B WAVE-1: named tokens may be worker-scoped
                  (kind=worker + optional worker_id) for route ACL.
Owns:             parse_token_map(), parse_token_entries(), load_token_map(),
                  load_token_entries(), lookup_token(), lookup_token_info(),
                  token_auth_configured(), token_accepted(),
                  identity_from_credentials(), set_request_identity(),
                  reset_request_identity(), current_identity(), bind_actor(),
                  worker_route_allowed(), TokenInfo, GENERIC_ACTORS, UNIDENTIFIED.
Public Surface:   The functions above. Identity dict shape:
                  ``{actor, actor_verified, token_mapped, claimed_actor,
                     kind, worker_id}``.
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

Token map formats (backward compatible):
  * Text: ``name:token`` (operator) or ``name:token:worker[:worker_id]``
  * JSON: ``{"token": "name"}`` or
    ``{"token": {"name": "…", "kind": "worker"|"operator", "worker_id": "…"}}``
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

UNIDENTIFIED = "unidentified"
# Placeholder actors that a request identity may replace inside record_audit.
GENERIC_ACTORS = frozenset({"", "api", "system", "unknown", "human", "anonymous", UNIDENTIFIED})

_MAX_NAME = 128
_IDENTITY: ContextVar[dict[str, Any] | None] = ContextVar("graphyn_request_identity", default=None)
_file_cache: dict[str, tuple[float, dict[str, "TokenInfo"]]] = {}
_file_lock = threading.Lock()


@dataclass(frozen=True)
class TokenInfo:
    """Metadata for one accepted bearer token."""

    name: str
    kind: str = "operator"  # operator | worker
    worker_id: str | None = None

    @property
    def is_worker(self) -> bool:
        return self.kind == "worker"


def _clean_name(raw: Any) -> str:
    return str(raw or "").strip()[:_MAX_NAME]


def _clean_worker_id(raw: Any) -> str | None:
    s = str(raw or "").strip()
    if not s:
        return None
    return s[:_MAX_NAME]


def _kind_of(raw: Any) -> str:
    k = str(raw or "operator").strip().lower()
    if k in ("worker", "w"):
        return "worker"
    return "operator"


def _token_info_from_meta(name: Any, meta: Any = None) -> TokenInfo | None:
    n = _clean_name(name)
    if not n:
        return None
    if meta is None:
        return TokenInfo(name=n, kind="operator", worker_id=None)
    if isinstance(meta, dict):
        # JSON value form: {"name", "kind", "worker_id"} used as the *value*
        # when key is the token — or as the whole value when token is the key
        # and value is a string name (handled by caller).
        nn = _clean_name(meta.get("name")) or n
        kind = _kind_of(meta.get("kind"))
        wid = _clean_worker_id(meta.get("worker_id"))
        return TokenInfo(name=nn, kind=kind, worker_id=wid)
    return TokenInfo(name=n, kind="operator", worker_id=None)


def parse_token_entries(raw: str | None) -> dict[str, TokenInfo]:
    """Parse token map text/JSON into token → TokenInfo.

    Text form: ``name:token``, ``name:token:worker``, ``name:token:worker:id``
    (commas or newlines; ``#`` comments). JSON: ``{"token": "name"}`` or
    ``{"token": {"name", "kind", "worker_id"}}``.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    out: dict[str, TokenInfo] = {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            log.warning("GRAPHYN_API_TOKENS: invalid JSON — ignored")
            return {}
        if not isinstance(data, dict):
            return {}
        for tok, val in data.items():
            t = str(tok or "").strip()
            if not t:
                continue
            if isinstance(val, dict):
                # Prefer explicit name inside object; fall back to empty → drop
                info = _token_info_from_meta(val.get("name") or "", val)
                if info is None:
                    # {"token": {"kind": "worker", "worker_id": "s99"}} without name
                    # — refuse (no anonymous worker tokens)
                    continue
                out[t] = info
            else:
                info = _token_info_from_meta(val)
                if info is not None:
                    out[t] = info
        return out
    import re as _re
    _worker_suf = _re.compile(
        r"^(?P<tok>.+):worker(?::(?P<wid>[A-Za-z0-9_.-]+))?$",
        _re.IGNORECASE,
    )
    for chunk in text.replace("\n", ",").split(","):
        item = chunk.strip()
        if not item or item.startswith("#"):
            continue
        name, sep, rest = item.partition(":")
        n = _clean_name(name)
        rest = rest.strip()
        if not sep or not n or not rest:
            continue
        m = _worker_suf.match(rest)
        if m:
            tok = m.group("tok").strip()
            wid = _clean_worker_id(m.group("wid"))
            if tok:
                out[tok] = TokenInfo(name=n, kind="worker", worker_id=wid)
        else:
            out[rest] = TokenInfo(name=n, kind="operator", worker_id=None)
    return out


def parse_token_map(raw: str | None) -> dict[str, str]:
    """Parse ``{"token": "name"}`` JSON or ``name:token,…`` text → token → name.

    Backward-compatible view of :func:`parse_token_entries` (names only).
    """
    return {tok: info.name for tok, info in parse_token_entries(raw).items()}


def _file_entries(path_s: str) -> dict[str, TokenInfo]:
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
        parsed = parse_token_entries(path.read_text(encoding="utf-8"))
    except OSError as exc:
        log.warning("GRAPHYN_API_TOKENS_FILE unreadable: %s", exc)
        parsed = {}
    with _file_lock:
        _file_cache[path_s] = (mtime, parsed)
    return parsed


def load_token_entries() -> dict[str, TokenInfo]:
    """token → TokenInfo from GRAPHYN_API_TOKENS_FILE then GRAPHYN_API_TOKENS.

    Read on every call (file cached by mtime) so rotation needs no restart.
    Env entries win on conflicts.
    """
    merged: dict[str, TokenInfo] = {}
    fpath = (os.environ.get("GRAPHYN_API_TOKENS_FILE") or "").strip()
    if fpath:
        merged.update(_file_entries(fpath))
    merged.update(parse_token_entries(os.environ.get("GRAPHYN_API_TOKENS")))
    return merged


def load_token_map() -> dict[str, str]:
    """token → name from GRAPHYN_API_TOKENS_FILE then GRAPHYN_API_TOKENS (env wins)."""
    return {tok: info.name for tok, info in load_token_entries().items()}


def _single_token() -> str:
    try:
        from app.core.config import api_token

        return api_token() or ""
    except Exception:
        return (os.environ.get("GRAPHYN_API_TOKEN") or "").strip()


def lookup_token_info(token: str | None) -> TokenInfo | None:
    """TokenInfo for ``token`` (constant-time compare per entry), or None."""
    tok = str(token or "")
    if not tok:
        return None
    found: TokenInfo | None = None
    for known, info in load_token_entries().items():
        if hmac.compare_digest(known.encode("utf-8"), tok.encode("utf-8")) and found is None:
            found = info
    return found


def lookup_token(token: str | None) -> str | None:
    """Mapped identity name for ``token`` (constant-time compare per entry)."""
    info = lookup_token_info(token)
    return info.name if info is not None else None


def token_auth_configured() -> bool:
    """True when any bearer token (single or mapped) is configured."""
    return bool(_single_token()) or bool(load_token_entries())


def token_accepted(token: str | None) -> bool:
    """True when ``token`` equals GRAPHYN_API_TOKEN or a mapped token."""
    tok = str(token or "")
    if not tok:
        return False
    single = _single_token()
    if single and hmac.compare_digest(single.encode("utf-8"), tok.encode("utf-8")):
        return True
    return lookup_token_info(tok) is not None


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
    info = lookup_token_info(token)
    if info is not None:
        return {
            "actor": info.name,
            "actor_verified": True,
            "token_mapped": True,
            "claimed_actor": claim if claim and claim != info.name else None,
            "kind": info.kind,
            "worker_id": info.worker_id,
        }
    # Single shared GRAPHYN_API_TOKEN (or no map hit) → operator, unverified name
    return {
        "actor": claim or UNIDENTIFIED,
        "actor_verified": False,
        "token_mapped": False,
        "claimed_actor": None,
        "kind": "operator",
        "worker_id": None,
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


def current_token_info() -> TokenInfo | None:
    """TokenInfo for the current request bearer, if mapped."""
    ident = current_identity()
    if not ident or not ident.get("token_mapped"):
        return None
    kind = str(ident.get("kind") or "operator")
    return TokenInfo(
        name=str(ident.get("actor") or UNIDENTIFIED),
        kind=kind if kind in ("operator", "worker") else "operator",
        worker_id=_clean_worker_id(ident.get("worker_id")),
    )


def is_operator_identity(ident: dict[str, Any] | None = None) -> bool:
    """True when the caller is not a worker-scoped mapped token / mTLS cert."""
    ident = ident if ident is not None else current_identity()
    if not ident:
        return True  # no request / unauthenticated-dev → treat as operator
    # mTLS worker cert (even without a mapped bearer) is not an operator.
    if ident.get("mtls_worker_id") and str(ident.get("kind") or "") == "worker":
        return False
    if not ident.get("token_mapped"):
        return True  # shared single token or unverified → operator
    return str(ident.get("kind") or "operator") != "worker"


def worker_route_allowed(
    requested_worker_id: str | None,
    *,
    ident: dict[str, Any] | None = None,
) -> bool:
    """Route ACL for worker-scoped tokens and/or mTLS client certs.

    Operator / unmapped / unauthenticated-dev → always True.
    When ``mtls_worker_id`` is present, ``requested_worker_id`` must match it
    (cert identity). When a worker-scoped token binds a ``worker_id``, the
    request must match that too (cert AND token when both present — middleware
    already rejects mismatches). Tokens with ``kind=worker`` and no bound id
    accept any non-empty requested id (lab convenience).
    """
    ident = ident if ident is not None else current_identity()
    if is_operator_identity(ident):
        return True
    req = str(requested_worker_id or "").strip()
    if not req:
        return False
    mtls_wid = _clean_worker_id((ident or {}).get("mtls_worker_id"))
    if mtls_wid is not None:
        if not hmac.compare_digest(mtls_wid.encode("utf-8"), req.encode("utf-8")):
            return False
    bound = _clean_worker_id((ident or {}).get("worker_id"))
    if bound is None:
        return True
    return hmac.compare_digest(bound.encode("utf-8"), req.encode("utf-8"))


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
    "TokenInfo",
    "bind_actor",
    "GENERIC_ACTORS",
    "UNIDENTIFIED",
    "bearer_from_header",
    "current_identity",
    "current_token_info",
    "identity_from_credentials",
    "is_operator_identity",
    "load_token_entries",
    "load_token_map",
    "lookup_token",
    "lookup_token_info",
    "parse_token_entries",
    "parse_token_map",
    "reset_request_identity",
    "set_request_identity",
    "token_accepted",
    "token_auth_configured",
    "worker_route_allowed",
]
