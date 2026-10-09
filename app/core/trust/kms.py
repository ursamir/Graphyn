# app/core/trust/kms.py
"""
Bounded Context:  BC6 — Trust (key management)
Responsibility:   Pluggable customer-managed key providers for credential and
                  Mode B blob master keys. Ships a working **local file** and
                  **local envelope** (CMK wraps DEK) implementation. Cloud KMS
                  (AWS/GCP) is documented as an extension point — this module
                  does **not** pretend to call cloud APIs.
Owns:             KeyProvider protocol, LocalFileKeyProvider,
                  LocalEnvelopeKeyProvider, resolve_data_key(),
                  kms_backend_name(), KmsError.
Public Surface:   resolve_data_key(purpose), kms_backend_name(), KmsError.
Must NOT:         Log key material; invent fake AWS/GCP responses.
Dependencies:     stdlib, cryptography (AES-GCM for envelope), app.core.config.
Reason To Change: New key provider or purpose string.

Purposes: ``credentials`` | ``blob``.

Configuration (see ``.env.example`` / ``docs/TRUST_MODEL.md``)::

    GRAPHYN_KMS_BACKEND=local|envelope   # default local
    # local: existing GRAPHYN_CREDENTIALS_KEY / .key / GRAPHYN_BLOB_ENCRYPTION_KEY
    # envelope:
    #   GRAPHYN_KMS_CMK_PATH=/path/to/cmk.raw   # 32-byte or passphrase file
    #   GRAPHYN_KMS_CMK=...                     # alt: env passphrase
    #   DEK sealed under {GRAPHYN_HOME}/kms/dek-{purpose}.v1

To plug AWS KMS later, implement ``KeyProvider.get_data_key(purpose)`` that
calls ``kms:Decrypt`` on a customer CMK and returns 32 raw bytes — register via
``GRAPHYN_KMS_BACKEND=aws`` in a future release (not shipped here).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

_PURPOSES = frozenset({"credentials", "blob"})


class KmsError(RuntimeError):
    """Key provider misconfiguration or unwrap failure."""


class KeyProvider(Protocol):
    def get_data_key(self, purpose: str) -> bytes:
        """Return a 32-byte data-encryption key for *purpose*."""
        ...


def _derive_32(raw: bytes) -> bytes:
    if len(raw) == 32:
        return raw
    try:
        decoded = base64.urlsafe_b64decode(raw)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    return hashlib.sha256(raw).digest()


def _read_secret_bytes(path: Path | None = None, env_name: str | None = None) -> bytes | None:
    if env_name:
        env = (os.environ.get(env_name) or "").strip()
        if env:
            return env.encode("utf-8")
    if path is not None and path.is_file():
        data = path.read_bytes().strip()
        if data:
            return data
    return None


class LocalFileKeyProvider:
    """Existing Graphyn behaviour: env or on-disk key file (no envelope)."""

    def get_data_key(self, purpose: str) -> bytes:
        purpose = str(purpose or "").strip().lower()
        if purpose not in _PURPOSES:
            raise KmsError(f"Unknown KMS purpose '{purpose}'")
        if purpose == "blob":
            raw = (os.environ.get("GRAPHYN_BLOB_ENCRYPTION_KEY") or "").strip()
            if raw:
                return _derive_32(raw.encode("utf-8"))
            if (os.environ.get("GRAPHYN_BLOB_ENCRYPTION_FALLBACK") or "").strip().lower() in (
                "1", "true", "yes", "on",
            ):
                return self.get_data_key("credentials")
            raise KmsError(
                "Blob encryption key unset (GRAPHYN_BLOB_ENCRYPTION_KEY). "
                "LocalFileKeyProvider refuses to invent a blob key."
            )
        # credentials
        env = (os.environ.get("GRAPHYN_CREDENTIALS_KEY") or "").strip()
        if env:
            return _derive_32(env.encode("utf-8"))
        from app.core.credentials.crypto import credentials_dir

        path = credentials_dir() / ".key"
        if path.is_file():
            data = path.read_bytes().strip()
            if data:
                return _derive_32(data)
        # Generate once (same as legacy crypto.py)
        raw = base64.urlsafe_b64encode(secrets.token_bytes(32))
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        log.info("kms/local: generated credentials DEK at %s", path)
        return _derive_32(raw)


class LocalEnvelopeKeyProvider:
    """CMK (customer master key) wraps a per-purpose DEK at rest (AES-GCM).

    CMK from ``GRAPHYN_KMS_CMK`` or ``GRAPHYN_KMS_CMK_PATH``. DEK files live under
    ``{GRAPHYN_HOME}/kms/``. This is real envelope encryption you can operate
    without cloud; swap the unwrap step for AWS/GCP KMS Decrypt later.
    """

    def __init__(self) -> None:
        from app.core.config import graphyn_home

        self.root = Path(graphyn_home()) / "kms"
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def _cmk(self) -> bytes:
        path_s = (os.environ.get("GRAPHYN_KMS_CMK_PATH") or "").strip()
        path = Path(path_s).expanduser() if path_s else None
        raw = _read_secret_bytes(path, "GRAPHYN_KMS_CMK")
        if not raw:
            raise KmsError(
                "Envelope KMS requires GRAPHYN_KMS_CMK or GRAPHYN_KMS_CMK_PATH "
                "(customer-managed master key). Cloud KMS is not shipped — see docs."
            )
        return _derive_32(raw)

    def _dek_path(self, purpose: str) -> Path:
        return self.root / f"dek-{purpose}.v1"

    def get_data_key(self, purpose: str) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        purpose = str(purpose or "").strip().lower()
        if purpose not in _PURPOSES:
            raise KmsError(f"Unknown KMS purpose '{purpose}'")
        cmk = self._cmk()
        path = self._dek_path(purpose)
        if path.is_file():
            blob = path.read_bytes()
            if len(blob) < 13:
                raise KmsError(f"Corrupt sealed DEK at {path}")
            nonce, ct = blob[:12], blob[12:]
            try:
                return AESGCM(cmk).decrypt(nonce, ct, purpose.encode("utf-8"))
            except Exception as exc:
                raise KmsError(f"Failed to unwrap DEK for '{purpose}' with CMK") from exc
        # Mint DEK, seal with CMK
        dek = secrets.token_bytes(32)
        nonce = secrets.token_bytes(12)
        sealed = nonce + AESGCM(cmk).encrypt(nonce, dek, purpose.encode("utf-8"))
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(sealed)
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        log.info("kms/envelope: minted sealed DEK for purpose=%s at %s", purpose, path)
        return dek


def kms_backend_name() -> str:
    return (os.environ.get("GRAPHYN_KMS_BACKEND") or "local").strip().lower() or "local"


def _provider() -> KeyProvider:
    backend = kms_backend_name()
    if backend in ("local", "file", ""):
        return LocalFileKeyProvider()
    if backend in ("envelope", "local-envelope", "byok"):
        return LocalEnvelopeKeyProvider()
    if backend in ("aws", "aws-kms", "gcp", "gcp-kms", "azure", "azure-kms"):
        raise KmsError(
            f"GRAPHYN_KMS_BACKEND={backend!r} is not shipped. "
            "Use 'local' or 'envelope' (working BYOK on this host), or implement "
            "KeyProvider.get_data_key() against your cloud KMS and wire it here. "
            "This code path refuses to fake cloud API calls."
        )
    raise KmsError(f"Unknown GRAPHYN_KMS_BACKEND={backend!r} (allowed: local, envelope)")


def resolve_data_key(purpose: str) -> bytes:
    """Resolve a 32-byte DEK for credentials or blob encryption."""
    return _provider().get_data_key(purpose)


def kms_status() -> dict:
    """Public honesty banner (no secrets)."""
    backend = kms_backend_name()
    out = {
        "backend": backend,
        "purposes": sorted(_PURPOSES),
        "cloud_kms_shipped": False,
        "envelope_available": backend in ("envelope", "local-envelope", "byok")
        or True,
        "note": (
            "Cloud KMS (AWS/GCP/Azure) is an extension point — not called from this build. "
            "Use GRAPHYN_KMS_BACKEND=envelope for local CMK-wrapped DEKs (BYOK)."
        ),
    }
    try:
        if backend in ("envelope", "local-envelope", "byok"):
            out["cmk_configured"] = bool(
                (os.environ.get("GRAPHYN_KMS_CMK") or "").strip()
                or (os.environ.get("GRAPHYN_KMS_CMK_PATH") or "").strip()
            )
    except Exception:
        pass
    return out


__all__ = [
    "KmsError",
    "KeyProvider",
    "LocalEnvelopeKeyProvider",
    "LocalFileKeyProvider",
    "kms_backend_name",
    "kms_status",
    "resolve_data_key",
]
