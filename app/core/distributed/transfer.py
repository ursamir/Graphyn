# app/core/distributed/transfer.py
"""
Bounded Context:  BC5 / BC6 — Distributed port payload transfer
Responsibility:   Serialize port values ↔ bytes, store/fetch content-addressed
                  blobs under ``artifacts/distributed_blobs``, and provide
                  HTTP helpers for workers talking to the control API.
Owns:             dump_port_value, load_port_value, put_blob,
                  put_blob_with_digest, get_blob, verify_blob_bytes,
                  http_put_blob, http_get_blob, blob_root, uri_to_key,
                  job_output_key, parse_job_output_key, tombstone_blobs,
                  delete_job_blobs, delete_blobs, sweep_blobs.
Public Surface:   All functions above.
Must NOT:         Import from app.domain or app.api.
Dependencies:     stdlib, artifact_uri, config.artifacts_dir, isolated_executor
                  (RestrictedUnpickler + recast_plugin_types).
Reason To Change: Serializer strategy, store layout, HTTP transfer protocol,
                  blob integrity (sha256) or retention/cleanup policy.

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
import uuid
import re
import urllib.error
import urllib.request
from urllib.parse import quote
from pathlib import Path
from typing import Any

from app.core.artifacts.artifact_uri import (
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


def _safe_path(key: str, root: Path | None = None) -> Path:
    key = (key or "").lstrip("/")
    if not key or not _BLOB_KEY_RE.match(key) or ".." in key.split("/"):
        raise ValueError(f"Invalid blob key: {key!r}")
    base = Path(root) if root is not None else blob_root()
    path = (base / key).resolve()
    root = base.resolve()
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


class BlobIntegrityError(ValueError):
    """Downloaded/stored blob bytes do not match the expected sha256."""


def _sha256_from_key(key: str) -> str | None:
    """Expected digest for content-addressed ``sha256/…`` keys, else None."""
    if not key.startswith("sha256/"):
        return None
    expected = key.rsplit("/", 1)[-1].lower()
    if len(expected) >= 8 and all(c in "0123456789abcdef" for c in expected):
        return expected
    return None


def verify_blob_bytes(
    data: bytes, *, key: str | None = None, expected_sha256: str | None = None, uri: str = ""
) -> None:
    """Raise :class:`BlobIntegrityError` when ``data`` fails any known digest.

    Checks the content-addressed key digest (``sha256/…``) and/or an explicit
    ``expected_sha256`` (e.g. ``JobResult.output_sha256``).
    """
    wanted = [d for d in (_sha256_from_key(key or ""), expected_sha256) if d]
    if not wanted:
        return
    actual = hashlib.sha256(data).hexdigest()
    for exp in wanted:
        exp_l = str(exp).lower()
        # Key digests may be a prefix; explicit digests must be full.
        if not (actual == exp_l or (len(exp_l) < 64 and actual.startswith(exp_l))):
            raise BlobIntegrityError(
                f"Blob content hash mismatch for {uri or key}: "
                f"expected {exp_l}, got {actual}"
            )


def put_blob_with_digest(data: bytes, *, key: str | None = None) -> tuple[str, str]:
    """Store raw bytes; return ``(artifact://local/{key}, sha256_hex)``.

    When ``key`` is omitted a sha256 content-addressed key is used. Blobs are
    write-once: an existing key with identical bytes is an idempotent no-op;
    different bytes raise :class:`FileExistsError` (never overwritten).
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
    uri = build_artifact_uri(LOCAL_STORE_ID, key)

    def _same_existing() -> bool:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest() == digest
        except OSError:
            return False

    content_addressed = _sha256_from_key(key) is not None
    if path.is_file():
        if _same_existing():
            try:
                os.utime(path)  # mark "re-used" so run-end cleanup keeps it
            except OSError:
                pass
            return uri, digest
        if not content_addressed:
            raise FileExistsError(f"Blob {key!r} already exists with different content")
        # Corrupt content-addressed blob: heal it below with the verified bytes.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    try:
        with open(tmp, "wb") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        if content_addressed:
            verify_blob_bytes(body, key=key, uri=uri)
            os.replace(tmp, path)
            return uri, digest
        try:
            # Atomic create-if-absent: link fails when another writer won.
            os.link(tmp, path)
        except FileExistsError:
            if _same_existing():
                return uri, digest
            raise FileExistsError(
                f"Blob {key!r} already exists with different content"
            ) from None
        except OSError:
            # Filesystem without hard links: best-effort exclusive replace.
            if path.exists():
                if _same_existing():
                    return uri, digest
                raise FileExistsError(
                    f"Blob {key!r} already exists with different content"
                ) from None
            os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return uri, digest


def put_blob(data: bytes, *, key: str | None = None) -> str:
    """Store raw bytes (write-once); return ``artifact://local/{key}``."""
    return put_blob_with_digest(data, key=key)[0]


def get_blob(uri: str, *, expected_sha256: str | None = None) -> bytes:
    """Load blob bytes for an ``artifact://local/…`` URI from the local store.

    Verifies ``sha256/`` key digests and ``expected_sha256`` when given.
    """
    parsed = parse_artifact_uri(uri)
    if parsed.store != LOCAL_STORE_ID:
        raise ValueError(
            f"get_blob only resolves local store URIs in-process; got {uri!r}"
        )
    path = _safe_path(parsed.key)
    if not path.is_file():
        raise FileNotFoundError(f"Blob not found for {uri}")
    data = path.read_bytes()
    verify_blob_bytes(data, key=parsed.key, expected_sha256=expected_sha256, uri=uri)
    return data


def http_put_blob(
    control_url: str,
    data: bytes,
    *,
    key: str | None = None,
    token: str | None = None,
    timeout_s: float = 60.0,
    worker_id: str | None = None,
) -> str:
    """PUT bytes to control ``POST /artifacts/blob``; return artifact URI.

    ``worker_id`` is required by the control plane for explicit
    ``jobs/<job_id>/g<gen>/…`` keys (must match the job's current claim).
    Verifies the server-reported sha256 against the local digest.
    """
    base = (control_url or "").rstrip("/")
    if not base:
        raise ValueError("control_url is required for http_put_blob")
    params = []
    if key:
        params.append(f"key={quote(key, safe='')}")
    if worker_id:
        params.append(f"worker_id={quote(worker_id, safe='')}")
    qs = ("?" + "&".join(params)) if params else ""
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
    remote_sha = payload.get("sha256")
    if remote_sha and str(remote_sha).lower() != hashlib.sha256(data).hexdigest():
        raise BlobIntegrityError(
            f"Control stored blob {uri} with sha256 {remote_sha} != local digest"
        )
    return str(uri)


def http_get_blob(
    control_url: str,
    uri: str,
    *,
    token: str | None = None,
    timeout_s: float = 60.0,
    expected_sha256: str | None = None,
) -> bytes:
    """GET blob bytes from control ``GET /artifacts/blob/{key}`` (verified).

    ``sha256/`` key digests and ``expected_sha256`` are checked; a mismatch
    raises :class:`BlobIntegrityError` (never returns corrupt bytes).
    """
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
            data = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} GET blob {uri}: {detail}") from exc
    verify_blob_bytes(data, key=key, expected_sha256=expected_sha256, uri=uri)
    return data


