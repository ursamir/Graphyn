# app/core/runs/run_dataset.py
"""
Bounded Context:  BC6 — Observability & Storage (dataset provenance)
Responsibility:   Describe which data a dataset-ingest node actually read
                  (configured path, resolved dir, clip count, fallback).
Owns:             is_ingest_node_type(), ingest_dataset_info(),
                  ingest_node_end_extra() — the ``dataset`` block attached
                  to ingest ``node_end`` events and run summaries.
Public Surface:   is_ingest_node_type, ingest_dataset_info, ingest_node_end_extra
Must NOT:         Import app.domain / app.api; raise into the executor
                  (all helpers are best-effort and return None on failure).
Dependencies:     stdlib (pathlib); app.core.paths.workspace_paths (lazy).
Reason To Change: Ingest config keys or fallback resolution rules change.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def is_ingest_node_type(node_type: str | None) -> bool:
    low = str(node_type or "").lower().replace("isolated_", "")
    return "ingest" in low


def _cfg_dict(config: Any) -> dict[str, Any]:
    if isinstance(config, dict):
        return config
    if config is not None and hasattr(config, "model_dump"):
        try:
            data = config.model_dump()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _workspace_rel(path: Path) -> str:
    try:
        from app.core.config import project_dir

        rel = path.resolve().relative_to(project_dir().resolve())
        return "workspace/" + rel.as_posix()
    except Exception:
        return str(path)


def _direct_candidates(raw: str) -> list[Path]:
    """Locations that ARE the configured path (no example-data substitution)."""
    text = raw.strip()
    variants = [text]
    parts = [p for p in Path(text).parts if p != "latest"]
    if parts and len(parts) != len(Path(text).parts):
        variants.append(str(Path(*parts)))
    out: list[Path] = []
    try:
        from app.core.config import project_dir

        root = project_dir()
    except Exception:
        root = None
    for v in variants:
        p = Path(v)
        out.append(p)
        if not p.is_absolute():
            out.append(Path.cwd() / v)
            if root is not None:
                out.append(root / v)
                vp = p.parts
                if vp and vp[0] == "workspace" and len(vp) > 1:
                    out.append(root / Path(*vp[1:]))
    return out


def ingest_dataset_info(
    config: Any,
    clip_count: int | None = None,
    *,
    resolve: bool = True,
) -> dict[str, Any] | None:
    """Return ``{source_path, resolved_path, source_type, clip_count, fallback_used}``.

    ``fallback_used`` is True when the configured filesystem path was missing
    or empty and :func:`resolve_ingest_dir` substituted another directory
    (e.g. the bundled example clips). None when it cannot be determined.
    """
    cfg = _cfg_dict(config)
    source_type = str(cfg.get("source_type") or "filesystem")
    raw = cfg.get("path") or ""
    if source_type == "manifest":
        raw = cfg.get("manifest_path") or raw
    if source_type == "huggingface":
        raw = cfg.get("hf_dataset") or cfg.get("dataset") or raw
    source_path = str(raw or "").strip() or None
    info: dict[str, Any] = {
        "source_path": source_path,
        "resolved_path": None,
        "source_type": source_type,
        "clip_count": int(clip_count) if isinstance(clip_count, int) else None,
        "fallback_used": None,
    }
    if resolve and source_type == "filesystem" and source_path:
        try:
            from app.core.paths.workspace_paths import resolve_ingest_dir

            resolved = resolve_ingest_dir(source_path)
            info["resolved_path"] = _workspace_rel(resolved)
            target = resolved.resolve()
            info["fallback_used"] = not any(
                c.exists() and c.resolve() == target for c in _direct_candidates(source_path)
            )
        except FileNotFoundError:
            info["fallback_used"] = None
        except Exception:
            pass
    return info


def ingest_node_end_extra(
    node: Any, node_type: str | None, port_counts: dict[str, int] | None
) -> dict[str, Any] | None:
    """Extra ``node_end`` fields for ingest nodes: ``{"dataset": {...}}``."""
    if not is_ingest_node_type(node_type):
        return None
    try:
        counts = port_counts or {}
        clip_count = counts.get("output")
        if clip_count is None and counts:
            clip_count = sum(int(v) for v in counts.values())
        info = ingest_dataset_info(getattr(node, "config", None), clip_count)
        return {"dataset": info} if info else None
    except Exception:
        return None


__all__ = ["ingest_dataset_info", "ingest_node_end_extra", "is_ingest_node_type"]
