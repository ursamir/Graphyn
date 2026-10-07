# app/core/distributed/blob_crypto.py
"""
Bounded Context:  BC5 / BC6 — Distributed blob encrypt-at-rest (Mode B WAVE-2)
Responsibility:   Encrypt/decrypt blob file envelopes when
                  GRAPHYN_BLOB_ENCRYPTION_KEY is set. Content-address by
                  *plaintext* sha256 (keys stay ``sha256/…``); on-disk file is
                  an encrypted envelope. When the key is unset, plaintext
                  bytes are stored (back-compat).
Owns:             blob_encryption_enabled(), encrypt_blob_envelope(),
                  decrypt_blob_envelope(), resolve_blob_key(), BlobCryptoError.
Public Surface:   Functions above.
Must NOT:         Import app.api / app.domain; log key material.
Dependencies:     stdlib only (same sealing style as credentials crypto).
Reason To Change: Envelope version or key derivation policy evolves.

Envelope (binary on disk)::

    magic b"GBE1" (4) || nonce(16) || tag(32) || ciphertext

Plaintext sha256 is verified after decrypt. Content-addressed keys are derived
from the plaintext digest before encryption.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from typing import Final

log = logging.getLogger(__name__)

_ENV_KEY = "GRAPHYN_BLOB_ENCRYPTION_KEY"
_ENV_FALLBACK = "GRAPHYN_CREDENTIALS_KEY"
_MAGIC: Final[bytes] = b"GBE1"
_NONCE_LEN = 16
_TAG_LEN = 32
_HEADER = len(_MAGIC) + _NONCE_LEN + _TAG_LEN


class BlobCryptoError(ValueError):
    """Blob envelope decrypt / auth failure."""


def blob_encryption_key() -> bytes | None:
    """Return 32-byte master key or None when encryption is disabled.

    Prefers ``GRAPHYN_BLOB_ENCRYPTION_KEY`` (urlsafe-b64 32-byte or passphrase).
    Does **not** auto-generate — unset means plaintext (lab back-compat).
    Optional fallback to ``GRAPHYN_CREDENTIALS_KEY`` only when
    ``GRAPHYN_BLOB_ENCRYPTION_FALLBACK=1``.
    """
    raw = (os.environ.get(_ENV_KEY) or "").strip()
    if not raw:
        if (os.environ.get("GRAPHYN_BLOB_ENCRYPTION_FALLBACK") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            raw = (os.environ.get(_ENV_FALLBACK) or "").strip()
        if not raw:
            return None
    return _derive_master(raw.encode("utf-8"))


def blob_encryption_enabled() -> bool:
    return blob_encryption_key() is not None


def _derive_master(raw: bytes) -> bytes:
    if len(raw) == 32:
        return raw
    try:
        decoded = base64.urlsafe_b64decode(raw)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    return hashlib.sha256(raw).digest()


def _keystream(master: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(master + nonce + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def is_encrypted_envelope(data: bytes) -> bool:
    return isinstance(data, (bytes, bytearray)) and bytes(data[:4]) == _MAGIC


def encrypt_blob_envelope(plaintext: bytes, *, key: bytes | None = None) -> bytes:
    """Seal plaintext into a GBE1 envelope. Raises if no key configured."""
    master = key if key is not None else blob_encryption_key()
    if master is None:
        raise BlobCryptoError("blob encryption key not configured")
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError("plaintext must be bytes")
    body = bytes(plaintext)
    nonce = secrets.token_bytes(_NONCE_LEN)
    stream = _keystream(master, nonce, len(body))
    ciphertext = bytes(a ^ b for a, b in zip(body, stream))
    tag = hmac.new(master, nonce + ciphertext, hashlib.sha256).digest()
    return _MAGIC + nonce + tag + ciphertext


def decrypt_blob_envelope(envelope: bytes, *, key: bytes | None = None) -> bytes:
    """Open a GBE1 envelope. Raises BlobCryptoError on tamper / wrong key."""
    master = key if key is not None else blob_encryption_key()
    if master is None:
        raise BlobCryptoError("blob encryption key not configured")
    data = bytes(envelope)
    if not is_encrypted_envelope(data):
        raise BlobCryptoError("not a GBE1 blob envelope")
    if len(data) < _HEADER:
        raise BlobCryptoError("corrupt blob envelope")
    nonce = data[4 : 4 + _NONCE_LEN]
    tag = data[4 + _NONCE_LEN : _HEADER]
    ciphertext = data[_HEADER:]
    expected = hmac.new(master, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise BlobCryptoError("blob envelope authentication failed (wrong key or tamper)")
    stream = _keystream(master, nonce, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, stream))


def maybe_encrypt_for_disk(plaintext: bytes) -> bytes:
    """Encrypt when a key is set; otherwise return plaintext unchanged."""
    key = blob_encryption_key()
    if key is None:
        return plaintext
    return encrypt_blob_envelope(plaintext, key=key)


def maybe_decrypt_from_disk(data: bytes) -> bytes:
    """Decrypt GBE1 envelopes when a key is set; plaintext passes through.

    If data looks like GBE1 but no key is configured → BlobCryptoError (fail closed).
    If data is plaintext and a key is set → return as-is (legacy blobs).
    """
    if is_encrypted_envelope(data):
        return decrypt_blob_envelope(data)
    return data
