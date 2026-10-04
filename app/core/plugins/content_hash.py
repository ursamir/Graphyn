# app/core/plugins/content_hash.py
"""
Bounded Context:  BC3 — Node Catalog (Plugin Ecosystem)
Responsibility:   Deterministic content hash of a plugin source / install
                  tree, and a requirements signature of a manifest, so
                  startup can detect "same version, different code" drift and
                  decide between a code-only refresh and a full reinstall.
Owns:             plugin_tree_hash(), requirements_signature(),
                  HASH_EXCLUDED_DIRS, HASH_EXCLUDED_SUFFIXES
Public Surface:   plugin_tree_hash, requirements_signature
Must NOT:         Import from app.domain or app.api; touch the filesystem
                  other than reading the tree being hashed.
Dependencies:     stdlib (hashlib, os, pathlib)
Reason To Change: The set of files that count as plugin "code" changes, or the
                  manifest fields that define a plugin venv change.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Iterable

# Directory names never part of plugin code (bytecode, VCS, local venvs, tool caches).
HASH_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        "venv",
        ".venv",
        "env",
        ".env",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "node_modules",
    }
)
HASH_EXCLUDED_SUFFIXES: tuple[str, ...] = (".pyc", ".pyo")
HASH_EXCLUDED_FILES: frozenset[str] = frozenset({".DS_Store"})

_CHUNK = 1 << 20


def _is_venv_dir(path: Path) -> bool:
    """True for any virtualenv root (has ``pyvenv.cfg``), whatever its name."""
    return (path / "pyvenv.cfg").is_file()


def _iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        # Prune in place (sorted for a stable walk; final order is sorted anyway).
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in HASH_EXCLUDED_DIRS
            and not d.endswith(".__backup__")
            and not d.endswith(".__staging__")
            and not _is_venv_dir(here / d)
        )
        for name in filenames:
            if name in HASH_EXCLUDED_FILES or name.endswith(HASH_EXCLUDED_SUFFIXES):
                continue
            yield here / name


def plugin_tree_hash(root: str | os.PathLike[str]) -> str:
    """Return a hex SHA-256 over the code files under *root*.

    Deterministic: files are hashed in sorted POSIX relative-path order and
    each entry contributes ``relpath NUL sha256(content) NUL``. Excludes
    ``__pycache__``, ``*.pyc``/``*.pyo``, VCS dirs, and virtualenv dirs.
    Symlinks are hashed by their target string (never followed).
    Raises ``FileNotFoundError`` when *root* is not a directory.
    """
    base = Path(root)
    if not base.is_dir():
        raise FileNotFoundError(f"plugin tree not found: {base}")
    entries: list[tuple[str, str]] = []
    for path in _iter_files(base):
        rel = path.relative_to(base).as_posix()
        h = hashlib.sha256()
        if path.is_symlink():
            h.update(b"symlink:")
            h.update(os.readlink(path).encode("utf-8", "surrogateescape"))
        else:
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(_CHUNK), b""):
                    h.update(chunk)
        entries.append((rel, h.hexdigest()))
    entries.sort()
    total = hashlib.sha256()
    for rel, digest in entries:
        total.update(rel.encode("utf-8", "surrogateescape"))
        total.update(b"\0")
        total.update(digest.encode("ascii"))
        total.update(b"\0")
    return total.hexdigest()


def requirements_signature(manifest: Any) -> tuple:
    """What determines a plugin's (isolated) venv contents.

    Accepts a ``PluginManifest`` or the ``record.manifest`` dict. Two
    manifests with the same signature can share an existing venv, so a
    same-version code change only needs the code recopied.
    """
    if isinstance(manifest, dict):
        get = manifest.get
    else:
        def get(key: str, default: Any = None) -> Any:
            return getattr(manifest, key, default)

    deps = sorted(str(d).strip() for d in (get("dependencies", None) or []))
    opt = sorted(str(d).strip() for d in (get("optional_dependencies", None) or []))
    runtime = str(get("runtime", None) or "inprocess")
    min_python = get("min_python", None)
    return (runtime, tuple(deps), tuple(opt), min_python)
