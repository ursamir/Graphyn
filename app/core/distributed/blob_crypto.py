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
Dependencies:     stdlib, cryptography (AES-GCM + HKDF).
Reason To Change: Envelope version or key derivation policy evolves.

Envelope (binary on disk), written by :func:`encrypt_blob_envelope`::

    magic b"GBE2" (4) || key_id(8) || nonce(12) || AES-256-GCM(ciphertext||tag)

The AES key is HKDF-SHA256(master, info="graphyn-blob/v2"); ``key_id`` is the
first 8 bytes of HKDF(master, info="graphyn-blob/key-id") and is bound as AAD,
so a wrong key is reported as such and old keys
(``GRAPHYN_BLOB_ENCRYPTION_OLD_KEYS``, comma-separated) can still decrypt
after rotation. Legacy ``GBE1`` envelopes (SHA-256 keystream + HMAC) remain
readable. Plaintext sha256 is verified after decrypt by the caller.
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
_MAGIC2: Final[bytes] = b"GBE2"
_KEY_ID_LEN = 8
_GCM_NONCE_LEN = 12
_HEADER2 = len(_MAGIC2) + _KEY_ID_LEN + _GCM_NONCE_LEN
_ENV_OLD_KEYS = "GRAPHYN_BLOB_ENCRYPTION_OLD_KEYS"


class BlobCryptoError(ValueError):
    """Blob envelope decrypt / auth failure."""


def blob_encryption_key() -> bytes | None:
    """Return 32-byte master key or None when encryption is disabled.

    Uses ``app.core.trust.kms.resolve_data_key("blob")`` when a blob key is
    configured (or envelope KMS is active). Unset + local backend → plaintext
    (lab back-compat). Optional fallback to credentials key when
    ``GRAPHYN_BLOB_ENCRYPTION_FALLBACK=1``.
    """
    backend = (os.environ.get("GRAPHYN_KMS_BACKEND") or "local").strip().lower()
    raw = (os.environ.get(_ENV_KEY) or "").strip()
    if not raw and backend not in ("envelope", "local-envelope", "byok"):
        if (os.environ.get("GRAPHYN_BLOB_ENCRYPTION_FALLBACK") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            raw = (os.environ.get(_ENV_FALLBACK) or "").strip()
        if not raw:
            return None
    try:
        from app.core.trust.kms import resolve_data_key

        return resolve_data_key("blob")
    except Exception:
        # KmsError or KMS module unavailable: fall back to the raw env key.
        if raw:
            return _derive_master(raw.encode("utf-8"))
        return None


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
    """Legacy GBE1 decrypt only."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(master + nonce + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def is_encrypted_envelope(data: bytes) -> bool:
    return isinstance(data, (bytes, bytearray)) and bytes(data[:4]) in (_MAGIC, _MAGIC2)


def _hkdf(master: bytes, info: bytes, length: int = 32) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=info).derive(master)


def blob_key_id(master: bytes) -> bytes:
    """Non-secret 8-byte identifier of a master key (stored in GBE2 headers)."""
    return _hkdf(master, b"graphyn-blob/key-id", _KEY_ID_LEN)


def _old_keys() -> list[bytes]:
    raw = (os.environ.get(_ENV_OLD_KEYS) or "").strip()
    return [_derive_master(p.strip().encode("utf-8")) for p in raw.split(",") if p.strip()]


def encrypt_blob_envelope(plaintext: bytes, *, key: bytes | None = None) -> bytes:
    """Seal plaintext into a GBE2 (AES-256-GCM) envelope. Raises if no key configured."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    master = key if key is not None else blob_encryption_key()
    if master is None:
        raise BlobCryptoError("blob encryption key not configured")
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError("plaintext must be bytes")
    key_id = blob_key_id(master)
    nonce = secrets.token_bytes(_GCM_NONCE_LEN)
    sealed = AESGCM(_hkdf(master, b"graphyn-blob/v2")).encrypt(nonce, bytes(plaintext), _MAGIC2 + key_id)
    return _MAGIC2 + key_id + nonce + sealed


def _decrypt_v2(data: bytes, candidates: list[bytes]) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(data) < _HEADER2 + 16:
        raise BlobCryptoError("corrupt blob envelope")
    key_id = data[4 : 4 + _KEY_ID_LEN]
    nonce = data[4 + _KEY_ID_LEN : _HEADER2]
    for master in candidates:
        if not hmac.compare_digest(blob_key_id(master), key_id):
            continue
        try:
            return AESGCM(_hkdf(master, b"graphyn-blob/v2")).decrypt(nonce, data[_HEADER2:], _MAGIC2 + key_id)
        except InvalidTag as exc:
            raise BlobCryptoError("blob envelope authentication failed (tamper)") from exc
    raise BlobCryptoError(
        f"blob encrypted with unknown key id {key_id.hex()} "
        f"(set {_ENV_OLD_KEYS} with the previous key after rotation)"
    )


def decrypt_blob_envelope(envelope: bytes, *, key: bytes | None = None) -> bytes:
    """Open a GBE2 (or legacy GBE1) envelope. Raises BlobCryptoError on tamper / wrong key."""
    master = key if key is not None else blob_encryption_key()
    if master is None:
        raise BlobCryptoError("blob encryption key not configured")
    data = bytes(envelope)
    if data[:4] == _MAGIC2:
        return _decrypt_v2(data, [master, *([] if key is not None else _old_keys())])
    if not is_encrypted_envelope(data):
        raise BlobCryptoError("not a GBE blob envelope")
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

    If data looks like GBE1/GBE2 but no key is configured → BlobCryptoError (fail closed).
    If data is plaintext and a key is set → return as-is (legacy blobs).
    """
    if is_encrypted_envelope(data):
        return decrypt_blob_envelope(data)
    return data
