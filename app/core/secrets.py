# app/core/secrets.py
"""Local file-backed named secret store under GRAPHYN_HOME/secrets.

API/MCP list endpoints must never return secret values — names only.
Nodes resolve provider keys via resolve_secret() (store, then process env).
"""
from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path

from app.core.config import secrets_dir

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SecretError(ValueError):
    """Invalid secret name or empty value."""


def validate_secret_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or not _NAME_RE.match(cleaned):
        raise SecretError(
            f"Invalid secret name {name!r}. Use an env-style identifier "
            "(e.g. OPENAI_API_KEY, DEEPGRAM_API_KEY)."
        )
    return cleaned


def _secret_path(name: str) -> Path:
    return secrets_dir() / validate_secret_name(name)


def _ensure_dir() -> Path:
    root = secrets_dir()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def list_secret_names() -> list[str]:
    """Return stored secret names only (never values)."""
    root = secrets_dir()
    if not root.exists():
        return []
    names = []
    for p in sorted(root.iterdir()):
        if p.is_file() and not p.name.startswith(".") and _NAME_RE.match(p.name):
            names.append(p.name)
    return names


def get_secret(name: str) -> str:
    """Return the stored value for *name*, or empty string if missing."""
    path = _secret_path(name)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").rstrip("\r\n")
    except OSError:
        return ""


def set_secret(name: str, value: str) -> str:
    """Write *value* to a 0600 file. Returns the name. Never logs the value."""
    cleaned = validate_secret_name(name)
    if value is None or str(value) == "":
        raise SecretError(f"Secret {cleaned} value must not be empty.")
    text = str(value)
    if text.endswith("\n") and text.count("\n") == 1:
        text = text[:-1]
    if not text:
        raise SecretError(f"Secret {cleaned} value must not be empty.")
    root = _ensure_dir()
    dest = root / cleaned
    fd, tmp = tempfile.mkstemp(prefix=f".{cleaned}.", dir=str(root), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
        os.chmod(dest, 0o600)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return cleaned


def delete_secret(name: str) -> bool:
    path = _secret_path(name)
    if not path.is_file():
        return False
    path.unlink()
    return True


def resolve_secret(name: str) -> str:
    """Resolve a named credential: secret store first, then process env.

    Does not raise on miss — callers fail closed with a named error.
    """
    cleaned = (name or "").strip()
    if not cleaned:
        return ""
    try:
        stored = get_secret(cleaned)
    except SecretError:
        stored = ""
    if stored:
        return stored
    return os.environ.get(cleaned, "").strip()


def file_mode(name: str) -> int | None:
    path = secrets_dir() / validate_secret_name(name)
    if not path.is_file():
        return None
    return stat.S_IMODE(path.stat().st_mode)