def job_output_key(job_id: str, lease_generation: int, port: str) -> str:
    """Generation-scoped blob key so a rejected complete can delete its writes.

    Content-addressed ``sha256/…`` keys are shared and must not be deleted.
    Worker outputs use this key so a stale lease can tombstone only its blobs.
    """
    safe_job = _safe_job_segment(job_id)
    safe_port = re.sub(r"[^A-Za-z0-9_.-]", "_", str(port or ""))[:64] or "port"
    return f"jobs/{safe_job}/g{int(lease_generation)}/{safe_port}"


def _safe_job_segment(job_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(job_id or ""))[:80] or "job"


_JOB_KEY_RE = re.compile(r"^jobs/([A-Za-z0-9_.-]+)/g(\d+)/[A-Za-z0-9_.-]+$")


def parse_job_output_key(key: str) -> tuple[str, int] | None:
    """Return ``(job_segment, lease_generation)`` for ``jobs/<job>/g<gen>/<port>``."""
    m = _JOB_KEY_RE.match((key or "").lstrip("/"))
    if not m:
        return None
    return m.group(1), int(m.group(2))


def delete_job_blobs(job_ids: list[str], *, root: Path | None = None) -> int:
    """Delete generation-scoped output blobs (``jobs/<job_id>/``). Returns files removed."""
    import shutil

    root = (Path(root) if root is not None else blob_root()).resolve()
    removed = 0
    for jid in job_ids or []:
        d = (root / "jobs" / _safe_job_segment(jid)).resolve()
        if not d.is_relative_to(root / "jobs") or not d.is_dir():
            continue
        removed += sum(1 for p in d.rglob("*") if p.is_file())
        shutil.rmtree(d, ignore_errors=True)
    return removed


