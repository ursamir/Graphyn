# app/core/write_paths.py
"""
Bounded Context:  Execution Runtime / Workspace
Responsibility:   Create filesystem write destinations for every node, in one
                  place, instead of each plugin mkdir'ing its own output_path.
Owns:             WRITE_CONFIG_KEYS, ensure_write_destination, ensure_node_write_dirs.
Public Surface:   ensure_node_write_dirs, ensure_write_destination, WRITE_CONFIG_KEYS.
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
        candidates.append(root / path)
        parts = path.parts
        if parts and parts[0] == "workspace":
            candidates.append(root / Path(*parts[1:]))
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
