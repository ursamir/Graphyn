# app/core/paths/write_paths.py
"""
Bounded Context:  Execution Runtime / Workspace
Responsibility:   Create filesystem write destinations for every node, in one
                  place, instead of each plugin mkdir'ing its own output_path.
Owns:             WRITE_CONFIG_KEYS, ensure_write_destination, ensure_node_write_dirs,
                  jail_relative_path (plugin file-path jail),
                  jail_read_path (read jail; follows workspace links into examples/).
Public Surface:   ensure_node_write_dirs, ensure_write_destination, WRITE_CONFIG_KEYS,
                  jail_relative_path.
Must NOT:         Create ingest/read directories (path, model_path). Must not
                  mkdir outside the project directory jail.
Dependencies:     pathlib; app.core.config.project_dir.
Reason To Change: New write-config key names or jail roots.

Output *ports* carry typed values to the next node. Output *folders* are
config keys (output_path, output_dir, …). The engine mkdirs those before
process() for in-process and isolated workers alike.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

WRITE_CONFIG_KEYS = frozenset(
    {
        "output_path",
        "output_dir",
        "export_dir",
        "dest_dir",
        "destination_dir",
        "save_dir",
        "checkpoint_dir",
    }
)

_FILE_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".json",
        ".keras",
        ".tflite",
        ".onnx",
        ".h5",
        ".pb",
        ".csv",
        ".wav",
        ".txt",
        ".md",
        ".zip",
        ".npy",
        ".npz",
        ".pt",
        ".pth",
        ".ckpt",
    }
)


def _project_root() -> Path:
    from app.core.config import project_dir

    return project_dir().resolve()


def _resolve_under_project(raw: str) -> Path | None:
    text = (raw or "").replace("\\", "/").strip()
    if not text:
        return None
    path = Path(text)
    root = _project_root()
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(Path.cwd() / path)
        parts = path.parts
        if parts and parts[0] == "workspace":
            # Prefer project-relative path when IR uses workspace/… prefix (P2-26).
            candidates.append(root / Path(*parts[1:]))
        candidates.append(root / path)
        if parts and parts[0] == "artifacts":
            candidates.append(root / path)
    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        try:
            if resolved == root or resolved.is_relative_to(root):
                return resolved
        except (ValueError, OSError):
            continue
    return None


def jail_relative_path(raw: str, *, what: str = "path") -> Path:
    """Resolve a plugin-supplied *relative* path inside the project directory.

    Rejects absolute paths (POSIX or drive-letter), any ``..`` segment, and
    anything that resolves (after symlinks) outside ``project_dir()``. Used by
    workflow plugins (csv_table, object_store) that read/write user-named
    files. Raises ``ValueError``; never creates directories.
    """
    text = (raw or "").replace("\\", "/").strip()
    if not text:
        raise ValueError(f"{what} is required")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":") or text.startswith("~"):
        raise ValueError(f"{what} must be relative to the workspace (got an absolute path)")
    if any(part == ".." for part in text.split("/")):
        raise ValueError(f"{what} must not contain '..'")
    resolved = _resolve_under_project(text)
    if resolved is None:
        raise ValueError(f"{what} resolves outside the workspace")
    return resolved


def _trusted_read_roots() -> list[Path]:
    """Read-only roots a *workspace symlink* may point into (F19 / F-19).

    Template sync links ``workspace/datasets/input/<slug>`` to the bundled
    ``examples/<folder>/data`` seed tree. Those links live inside the workspace
    but resolve outside it; reading through them is safe (shipped sample data),
    writing is not, so only :func:`jail_read_path` honours these roots.
    """
    roots: list[Path] = []
    try:
        from app.core.templates.example_templates import examples_dir

        roots.append(examples_dir().resolve())
    except Exception:  # pragma: no cover - import guard
        pass
    env = os.environ.get("GRAPHYN_EXAMPLES_DIR", "").strip()
    if env:
        try:
            roots.append(Path(env).resolve())
        except OSError:
            pass
    return roots


def jail_read_path(raw: str, *, what: str = "path") -> Path:
    """Resolve a relative path for **reading** inside the workspace.

    Same lexical rules as :func:`jail_relative_path` (no absolute paths, no
    ``..``). The path must exist *lexically* under the workspace; it may be (or
    pass through) a symlink whose target is inside the workspace or inside the
    bundled ``examples/`` seed tree (see :func:`_trusted_read_roots`). A
    ``workspace/`` prefix is accepted once and never doubled. Raises
    ``ValueError`` (outside the jail) or ``FileNotFoundError`` (missing).
    """
    text = (raw or "").replace("\\", "/").strip()
    if not text:
        raise ValueError(f"{what} is required")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":") or text.startswith("~"):
        raise ValueError(f"{what} must be relative to the workspace (got an absolute path)")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError(f"{what} must not contain '..'")
    root = _project_root()
    lexical: list[Path] = []
    if parts and parts[0] == "workspace" and len(parts) > 1:
        lexical.append(root.joinpath(*parts[1:]))
    lexical.append(root.joinpath(*parts))
    allowed = [root, *_trusted_read_roots()]
    rejected = False
    for cand in lexical:
        if not os.path.lexists(cand):
            continue
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if any(resolved == r or resolved.is_relative_to(r) for r in allowed):
            if not resolved.exists():
                raise FileNotFoundError(f"{what}: {text!r} is a dangling link")
            return resolved
        rejected = True
    if rejected:
        raise ValueError(f"{what} resolves outside the workspace")
    raise FileNotFoundError(f"{what}: {text!r} not found in the workspace")


def ensure_write_destination(raw: str) -> Path | None:
    """mkdir a write destination (file parent or directory) if it is jailed.

    File-like suffixes mkdir the parent. Directory-like values mkdir themselves.
    Returns the created/existing directory, or None if the path is outside jail.
    """
    resolved = _resolve_under_project(raw)
    if resolved is None:
        log.debug("write_paths: skip mkdir outside project dir: %s", raw)
        return None
    target = resolved.parent if resolved.suffix.lower() in _FILE_SUFFIXES else resolved
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("write_paths: could not create %s: %s", target, exc)
        return None
    return target


def _config_mapping(node: Any) -> dict[str, Any]:
    cfg = getattr(node, "config", None)
    if cfg is None:
        return {}
    if isinstance(cfg, dict):
        return cfg
    dump = getattr(cfg, "model_dump", None)
    if callable(dump):
        data = dump()
        return data if isinstance(data, dict) else {}
    out: dict[str, Any] = {}
    for key in WRITE_CONFIG_KEYS:
        if hasattr(cfg, key):
            out[key] = getattr(cfg, key)
    return out


def ensure_node_write_dirs(node: Any) -> list[str]:
    """Create every jailed write directory declared on ``node.config``."""
    created: list[str] = []
    for key, value in _config_mapping(node).items():
        if key not in WRITE_CONFIG_KEYS:
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        dest = ensure_write_destination(value)
        if dest is not None:
            created.append(str(dest))
    return created