def delete_blobs(uris: list[str], *, root: Path | None = None) -> int:
    """Delete specific local blob files by URI (missing/invalid ignored)."""
    removed = 0
    for uri in uris or []:
        try:
            path = _safe_path(uri_to_key(str(uri)), root)
        except Exception:
            continue
        try:
            if path.is_file():
                path.unlink()
                removed += 1
        except OSError as exc:
            log.warning("delete_blobs: failed to remove %s: %s", path, exc)
    return removed


def sweep_blobs(
    *,
    older_than_s: float,
    protected_keys: set[str] | frozenset[str] = frozenset(),
    protected_job_segments: set[str] | frozenset[str] = frozenset(),
) -> dict[str, int]:
    """TTL sweep of ``distributed_blobs``: delete files older than ``older_than_s``.

    Skips keys in ``protected_keys`` and anything under
    ``jobs/<segment>/`` for ``protected_job_segments`` (active jobs). Empty
    directories are pruned. Returns ``{"blobs_deleted", "bytes_freed"}``.
    """
    import time as _time

    root = blob_root()
    cutoff = _time.time() - max(0.0, float(older_than_s))
    deleted = 0
    freed = 0
    for path in list(root.rglob("*")):
        try:
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in protected_keys:
                continue
            parts = rel.split("/")
            if len(parts) >= 2 and parts[0] == "jobs" and parts[1] in protected_job_segments:
                continue
            st = path.stat()
            if st.st_mtime >= cutoff:
                continue
            path.unlink()
            deleted += 1
            freed += st.st_size
        except OSError as exc:
            log.warning("sweep_blobs: failed on %s: %s", path, exc)
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        try:
            d.rmdir()  # only succeeds when empty
        except OSError:
            pass
    return {"blobs_deleted": deleted, "bytes_freed": freed}


def tombstone_blobs(uris: list[str], *, reason: str) -> list[str]:
    """Record rejected output URIs and delete generation-scoped job blobs.

    ``sha256/`` content-addressed blobs are recorded but left on disk because
    another job may share the same bytes. Returns URIs whose files were removed.
    """
    import json

    deleted: list[str] = []
    lines: list[str] = []
    root = blob_root()
    record = root.parent / "distributed_blob_tombstones.jsonl"
    for uri in uris:
        if not uri:
            continue
        try:
            key = uri_to_key(str(uri))
        except Exception:
            lines.append(
                json.dumps({"uri": str(uri), "deleted": False, "reason": reason})
            )
            continue
        removed = False
        if key.startswith("jobs/"):
            try:
                path = _safe_path(key)
            except ValueError:
                path = None
            if path is not None and path.is_file():
                path.unlink()
                removed = True
                deleted.append(str(uri))
        lines.append(
            json.dumps(
                {
                    "uri": str(uri),
                    "key": key,
                    "deleted": removed,
                    "reason": reason,
                }
            )
        )
    if lines:
        record.parent.mkdir(parents=True, exist_ok=True)
        with open(record, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return deleted


def put_port_value(value: Any, *, key: str | None = None) -> str:
    """Serialize a port value and store it; return artifact URI."""
    return put_blob(dump_port_value(value), key=key)


def put_port_value_with_digest(value: Any, *, key: str | None = None) -> tuple[str, str]:
    """Serialize + store a port value; return ``(uri, sha256_hex)``."""
    return put_blob_with_digest(dump_port_value(value), key=key)


def get_port_value(uri: str, *, expected_sha256: str | None = None) -> Any:
    """Fetch a blob by URI (integrity-checked) and deserialize to a port value."""
    return load_port_value(get_blob(uri, expected_sha256=expected_sha256))

# Public names. A leading underscore stays private to this module.
safe_path = _safe_path
sha256_from_key = _sha256_from_key
safe_job_segment = _safe_job_segment
