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
                  delete_job_blobs, delete_blobs, sweep_blobs,
                  mint_signed_blob_url, verify_signed_blob_url, blob_signing_secret,
                  prepare_port_value_for_put, materialize_path_sidecars,
                  materialize_artifact_refs, PATH_SIDELOAD_MARK (legacy),
                  UnreclaimedHostPathError.
                  Mode B WAVE-2: optional encrypt-at-rest (GRAPHYN_BLOB_ENCRYPTION_KEY).
Public Surface:   All functions above.
Must NOT:         Import from app.domain or app.api.
Dependencies:     stdlib, artifact_uri, artifact_pack, config.artifacts_dir,
                  isolated_executor (RestrictedUnpickler + recast_plugin_types).
Reason To Change: Serializer strategy, store layout, HTTP transfer protocol,
                  blob integrity (sha256), retention/cleanup, or ArtifactRef transfer.

P1 note
-------
Port payloads use pickle + ``recast_plugin_types`` (same pattern as
``isolated_executor``). Host-side loads use ``RestrictedUnpickler``.
Path-bearing platform artifacts carry an ``ArtifactRef`` manifest (roles such
as ``keras_model``, ``saved_model``, ``labels``): ``prepare_port_value_for_put``
packs local files by role into content-addressed blobs and wires **refs only**
(fail-closed if unreclaimed host paths remain). ``load_port_value`` /
``materialize_artifact_refs`` hydrate under a materialize root (prefer
``<node_write_dir>/_inputs/<port>/…``) and rewrite local path fields for plugin
execution only. File bytes travel via manifest/blobs; metadata may pickle.
ArtifactSerializerRegistry may reuse the same pack helpers for on-disk runs.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import pickle
import tarfile
import uuid
import re
import urllib.error
import urllib.request
from urllib.parse import quote
from pathlib import Path
from typing import Any, Callable

from app.core.artifacts.artifact_pack import UnreclaimedHostPathError
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


# ---------------------------------------------------------------------------
# ArtifactRef transfer (Mode B — no shared filesystem)
# ---------------------------------------------------------------------------

PATH_SIDELOAD_MARK = "__graphyn_path_sideload__"  # legacy envelope mark (still hydrated)
PATH_SIDELOAD_VERSION = 1

# Re-export for callers / tests.
def default_materialize_root() -> Path:
    """Local root for rewritten path-bearing files (per-host, never shared)."""
    from app.core.config import artifacts_dir

    root = Path(artifacts_dir()) / "distributed_materialized"
    root.mkdir(parents=True, exist_ok=True)
    return root


def inputs_materialize_dir(
    node_write_dir: Path | str | None,
    port: str | None = None,
    *,
    fallback: Path | str | None = None,
) -> Path:
    """Stable hydrate layout: ``<node_write_dir>/_inputs/<port>/…``.

    When *node_write_dir* is omitted, falls back to
    ``default_materialize_root()/_inputs/<port>`` (or bare default root).
    """
    base = Path(node_write_dir) if node_write_dir else (
        Path(fallback) if fallback is not None else default_materialize_root()
    )
    port_name = (port or "_").strip() or "_"
    # Keep port segment basename-safe.
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in port_name)[:120] or "_"
    dest = base / "_inputs" / safe
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def prepare_port_value_for_put(
    value: Any,
    *,
    put_companion: Callable[[bytes], tuple[str, str]] | None = None,
    fail_closed: bool = True,
) -> Any:
    """Pack ArtifactRef roles to content-addressed blobs; wire refs only.

    ``put_companion(data) -> (artifact_uri, sha256_hex)``. When omitted, uses
    local ``put_blob_with_digest``. Mode B is **fail-closed**: unreclaimed host
    paths raise :class:`UnreclaimedHostPathError`.
    """
    put_fn = put_companion
    if put_fn is None:
        def put_fn(data: bytes) -> tuple[str, str]:  # type: ignore[misc]
            return put_blob_with_digest(data)

    return _attach_artifact_refs(value, put_companion=put_fn, fail_closed=fail_closed)


