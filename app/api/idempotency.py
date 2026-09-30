# app/api/idempotency.py
"""
Bounded Context:  REST API Layer
Responsibility:   Honor ``Idempotency-Key`` on mutating endpoints (API-CONV-004).

Behavior (SRS §9.0 API-CONV-004):
  - Header ``Idempotency-Key``: ASCII, 1–128 chars (optional unless route requires it).
  - Storage key: ``(actor, key, route)`` where route is ``METHOD path_template``.
  - Same key + same body fingerprint → replay original status + body.
  - Same key + different body → **409** ``idempotency_conflict``.
  - Same key while the first request is still executing → **409**
    ``idempotency_in_progress`` (an in-flight placeholder is reserved
    atomically by ``begin_idempotent``; it never runs twice).
  - Failed requests release the placeholder (``abort_idempotent`` /
    ``idempotency_guard``) so the client may retry with the same key;
    placeholders orphaned by a crash expire after 15 minutes.
  - TTL default 24h; expired entries are treated as new.

Durability: filesystem under ``{GRAPHYN_HOME or project}/.idempotency/`` with
atomic replace (unique tmp); reservation decisions run under a store-wide
file lock (threads + processes); in-memory index of *completed* entries.

Public Surface:   idempotent(), begin_idempotent(), complete_idempotent(),
                  abort_idempotent(), idempotency_guard(),
                  IdempotencyConflict, IN_PROGRESS_TTL_S
Must NOT:         Authenticate; import routers circularly.
Dependencies:     hashlib, json, os, tempfile, threading, time, uuid,
                  pathlib; app.core.config; app.core.pipelines.project_pipelines
                  (resource_lock); fastapi Request.
Reason To Change: TTL policy, storage backend, or key scope changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

log = logging.getLogger(__name__)

DEFAULT_TTL_S = 24 * 3600
# A placeholder older than this is treated as orphaned (worker crashed).
IN_PROGRESS_TTL_S = 15 * 60
_IN_PROGRESS = "in_progress"
_COMPLETED = "completed"
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


def _entry_path(comp: str) -> Path:
    return _store_dir() / f"{comp}.json"


def _store_lock():
    """Store-wide exclusive lock (threads + processes) for reserve/abort."""
    from app.core.pipelines.project_pipelines import resource_lock

    return resource_lock(_store_dir() / ".store.lock")


def _read_disk(comp: str) -> Optional[dict[str, Any]]:
    try:
        data = json.loads(_entry_path(comp).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None  # unreadable → treated as absent (overwritten on reserve)
    return data if isinstance(data, dict) else None


def _is_in_progress(data: dict[str, Any]) -> bool:
    return data.get("state") == _IN_PROGRESS


def _is_live(data: dict[str, Any], now: float) -> bool:
    if _is_in_progress(data):
        return float(data.get("started_at") or 0) + IN_PROGRESS_TTL_S >= now
    return float(data.get("expires_at") or 0) >= now


def _load_entry(comp: str) -> Optional[dict[str, Any]]:
    """Live entry (completed or in-progress) or None. Never deletes files."""
    now = time.time()
    with _LOCK:
        mem = _MEMORY.get(comp)
        if mem is not None:
            if mem.get("expires_at", 0) >= now:
                return dict(mem)
            _MEMORY.pop(comp, None)
    data = _read_disk(comp)
    if data is None or not _is_live(data, now):
        return None
    if not _is_in_progress(data):
        with _LOCK:
            _MEMORY[comp] = data
    return dict(data)


def _write_disk(comp: str, data: dict[str, Any]) -> None:
    path = _entry_path(comp)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{comp}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2, default=str))
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _save_entry(comp: str, data: dict[str, Any]) -> None:
    with _LOCK:
        _MEMORY[comp] = data
    _write_disk(comp, data)


def _reserve(comp: str, fp: str, ttl_s: int) -> str:
    """Create the in-flight placeholder. Caller holds ``_store_lock``."""
    token = uuid.uuid4().hex
    now = time.time()
    placeholder = {
        "state": _IN_PROGRESS,
        "token": token,
        "body_fp": fp,
        "started_at": now,
        "expires_at": now + IN_PROGRESS_TTL_S,
        "pid": os.getpid(),
    }
    path = _entry_path(comp)
    try:
        # O_EXCL: exactly one creator even if the lock were not honoured.
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        # A dead (expired / stale / corrupt) entry: replace it atomically.
        _write_disk(comp, placeholder)
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(placeholder, indent=2))
            fh.flush()
    return token


def _replay(existing: dict[str, Any]) -> Response:
    status = int(existing.get("status_code") or 200)
    content = existing.get("body")
    headers = dict(existing.get("headers") or {})
    headers["Idempotent-Replay"] = "true"
    if content is None:
        return Response(status_code=status, headers=headers)
    return JSONResponse(status_code=status, content=content, headers=headers)


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": "idempotency_conflict",
            "code": "idempotency_conflict",
            "message": "Idempotency-Key reused with a different request body",
        },
    )


def _in_progress() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": "idempotency_in_progress",
            "code": "idempotency_in_progress",
            "message": (
                "A request with this Idempotency-Key is still being processed; "
                "retry later to receive its result"
            ),
        },
        headers={"Retry-After": "1"},
    )


def begin_idempotent(
    request: Request,
    *,
    body: Any,
    route: Optional[str] = None,
    actor: Optional[str] = None,
    ttl_s: int = DEFAULT_TTL_S,
) -> Optional[Response]:
    """If Idempotency-Key present, return cached Response or None to proceed.

    Returning None means this request now owns an in-flight reservation for
    the key: callers MUST then call ``complete_idempotent`` on success or
    ``abort_idempotent`` on failure (``idempotency_guard`` does the latter).
    Raises 409 ``idempotency_conflict`` (different body) or
    ``idempotency_in_progress`` (same key still executing).
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
    request.state.idempotency_comp = None
    request.state.idempotency_fp = fp
    request.state.idempotency_ttl = ttl_s

    # Fast path: completed entry cached in memory / on disk → replay.
    existing = _load_entry(comp)
    if existing is not None and not _is_in_progress(existing):
        if existing.get("body_fp") != fp:
            raise _conflict()
        return _replay(existing)

    with _store_lock():
        existing = _read_disk(comp)
        if existing is not None and _is_live(existing, time.time()):
            if existing.get("body_fp") != fp:
                raise _conflict()
            if _is_in_progress(existing):
                raise _in_progress()
            with _LOCK:
                _MEMORY[comp] = existing
            return _replay(existing)
        token = _reserve(comp, fp, ttl_s)
    request.state.idempotency_comp = comp
    request.state.idempotency_token = token
    return None


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
        "state": _COMPLETED,
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
    request.state.idempotency_comp = None


def abort_idempotent(request: Request) -> None:
    """Release this request's in-flight reservation (handler failed).

    Only removes the placeholder this request created (token match), so a
    completed entry or someone else's newer reservation is never deleted.
    Safe to call when no reservation is held.
    """
    comp = getattr(request.state, "idempotency_comp", None)
    token = getattr(request.state, "idempotency_token", None)
    request.state.idempotency_comp = None
    if not comp or not token:
        return
    try:
        with _store_lock():
            data = _read_disk(comp)
            if data is not None and _is_in_progress(data) and data.get("token") == token:
                _entry_path(comp).unlink(missing_ok=True)
    except Exception as exc:
        log.warning("idempotency abort failed: %s", exc)


@contextmanager
def idempotency_guard(request: Request) -> Iterator[None]:
    """Release the reservation if the wrapped handler body raises."""
    try:
        yield
    except BaseException:
        abort_idempotent(request)
        raise


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

            try:
                result = fn(*args, **kwargs)
            except BaseException:
                if request is not None:
                    abort_idempotent(request)
                raise

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
