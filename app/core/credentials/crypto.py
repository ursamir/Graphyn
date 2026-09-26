# app/core/credentials/crypto.py
"""At-rest sealing for credential payloads (stdlib only).

Key source (precedence):
  1. GRAPHYN_CREDENTIALS_KEY env (urlsafe base64 32-byte, or any passphrase)
  2. Generated once into {GRAPHYN_HOME}/credentials/.key (mode 0600)

Format: ``v1:`` + urlsafe_b64(nonce || tag || ciphertext)
  - keystream: SHA-256(master || nonce || counter) chunks
  - tag: HMAC-SHA256(master, nonce || ciphertext)
Never log plaintext or the master key.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path

from app.core.config import credentials_dir as _config_credentials_dir

logger = logging.getLogger(__name__)

_KEY_ENV = "GRAPHYN_CREDENTIALS_KEY"
_KEY_FILE = ".key"
_VERSION = b"v1"
_NONCE_LEN = 16
_TAG_LEN = 32


def credentials_dir() -> Path:
    """Return {GRAPHYN_HOME}/credentials/ (mode 0700)."""
    root = _config_credentials_dir()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def _derive_master(raw: bytes) -> bytes:
    """Normalize any input to a 32-byte master key via SHA-256."""
    if len(raw) == 32:
        return raw
    try:
        decoded = base64.urlsafe_b64decode(raw)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    return hashlib.sha256(raw).digest()


def _load_or_create_key() -> bytes:
    env = (os.environ.get(_KEY_ENV) or "").strip()
    if env:
        return _derive_master(env.encode("utf-8"))
    root = credentials_dir()
    path = root / _KEY_FILE
    if path.is_file():
        data = path.read_bytes().strip()
        if data:
            return _derive_master(data)
    # Generate once
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
    logger.info("credentials: generated new master key at %s (mode 0600)", path)
    return _derive_master(raw)


def _keystream(master: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(master + nonce + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def seal(plaintext: bytes) -> str:
    """Encrypt *plaintext*; return a versioned urlsafe token. Never logs input."""
    master = _load_or_create_key()
    nonce = secrets.token_bytes(_NONCE_LEN)
    stream = _keystream(master, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    tag = hmac.new(master, nonce + ciphertext, hashlib.sha256).digest()
    blob = nonce + tag + ciphertext
    return "v1:" + base64.urlsafe_b64encode(blob).decode("ascii")


def unseal(token: str) -> bytes:
    """Decrypt a seal() token. Raises CredentialError on tamper/mismatch."""
    from app.core.credentials.errors import CredentialError

    if not token or not isinstance(token, str):
        raise CredentialError("Invalid sealed credential token")
    if not token.startswith("v1:"):
        raise CredentialError("Unsupported credential seal version")
    try:
        blob = base64.urlsafe_b64decode(token[3:].encode("ascii"))
    except Exception as exc:
        raise CredentialError("Corrupt sealed credential token") from exc
    if len(blob) < _NONCE_LEN + _TAG_LEN:
        raise CredentialError("Corrupt sealed credential token")
    nonce = blob[:_NONCE_LEN]
    tag = blob[_NONCE_LEN : _NONCE_LEN + _TAG_LEN]
    ciphertext = blob[_NONCE_LEN + _TAG_LEN :]
    master = _load_or_create_key()
    expected = hmac.new(master, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise CredentialError("Credential seal authentication failed")
    stream = _keystream(master, nonce, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, stream))