def _attach_artifact_refs(
    value: Any,
    *,
    put_companion: Callable[[bytes], tuple[str, str]],
    fail_closed: bool,
) -> Any:
    from app.core.artifacts.artifact_pack import (
        apply_packed_refs,
        collect_path_bearing_roles,
        has_path_bearing_contract,
    )

    if value is None or isinstance(value, (str, bytes, int, float, bool, complex)):
        return value
    if isinstance(value, dict):
        if PATH_SIDELOAD_MARK in value:
            # Legacy envelope — leave as-is (still materializable).
            return value
        return {
            k: _attach_artifact_refs(v, put_companion=put_companion, fail_closed=fail_closed)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _attach_artifact_refs(v, put_companion=put_companion, fail_closed=fail_closed)
            for v in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _attach_artifact_refs(v, put_companion=put_companion, fail_closed=fail_closed)
            for v in value
        )
    if not has_path_bearing_contract(value):
        return value
    from app.core.artifacts.artifact_pack import declared_unreclaimable_host_paths

    missing = declared_unreclaimable_host_paths(value)
    if missing and fail_closed:
        raise UnreclaimedHostPathError(
            "Unreclaimed host path(s) would cross Mode B boundary: "
            + ", ".join(missing[:8])
        )
    refs = collect_path_bearing_roles(value)
    if not refs:
        # No files to pack — strip residual host paths; fail if any remain.
        from app.core.artifacts.artifact_pack import scan_host_paths, strip_host_paths

        value = strip_host_paths(value, fail_closed=fail_closed)
        leftover = scan_host_paths(value)
        if leftover and fail_closed:
            raise UnreclaimedHostPathError(
                "Unreclaimed host path(s) would cross Mode B boundary: "
                + ", ".join(leftover[:8])
            )
        return value
    return apply_packed_refs(
        value, refs, put_companion=put_companion, fail_closed=fail_closed
    )


def materialize_artifact_refs(
    value: Any,
    *,
    materialize_dir: Path | str | None = None,
    get_companion: Callable[..., bytes] | None = None,
    port: str | None = None,
) -> Any:
    """Fetch ArtifactRef blobs and rewrite path fields onto *materialize_dir*.

    Prefer ``inputs_materialize_dir(node_write_dir, port)`` so siblings land under
    ``<node_write_dir>/_inputs/<port>/…``.
    """
    get_fn = get_companion
    if get_fn is None:
        def get_fn(uri: str, expected_sha256: str | None = None) -> bytes:  # type: ignore[misc]
            return get_blob(uri, expected_sha256=expected_sha256)

    root = Path(materialize_dir) if materialize_dir is not None else default_materialize_root()
    if port:
        root = inputs_materialize_dir(root, port)
    return _materialize_walk(value, materialize_root=root, get_companion=get_fn)


# Back-compat alias used by older call sites / tests.
def materialize_path_sidecars(
    value: Any,
    *,
    materialize_dir: Path | str | None = None,
    get_companion: Callable[..., bytes] | None = None,
) -> Any:
    return materialize_artifact_refs(
        value, materialize_dir=materialize_dir, get_companion=get_companion
    )


