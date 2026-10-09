# app/core/mlops/ship_signing.py
"""
Bounded Context:  BC6 — Ship packages / supply-chain integrity
Responsibility:   Ed25519 signing + verification of ship package manifests
                  (F19 / F-14). Packages are signed by default; the old
                  ``dev-unsigned`` placeholder is only produced on explicit
                  opt-in and can never be promoted to prod.
Public Surface:   signing_key_path(), public_key_info(), sign_manifest(man),
                  verify_manifest(man, archive_path) -> dict, signed_payload(man)
Must NOT:         Import app.api; log or return private key material.
Dependencies:     cryptography (Ed25519), stdlib.

Key: ``GRAPHYN_SHIP_SIGNING_KEY`` (path to a PEM Ed25519 private key) or,
when unset, ``{GRAPHYN_HOME}/keys/ship_signing_ed25519.pem`` generated on
first use (dir 0700, file 0600). ``key_id`` = ``ed25519:`` + first 16 hex of
sha256(raw public key). Additional trusted public keys (rotation) may be
dropped as PEM files in ``{GRAPHYN_HOME}/keys/ship_trusted/``.

Signed payload = canonical JSON (sorted keys, no spaces) of
``{package_id, archive_sha256, runtime, model_format, files:[{path, sha256}]}``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
ALG = "ed25519"


def signing_key_path() -> Path:
    env = (os.environ.get("GRAPHYN_SHIP_SIGNING_KEY") or "").strip()
    if env:
        return Path(env).expanduser()
    from app.core.config import graphyn_home

    return graphyn_home() / "keys" / "ship_signing_ed25519.pem"


def _trusted_dir() -> Path:
    from app.core.config import graphyn_home

    return graphyn_home() / "keys" / "ship_trusted"


def _load_or_create_private_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    path = signing_key_path()
    with _LOCK:
        if path.is_file():
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError(f"ship signing key at {path} is not an Ed25519 private key")
            return key
        if (os.environ.get("GRAPHYN_SHIP_SIGNING_KEY") or "").strip():
            raise FileNotFoundError(f"GRAPHYN_SHIP_SIGNING_KEY points to a missing file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(pem)
        return key


def _raw_public(pub) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _key_id(pub) -> str:
    return f"{ALG}:" + hashlib.sha256(_raw_public(pub)).hexdigest()[:16]


def public_key_info() -> dict[str, Any]:
    """Public half of the active signing key (safe to publish)."""
    from cryptography.hazmat.primitives import serialization

    pub = _load_or_create_private_key().public_key()
    pem = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return {"alg": ALG, "key_id": _key_id(pub), "public_key_pem": pem.decode("ascii")}


def _trusted_public_keys() -> dict[str, Any]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    keys: dict[str, Any] = {}
    pub = _load_or_create_private_key().public_key()
    keys[_key_id(pub)] = pub
    tdir = _trusted_dir()
    if tdir.is_dir():
        for f in sorted(tdir.glob("*.pem")):
            try:
                k = serialization.load_pem_public_key(f.read_bytes())
            except Exception:
                continue
            if isinstance(k, Ed25519PublicKey):
                keys[_key_id(k)] = k
    return keys


def signed_payload(man: dict[str, Any]) -> bytes:
    files = [
        {"path": str(f.get("path")), "sha256": str(f.get("sha256"))}
        for f in (man.get("files") or [])
        if isinstance(f, dict)
    ]
    body = {
        "package_id": man.get("package_id"),
        "archive_sha256": (man.get("checksums") or {}).get("sha256"),
        "runtime": man.get("runtime"),
        "model_format": (man.get("model_ref") or {}).get("format"),
        "files": sorted(files, key=lambda f: f["path"]),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(man: dict[str, Any], *, actor: str = "") -> dict[str, Any]:
    """Return a signature record for *man* (does not mutate it)."""
    key = _load_or_create_private_key()
    payload = signed_payload(man)
    sig = key.sign(payload)
    return {
        "alg": ALG,
        "key_id": _key_id(key.public_key()),
        "value": base64.b64encode(sig).decode("ascii"),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "signed_at": datetime.now(timezone.utc).isoformat(),
        "signed_by": actor or None,
    }


def real_signatures(man: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in (man.get("signatures") or []) if isinstance(s, dict) and s.get("alg") == ALG]


def verify_manifest(man: dict[str, Any], archive_path: Path | None = None) -> dict[str, Any]:
    """Verify archive checksum + Ed25519 signature(s). Never raises for bad input."""
    from cryptography.exceptions import InvalidSignature

    result: dict[str, Any] = {"signed": False, "valid": False, "checksum_ok": None, "key_id": None, "reason": ""}
    if archive_path is not None:
        try:
            h = hashlib.sha256()
            with Path(archive_path).open("rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            result["checksum_ok"] = h.hexdigest() == (man.get("checksums") or {}).get("sha256")
        except OSError as exc:
            result["checksum_ok"] = False
            result["reason"] = f"archive unreadable: {exc}"
            return result
        if not result["checksum_ok"]:
            result["reason"] = "archive sha256 does not match the manifest"
            return result
    sigs = real_signatures(man)
    if not sigs:
        result["reason"] = "package is unsigned"
        return result
    result["signed"] = True
    trusted = _trusted_public_keys()
    payload = signed_payload(man)
    for s in sigs:
        pub = trusted.get(str(s.get("key_id")))
        if pub is None:
            result["reason"] = f"signing key {s.get('key_id')} is not trusted"
            continue
        try:
            pub.verify(base64.b64decode(str(s.get("value") or "")), payload)
        except (InvalidSignature, ValueError):
            result["reason"] = "signature does not match the manifest"
            continue
        result.update({"valid": True, "key_id": s.get("key_id"), "reason": ""})
        return result
    return result


__all__ = [
    "ALG",
    "public_key_info",
    "real_signatures",
    "sign_manifest",
    "signed_payload",
    "signing_key_path",
    "verify_manifest",
]
