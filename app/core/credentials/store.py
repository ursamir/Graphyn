# app/core/credentials/store.py
"""Durable encrypted credential (connection) store under GRAPHYN_HOME/credentials.

Hot: create / rotate / revoke without API restart — every read hits SQLite.
Payloads are sealed with app.core.credentials.crypto; list/get never return
raw secret fields.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.credentials.crypto import credentials_dir, seal, unseal
from app.core.credentials.errors import CredentialError, CredentialNotFoundError
from app.core.credentials.kinds import (
    redact_payload,
    require_kind,
    validate_payload,
)

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_DB_NAME = "store.sqlite"


def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _db_path() -> str:
    return str(credentials_dir() / _DB_NAME)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS connections (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            sealed_payload TEXT NOT NULL,
            is_default INTEGER NOT NULL DEFAULT 0,
            revoked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_connections_kind ON connections(kind)"
    )
    conn.commit()


def _row_meta(row: sqlite3.Row, *, include_redacted: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if include_redacted and not row["revoked"]:
        try:
            raw = json.loads(unseal(row["sealed_payload"]).decode("utf-8"))
            payload = redact_payload(row["kind"], raw if isinstance(raw, dict) else {})
        except Exception:
            payload = {"_error": "unreadable"}
    meta: dict[str, Any] = {}
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except Exception:
        meta = {}
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "is_default": bool(row["is_default"]),
        "revoked": bool(row["revoked"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "meta": meta,
        "fields": payload,
        "resource_version": row["updated_at"],
    }


def create_connection(
    *,
    name: str,
    kind: str,
    payload: dict[str, Any],
    is_default: bool = False,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a connection. Returns redacted metadata (never raw secrets)."""
    require_kind(kind)
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise CredentialError("connection name is required")
    cleaned = validate_payload(kind, payload or {}, partial=False)
    sealed = seal(json.dumps(cleaned, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    cid = str(uuid.uuid4())
    now = _utcnow()
    meta_json = json.dumps(meta or {}, separators=(",", ":"), ensure_ascii=False)
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            if is_default:
                conn.execute(
                    "UPDATE connections SET is_default=0 WHERE kind=? AND revoked=0",
                    ((kind or "").strip().lower(),),
                )
            conn.execute(
                """
                INSERT INTO connections
                (id, name, kind, sealed_payload, is_default, revoked, created_at, updated_at, meta_json)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    cid,
                    cleaned_name,
                    (kind or "").strip().lower(),
                    sealed,
                    1 if is_default else 0,
                    now,
                    now,
                    meta_json,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM connections WHERE id=?", (cid,)).fetchone()
        finally:
            conn.close()
    # Never log payload
    logger.info("credentials: created connection id=%s kind=%s name=%s", cid, kind, cleaned_name)
    return _row_meta(row)


def list_connections(
    *,
    kind: str | None = None,
    include_revoked: bool = False,
) -> list[dict[str, Any]]:
    """List connection metadata (redacted fields only)."""
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            sql = "SELECT * FROM connections WHERE 1=1"
            args: list[Any] = []
            if kind:
                sql += " AND kind=?"
                args.append(kind.strip().lower())
            if not include_revoked:
                sql += " AND revoked=0"
            sql += " ORDER BY kind, name"
            rows = conn.execute(sql, args).fetchall()
        finally:
            conn.close()
    return [_row_meta(r) for r in rows]


def get_connection(connection_id: str, *, include_revoked: bool = False) -> dict[str, Any]:
    """Return redacted metadata for one connection."""
    cid = (connection_id or "").strip()
    if not cid:
        raise CredentialNotFoundError("connection id required")
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            row = conn.execute("SELECT * FROM connections WHERE id=?", (cid,)).fetchone()
        finally:
            conn.close()
    if row is None:
        raise CredentialNotFoundError(f"Credential connection {cid!r} not found")
    if row["revoked"] and not include_revoked:
        raise CredentialNotFoundError(f"Credential connection {cid!r} is revoked")
    return _row_meta(row)


def get_payload(connection_id: str) -> tuple[str, dict[str, Any]]:
    """Return (kind, plaintext payload) for runtime resolve only. Never expose via API."""
    cid = (connection_id or "").strip()
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            row = conn.execute("SELECT * FROM connections WHERE id=?", (cid,)).fetchone()
        finally:
            conn.close()
    if row is None or row["revoked"]:
        raise CredentialNotFoundError(f"Credential connection {cid!r} not found or revoked")
    raw = json.loads(unseal(row["sealed_payload"]).decode("utf-8"))
    if not isinstance(raw, dict):
        raise CredentialError("Corrupt credential payload")
    return row["kind"], raw


def update_connection(
    connection_id: str,
    *,
    name: str | None = None,
    payload: dict[str, Any] | None = None,
    is_default: bool | None = None,
    meta: dict[str, Any] | None = None,
    rotate: bool = False,
) -> dict[str, Any]:
    """Update / rotate a connection. Payload merge unless rotate=True (replace)."""
    cid = (connection_id or "").strip()
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            row = conn.execute("SELECT * FROM connections WHERE id=?", (cid,)).fetchone()
            if row is None or row["revoked"]:
                raise CredentialNotFoundError(f"Credential connection {cid!r} not found or revoked")
            kind = row["kind"]
            new_name = (name if name is not None else row["name"]).strip()
            if not new_name:
                raise CredentialError("connection name is required")
            current = json.loads(unseal(row["sealed_payload"]).decode("utf-8"))
            if not isinstance(current, dict):
                current = {}
            if payload is not None:
                if rotate:
                    merged = validate_payload(kind, payload, partial=False)
                else:
                    merged = dict(current)
                    merged.update(payload)
                    merged = validate_payload(kind, merged, partial=False)
            else:
                merged = current
            sealed = seal(json.dumps(merged, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
            now = _utcnow()
            if is_default is True:
                conn.execute(
                    "UPDATE connections SET is_default=0 WHERE kind=? AND revoked=0",
                    (kind,),
                )
            default_val = row["is_default"] if is_default is None else (1 if is_default else 0)
            meta_json = row["meta_json"]
            if meta is not None:
                meta_json = json.dumps(meta, separators=(",", ":"), ensure_ascii=False)
            conn.execute(
                """
                UPDATE connections
                SET name=?, sealed_payload=?, is_default=?, updated_at=?, meta_json=?
                WHERE id=?
                """,
                (new_name, sealed, default_val, now, meta_json, cid),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM connections WHERE id=?", (cid,)).fetchone()
        finally:
            conn.close()
    logger.info("credentials: updated connection id=%s kind=%s", cid, row["kind"])
    return _row_meta(row)


def revoke_connection(connection_id: str, *, delete: bool = False) -> dict[str, Any]:
    """Revoke (soft) or permanently delete a connection."""
    cid = (connection_id or "").strip()
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            row = conn.execute("SELECT * FROM connections WHERE id=?", (cid,)).fetchone()
            if row is None:
                raise CredentialNotFoundError(f"Credential connection {cid!r} not found")
            if delete:
                conn.execute("DELETE FROM connections WHERE id=?", (cid,))
                conn.commit()
                logger.info("credentials: deleted connection id=%s", cid)
                return {"ok": True, "id": cid, "deleted": True}
            now = _utcnow()
            conn.execute(
                "UPDATE connections SET revoked=1, is_default=0, updated_at=? WHERE id=?",
                (now, cid),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM connections WHERE id=?", (cid,)).fetchone()
        finally:
            conn.close()
    logger.info("credentials: revoked connection id=%s", cid)
    return _row_meta(row, include_redacted=False)


def set_default(connection_id: str) -> dict[str, Any]:
    """Bind connection as workspace default for its kind."""
    return update_connection(connection_id, is_default=True)


def get_default_for_kind(kind: str) -> dict[str, Any] | None:
    kid = (kind or "").strip().lower()
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM connections WHERE kind=? AND is_default=1 AND revoked=0 LIMIT 1",
                (kid,),
            ).fetchone()
        finally:
            conn.close()
    if row is None:
        return None
    return _row_meta(row)


def connection_exists(connection_id: str) -> bool:
    try:
        get_connection(connection_id)
        return True
    except CredentialNotFoundError:
        return False
