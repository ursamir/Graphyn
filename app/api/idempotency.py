# app/api/idempotency.py
"""
Bounded Context:  REST API Layer
Responsibility:   Honor ``Idempotency-Key`` on mutating endpoints (API-CONV-004).

Behavior (SRS §9.0 API-CONV-004):
  - Header ``Idempotency-Key``: ASCII, 1–128 chars (optional unless route requires it).
  - Storage key: ``(actor, key, route)`` where route is ``METHOD path_template``.
  - Same key + same body fingerprint → replay original status + body.
  - Same key + different body → **409** ``idempotency_conflict``.
  - TTL default 24h; expired entries are treated as new.

Durability: filesystem under ``{GRAPHYN_HOME or project}/.idempotency/`` with
atomic replace; in-memory index for the process. Suitable for single-node P0;
multi-node can swap the store later without changing the router API.

Public Surface:   idempotent(), check_and_store(), begin_idempotent(),
                  complete_idempotent(), IdempotencyConflict
Must NOT:         Authenticate; import routers circularly.
Dependencies:     hashlib, json, time, pathlib; app.core.config; fastapi Request.
Reason To Change: TTL policy, storage backend, or key scope changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

log = logging.getLogger(__name__)

DEFAULT_TTL_S = 24 * 3600
_MAX_KEY_LEN = 128
_LOCK = threading.Lock()
_MEMORY: dict[str, dict[str, Any]] = {}


class IdempotencyConflict(Exception):
    """Raised when the same Idempotency-Key is reused with a different body."""


def _store_dir() -> Path:
    try:
        from app.core.config import project_dir

        root = project_dir()
    except Exception:
        root = Path(os.environ.get("GRAPHYN_PROJECT_DIR") or "/tmp/graphyn")
    d = Path(root) / ".idempotency"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _normalize_key(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        return None
    if len(key) > _MAX_KEY_LEN:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": "Idempotency-Key too long (max 128)"},
        )
    try:
        key.encode("ascii")
    except UnicodeEncodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": "Idempotency-Key must be ASCII"},
        ) from exc
    return key


def _body_fingerprint(body: Any) -> str:
    try:
        payload = json.dumps(body, sort_keys=True, default=str, separators=(",", ":"))
    except Exception:
        payload = repr(body)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _composite_key(actor: str, key: str, route: str) -> str:
    raw = f"{actor}\0{key}\0{route}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_entry(comp: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        mem = _MEMORY.get(comp)
        if mem is not None:
            if mem.get("expires_at", 0) >= time.time():
                return dict(mem)
            _MEMORY.pop(comp, None)
    path = _store_dir() / f"{comp}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if float(data.get("expires_at") or 0) < time.time():
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return None
    with _LOCK:
        _MEMORY[comp] = data
    return dict(data)


def _save_entry(comp: str, data: dict[str, Any]) -> None:
    path = _store_dir() / f"{comp}.json"
    tmp = path.with_suffix(".tmp")
    text = json.dumps(data, indent=2, default=str)
    with _LOCK:
        _MEMORY[comp] = data
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)


def begin_idempotent(
    request: Request,
    *,
    body: Any,
    route: Optional[str] = None,
    actor: Optional[str] = None,
    ttl_s: int = DEFAULT_TTL_S,
) -> Optional[Response]:
    """If Idempotency-Key present, return cached Response or None to proceed.

    Callers that proceed MUST call ``complete_idempotent`` after producing the
    success response. On conflict, raises HTTPException 409.
    """
    key = _normalize_key(request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key"))
    if key is None:
        request.state.idempotency_comp = None
        return None

    from app.api.actor import resolve_actor

    act = actor or resolve_actor(request)
    route_key = route or f"{request.method} {request.url.path}"
    comp = _composite_key(act, key, route_key)
    fp = _body_fingerprint(body)
    request.state.idempotency_comp = comp
    request.state.idempotency_fp = fp
    request.state.idempotency_ttl = ttl_s

    existing = _load_entry(comp)
    if existing is None:
        return None
    if existing.get("body_fp") != fp:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "idempotency_conflict",
                "message": "Idempotency-Key reused with a different request body",
            },
        )
    status = int(existing.get("status_code") or 200)
    content = existing.get("body")
    headers = dict(existing.get("headers") or {})
    headers["Idempotent-Replay"] = "true"
    if content is None:
        return Response(status_code=status, headers=headers)
    return JSONResponse(status_code=status, content=content, headers=headers)


def complete_idempotent(
    request: Request,
    *,
    status_code: int,
    body: Any,
    headers: Optional[dict[str, str]] = None,
) -> None:
    """Persist outcome for a prior begin_idempotent that returned None."""
    comp = getattr(request.state, "idempotency_comp", None)
    if not comp:
        return
    fp = getattr(request.state, "idempotency_fp", "")
    ttl_s = int(getattr(request.state, "idempotency_ttl", DEFAULT_TTL_S) or DEFAULT_TTL_S)
    data = {
        "body_fp": fp,
        "status_code": status_code,
        "body": body,
        "headers": headers or {},
        "expires_at": time.time() + ttl_s,
        "stored_at": time.time(),
    }
    try:
        _save_entry(comp, data)
    except Exception as exc:
        log.warning("idempotency store failed: %s", exc)


def idempotent(route_name: str):
    """Decorator for sync FastAPI handlers that return a JSON-serializable dict.

    Expects the handler signature to include ``request: Request`` and a body
    argument (Pydantic model or dict) named ``body`` or ``payload``.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Optional[Request] = kwargs.get("request")
            if request is None:
                for a in args:
                    if isinstance(a, Request):
                        request = a
                        break
            body = kwargs.get("body", kwargs.get("payload"))
            if body is not None and hasattr(body, "model_dump"):
                body_data = body.model_dump()
            elif isinstance(body, dict):
                body_data = body
            else:
                body_data = body

            if request is not None:
                cached = begin_idempotent(
                    request,
                    body=body_data,
                    route=route_name or f"{request.method} {request.url.path}",
                )
                if cached is not None:
                    return cached

            result = fn(*args, **kwargs)

            if request is not None and getattr(request.state, "idempotency_comp", None):
                if isinstance(result, JSONResponse):
                    try:
                        content = json.loads(result.body.decode("utf-8")) if result.body else None
                    except Exception:
                        content = None
                    complete_idempotent(
                        request,
                        status_code=result.status_code,
                        body=content,
                        headers={k: v for k, v in result.headers.items()},
                    )
                elif isinstance(result, Response):
                    complete_idempotent(
                        request,
                        status_code=result.status_code,
                        body=None,
                        headers={k: v for k, v in result.headers.items()},
                    )
                else:
                    complete_idempotent(request, status_code=200, body=result)
            return result

        return wrapper

    return decorator
