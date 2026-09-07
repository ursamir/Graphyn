# app/core/distributed/transfer.py
"""
Bounded Context:  BC5 / BC6 — Distributed port payload transfer
Responsibility:   Serialize port values ↔ bytes, store/fetch content-addressed
                  blobs under ``artifacts/distributed_blobs``, and provide
                  HTTP helpers for workers talking to the control API.
Owns:             dump_port_value, load_port_value, put_blob, get_blob,
                  http_put_blob, http_get_blob, blob_root, uri_to_key.
Public Surface:   All functions above.
Must NOT:         Import from app.domain or app.api.
Dependencies:     stdlib, artifact_uri, config.artifacts_dir, isolated_executor
                  (RestrictedUnpickler + recast_plugin_types).
Reason To Change: Serializer strategy, store layout, or HTTP transfer protocol.

P1 note
-------
Port payloads use pickle + ``recast_plugin_types`` (same pattern as
``isolated_executor``). Host-side loads use ``RestrictedUnpickler``.
Known PortDataType values may later route through ArtifactSerializerRegistry;
for P1 pickle+recast is intentional and documented here.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import pickle
import re
import urllib.error
import urllib.request
from urllib.parse import quote
from pathlib import Path
from typing import Any

from app.core.artifact_uri import (
    LOCAL_STORE_ID,
    build_artifact_uri,
    local_content_key,
    parse_artifact_uri,
)

log = logging.getLogger(__name__)

_BLOB_KEY_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


def blob_root() -> Path:
    """Return (and create) the distributed blob store root."""
    from app.core.config import artifacts_dir

    root = Path(artifacts_dir()) / "distributed_blobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def uri_to_key(uri: str) -> str:
    """Extract the store key from an ``artifact://…`` URI."""
    return parse_artifact_uri(uri).key


def _safe_path(key: str) -> Path:
    key = (key or "").lstrip("/")
    if not key or not _BLOB_KEY_RE.match(key) or ".." in key.split("/"):
        raise ValueError(f"Invalid blob key: {key!r}")
    path = (blob_root() / key).resolve()
    root = blob_root().resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Invalid blob key: {key!r}")
    return path


def dump_port_value(value: Any) -> bytes:
    """Serialize a port value to bytes (pickle + plugin-type recast)."""
    from app.core.plugins.isolated_executor import recast_plugin_types

    safe = recast_plugin_types(value)
    return pickle.dumps(safe, protocol=pickle.HIGHEST_PROTOCOL)


def load_port_value(data: bytes) -> Any:
    """Deserialize port bytes with RestrictedUnpickler (fail closed)."""
    from app.core.plugins.isolated_executor import RestrictedUnpickler
    from app.core.plugins.hydrate import hydrate_platform_models

    obj = RestrictedUnpickler(io.BytesIO(data)).load()
    try:
        return hydrate_platform_models(obj)
    except Exception:
        return obj


def put_blob(data: bytes, *, key: str | None = None) -> str:
    """Store raw bytes; return ``artifact://local/{key}``.

    When ``key`` is omitted a sha256 content-addressed key is used.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(f"put_blob expects bytes, got {type(data)!r}")
    body = bytes(data)
    if not body:
        raise ValueError("put_blob refuses empty payloads")
    digest = hashlib.sha256(body).hexdigest()
    if not key:
        key = local_content_key(digest)
    path = _safe_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_bytes(body)
    return build_artifact_uri(LOCAL_STORE_ID, key)


def get_blob(uri: str) -> bytes:
    """Load blob bytes for an ``artifact://local/…`` URI from the local store."""
    parsed = parse_artifact_uri(uri)
    if parsed.store != LOCAL_STORE_ID:
        raise ValueError(
            f"get_blob only resolves local store URIs in-process; got {uri!r}"
        )
    path = _safe_path(parsed.key)
    if not path.is_file():
        raise FileNotFoundError(f"Blob not found for {uri}")
    return path.read_bytes()


def http_put_blob(
    control_url: str,
    data: bytes,
    *,
    key: str | None = None,
    token: str | None = None,
    timeout_s: float = 60.0,
) -> str:
    """PUT bytes to control ``POST /artifacts/blob``; return artifact URI."""
    base = (control_url or "").rstrip("/")
    if not base:
        raise ValueError("control_url is required for http_put_blob")
    qs = f"?key={quote(key, safe='')}" if key else ""
    url = f"{base}/artifacts/blob{qs}"
    headers = {"Content-Type": "application/octet-stream", "Accept": "application/json"}
    tok = token if token is not None else os.environ.get("GRAPHYN_API_TOKEN", "")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            import json

            body = resp.read().decode("utf-8")
            payload = json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} PUT blob: {detail}") from exc
    uri = payload.get("uri")
    if not uri:
        raise RuntimeError(f"Control blob PUT returned no uri: {payload!r}")
    return str(uri)


def http_get_blob(
    control_url: str,
    uri: str,
    *,
    token: str | None = None,
    timeout_s: float = 60.0,
) -> bytes:
    """GET blob bytes from control ``GET /artifacts/blob/{key}``."""
    base = (control_url or "").rstrip("/")
    if not base:
        raise ValueError("control_url is required for http_get_blob")
    key = uri_to_key(uri)
    # Preserve path separators; encode other reserved characters.
    encoded_key = quote(key, safe="/")
    url = f"{base}/artifacts/blob/{encoded_key}"
    headers = {"Accept": "application/octet-stream"}
    tok = token if token is not None else os.environ.get("GRAPHYN_API_TOKEN", "")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} GET blob {uri}: {detail}") from exc


def put_port_value(value: Any, *, key: str | None = None) -> str:
    """Serialize a port value and store it; return artifact URI."""
    return put_blob(dump_port_value(value), key=key)


def get_port_value(uri: str) -> Any:
    """Fetch a blob by URI and deserialize to a port value."""
    return load_port_value(get_blob(uri))