def _materialize_walk(
    value: Any,
    *,
    materialize_root: Path,
    get_companion: Callable[..., bytes],
) -> Any:
    from app.core.artifacts.artifact_pack import (
        has_path_bearing_contract,
        materialize_refs_onto,
    )

    if value is None or isinstance(value, (str, bytes, int, float, bool, complex)):
        return value
    if isinstance(value, dict) and PATH_SIDELOAD_MARK in value:
        return _materialize_legacy_envelope(
            value, materialize_root=materialize_root, get_companion=get_companion
        )
    if isinstance(value, dict):
        return {
            k: _materialize_walk(
                v, materialize_root=materialize_root, get_companion=get_companion
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _materialize_walk(
                v, materialize_root=materialize_root, get_companion=get_companion
            )
            for v in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _materialize_walk(
                v, materialize_root=materialize_root, get_companion=get_companion
            )
            for v in value
        )
    if has_path_bearing_contract(value) and getattr(value, "refs", None):
        return materialize_refs_onto(
            value, dest_root=materialize_root, get_companion=get_companion
        )
    return value


def _materialize_legacy_envelope(
    env: dict[str, Any],
    *,
    materialize_root: Path,
    get_companion: Callable[..., bytes],
) -> Any:
    """Hydrate pre-ArtifactRef sideload envelopes (one release back-compat)."""
    from app.core.artifacts.artifact_pack import atomic_write_bytes, unpack_directory
    from app.core.plugins.hydrate import hydrate_platform_models

    payload = env.get("payload")
    try:
        payload = hydrate_platform_models(payload)
    except Exception:
        pass
    sidecars = env.get("sidecars") or {}
    if not isinstance(sidecars, dict) or not sidecars:
        return payload

    def _safe_basename(name: str) -> str:
        base = Path(str(name or "artifact")).name
        base = base.replace("\\", "/").split("/")[-1]
        if not base or base in {".", ".."} or ".." in base:
            return "artifact"
        return base[:200]

    def _rewrite_path_field(obj: Any, field: str, new_path: str) -> Any:
        if hasattr(obj, "model_copy"):
            try:
                return obj.model_copy(update={field: new_path})
            except Exception:
                pass
        if hasattr(obj, "model_dump") and hasattr(type(obj), "model_validate"):
            try:
                payload_d = obj.model_dump()
                payload_d[field] = new_path
                return type(obj).model_validate(payload_d)
            except Exception:
                pass
        try:
            setattr(obj, field, new_path)
            return obj
        except Exception:
            return obj

    for field, meta in sidecars.items():
        if not isinstance(meta, dict):
            continue
        uri = str(meta.get("uri") or "")
        if not uri:
            continue
        digest = str(meta.get("sha256") or "") or None
        name = _safe_basename(str(meta.get("name") or "artifact"))
        kind = str(meta.get("kind") or "file")
        data = get_companion(uri, expected_sha256=digest)
        actual = hashlib.sha256(data).hexdigest()
        if digest and digest.lower() != actual:
            raise BlobIntegrityError(
                f"Path sideload companion hash mismatch for {uri}: "
                f"expected {digest}, got {actual}"
            )
        dest_dir = materialize_root / actual[:2] / actual
        dest_dir.mkdir(parents=True, exist_ok=True)
        if kind == "dir":
            dest = dest_dir / name
            marker = dest_dir / f".{name}.extracted"
            if not marker.is_file():
                if dest.exists():
                    import shutil

                    shutil.rmtree(dest, ignore_errors=True)
                unpack_directory(data, dest)
                marker.write_text(actual, encoding="utf-8")
            local_path = str(dest)
        else:
            dest = dest_dir / name
            if not dest.is_file() or dest.stat().st_size != len(data):
                atomic_write_bytes(dest, data)
            local_path = str(dest)
        payload = _rewrite_path_field(payload, str(field), local_path)
    return payload


def dump_port_value(value: Any) -> bytes:
    """Serialize a port value to bytes (pickle + plugin-type recast).

    Callers that need path sideload must run
    :func:`prepare_port_value_for_put` first (``put_port_value`` does this).
    """
    from app.core.plugins.isolated_executor import recast_plugin_types

    safe = recast_plugin_types(value)
    return pickle.dumps(safe, protocol=pickle.HIGHEST_PROTOCOL)


def load_port_value(
    data: bytes,
    *,
    materialize_dir: Path | str | None = None,
    get_companion: Callable[..., bytes] | None = None,
    port: str | None = None,
) -> Any:
    """Deserialize port bytes with RestrictedUnpickler (fail closed).

    ArtifactRef manifests (and legacy sideload envelopes) are materialized under
    ``materialize_dir`` (default ``artifacts/distributed_materialized``), optionally
    namespaced by *port* as ``_inputs/<port>/``, so path fields point at real
    local files on this host for plugin execution only.
    """
    from app.core.plugins.isolated_executor import RestrictedUnpickler
    from app.core.plugins.hydrate import hydrate_platform_models

    obj = RestrictedUnpickler(io.BytesIO(data)).load()
    try:
        obj = hydrate_platform_models(obj)
    except Exception:
        pass
    return materialize_artifact_refs(
        obj,
        materialize_dir=materialize_dir,
        get_companion=get_companion,
        port=port,
    )


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
    write-once: an existing key with identical *plaintext* is an idempotent
    no-op; different bytes raise :class:`FileExistsError` (never overwritten).

    Content-addressing always hashes **plaintext**. When
    ``GRAPHYN_BLOB_ENCRYPTION_KEY`` is set the on-disk file is a GBE1 envelope
    (see ``blob_crypto``); ``get_blob`` decrypts then verifies sha256.
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

    from app.core.distributed.blob_crypto import maybe_decrypt_from_disk, maybe_encrypt_for_disk

    def _same_existing() -> bool:
        try:
            raw = path.read_bytes()
            try:
                plain = maybe_decrypt_from_disk(raw)
            except Exception:
                plain = raw
            return hashlib.sha256(plain).hexdigest() == digest
        except OSError:
            return False

    disk_body = maybe_encrypt_for_disk(body)
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
            f.write(disk_body)
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

    Decrypts GBE1 envelopes when ``GRAPHYN_BLOB_ENCRYPTION_KEY`` is set, then
    verifies ``sha256/`` key digests and ``expected_sha256`` against plaintext.
    """
    parsed = parse_artifact_uri(uri)
    if parsed.store != LOCAL_STORE_ID:
        raise ValueError(
            f"get_blob only resolves local store URIs in-process; got {uri!r}"
        )
    path = _safe_path(parsed.key)
    if not path.is_file():
        raise FileNotFoundError(f"Blob not found for {uri}")
    raw = path.read_bytes()
    from app.core.distributed.blob_crypto import maybe_decrypt_from_disk

    data = maybe_decrypt_from_disk(raw)
    verify_blob_bytes(data, key=parsed.key, expected_sha256=expected_sha256, uri=uri)
    return data



def blob_signing_secret() -> str:
    """HMAC secret for short-lived blob URLs.

    ``GRAPHYN_BLOB_SIGNING_KEY`` when set, else ``GRAPHYN_API_TOKEN`` /
    ``api_token()``. Empty when neither is configured (signed URLs unavailable).
    """
    dedicated = (os.environ.get("GRAPHYN_BLOB_SIGNING_KEY") or "").strip()
    if dedicated:
        return dedicated
    try:
        from app.core.config import api_token

        return (api_token() or "").strip()
    except Exception:
        return (os.environ.get("GRAPHYN_API_TOKEN") or "").strip()


def blob_url_ttl_s() -> int:
    """Default TTL for signed blob URLs (``GRAPHYN_BLOB_URL_TTL_S``, default 300)."""
    raw = (os.environ.get("GRAPHYN_BLOB_URL_TTL_S") or "300").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 300


def mint_signed_blob_url(
    key: str,
    *,
    method: str = "GET",
    ttl_s: int | None = None,
    secret: str | None = None,
    base_url: str | None = None,
) -> str:
    """Return a path or absolute URL with ``exp`` + ``sig`` query params.

    When ``base_url`` is set (control ``…/api/v1``), returns
    ``{base}/artifacts/blob/{key}?exp=&sig=``. Otherwise returns
    ``{key}?exp=&sig=`` (relative). Raises ``ValueError`` when no signing
    secret is configured.
    """
    import hashlib as _hashlib
    import hmac as _hmac
    import time as _time
    from urllib.parse import quote as _quote, urlencode

    k = (key or "").lstrip("/")
    if not k or not _BLOB_KEY_RE.match(k) or ".." in k.split("/"):
        raise ValueError("invalid blob key for signed URL")
    sec = secret if secret is not None else blob_signing_secret()
    if not sec:
        raise ValueError("blob signing secret not configured")
    ttl = int(ttl_s) if ttl_s is not None else blob_url_ttl_s()
    exp = int(_time.time()) + max(1, ttl)
    method_u = (method or "GET").upper()
    msg = f"{k}|{exp}|{method_u}".encode("utf-8")
    sig_hex = _hmac.new(sec.encode("utf-8"), msg, _hashlib.sha256).hexdigest()
    qs = urlencode({"exp": str(exp), "sig": sig_hex})
    encoded_key = _quote(k, safe="/")
    if base_url:
        base = base_url.rstrip("/")
        return f"{base}/artifacts/blob/{encoded_key}?{qs}"
    return f"{encoded_key}?{qs}"


def verify_signed_blob_url(
    key: str,
    *,
    exp: str | int | None,
    sig: str | None,
    method: str = "GET",
    secret: str | None = None,
    now: float | None = None,
) -> bool:
    """True when ``sig`` is a valid HMAC for ``key|exp|method`` and not expired."""
    import hashlib as _hashlib
    import hmac as _hmac
    import time as _time

    k = (key or "").lstrip("/")
    if not k or not sig or exp is None:
        return False
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    sec = secret if secret is not None else blob_signing_secret()
    if not sec:
        return False
    ts = _time.time() if now is None else float(now)
    if exp_i < ts:
        return False
    method_u = (method or "GET").upper()
    msg = f"{k}|{exp_i}|{method_u}".encode("utf-8")
    expected = _hmac.new(sec.encode("utf-8"), msg, _hashlib.sha256).hexdigest()
    try:
        return _hmac.compare_digest(expected, str(sig).strip())
    except Exception:
        return False


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
        ssl_ctx = None
        try:
            from app.core.distributed.mtls import mtls_enabled, urllib_ssl_context

            if mtls_enabled():
                ssl_ctx = urllib_ssl_context()
        except Exception:
            ssl_ctx = None
        with urllib.request.urlopen(req, timeout=timeout_s, **({"context": ssl_ctx} if ssl_ctx is not None else {})) as resp:
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
    worker_id: str | None = None,
    use_signed_url: bool = True,
) -> bytes:
    """GET blob bytes from control ``GET /artifacts/blob/{key}`` (verified).

    Prefers a short-lived HMAC signed URL when a signing secret is available
    (``GRAPHYN_BLOB_SIGNING_KEY`` or API token); still sends Bearer as a
    fallback for operators. ``sha256/`` key digests and ``expected_sha256``
    are checked; a mismatch raises :class:`BlobIntegrityError`.
    """
    base = (control_url or "").rstrip("/")
    if not base:
        raise ValueError("control_url is required for http_get_blob")
    # Absolute signed URL already?
    if isinstance(uri, str) and uri.startswith("http") and "sig=" in uri:
        url = uri
        # key for verify_blob_bytes: last path segment after /artifacts/blob/
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(uri)
        path = parsed.path or ""
        marker = "/artifacts/blob/"
        key = path.split(marker, 1)[-1] if marker in path else uri_to_key(uri)
    else:
        key = uri_to_key(uri) if "://" in str(uri) or str(uri).startswith("artifact:") else str(uri).lstrip("/")
        encoded_key = quote(key, safe="/")
        url = f"{base}/artifacts/blob/{encoded_key}"
        if use_signed_url and blob_signing_secret():
            try:
                url = mint_signed_blob_url(key, method="GET", base_url=base)
            except ValueError:
                pass
    headers = {"Accept": "application/octet-stream"}
    tok = token if token is not None else os.environ.get("GRAPHYN_API_TOKEN", "")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    wid = worker_id or os.environ.get("GRAPHYN_WORKER_ID") or None
    if wid:
        headers["X-Graphyn-Worker-Id"] = str(wid)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        ssl_ctx = None
        try:
            from app.core.distributed.mtls import mtls_enabled, urllib_ssl_context

            if mtls_enabled():
                ssl_ctx = urllib_ssl_context()
        except Exception:
            ssl_ctx = None
        with urllib.request.urlopen(req, timeout=timeout_s, **({"context": ssl_ctx} if ssl_ctx is not None else {})) as resp:
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
    """Serialize a port value (ArtifactRef pack, fail-closed) and store it; return URI."""
    prepared = prepare_port_value_for_put(value)
    return put_blob(dump_port_value(prepared), key=key)


def put_port_value_with_digest(value: Any, *, key: str | None = None) -> tuple[str, str]:
    """Serialize + store a port value (ArtifactRef pack); return ``(uri, sha256)``."""
    prepared = prepare_port_value_for_put(value)
    return put_blob_with_digest(dump_port_value(prepared), key=key)


def get_port_value(
    uri: str,
    *,
    expected_sha256: str | None = None,
    materialize_dir: Path | str | None = None,
    get_companion: Callable[..., bytes] | None = None,
    port: str | None = None,
) -> Any:
    """Fetch a blob by URI (integrity-checked) and deserialize to a port value.

    ArtifactRef companions are fetched via ``get_companion`` (default local
    ``get_blob``) and rewritten under ``materialize_dir`` (optionally
    ``_inputs/<port>/``).
    """
    return load_port_value(
        get_blob(uri, expected_sha256=expected_sha256),
        materialize_dir=materialize_dir,
        get_companion=get_companion,
        port=port,
    )

# Public names. A leading underscore stays private to this module.
safe_path = _safe_path
sha256_from_key = _sha256_from_key
safe_job_segment = _safe_job_segment
