# app/core/project_pipelines.py
"""
Bounded Context:  BC6 — Observability & Storage / project assets
Responsibility:   Persist project-owned Graph IR under
                  workspace/datasets/output/{project}/pipelines/{name}.graph.json.
Owns:             list/get/put/delete helpers, name validation.
Public Surface:   SAFE_PIPELINE_NAME_RE, pipelines_dir, list_pipelines,
                  get_pipeline, put_pipeline, delete_pipeline.
Must NOT:         Import app.domain (callers pass project Path) or app.api.
Dependencies:     json, re, pathlib, tempfile; app.core.ir.loader;
                  app.core.ir.secret_policy.
Reason To Change: Project pipeline storage layout or validation rules change.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.ir.loader import dump_ir, load_ir
from app.core.ir.secret_policy import assert_no_inline_secrets

log = logging.getLogger(__name__)

SAFE_PIPELINE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def pipelines_dir(project_dir: Path) -> Path:
    return project_dir / "pipelines"


def _validate_pipeline_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or not SAFE_PIPELINE_NAME_RE.match(cleaned):
        raise ValueError(
            f"Invalid pipeline name {name!r}. "
            "Use letters, digits, hyphens, and underscores only."
        )
    return cleaned


def _pipeline_path(project_dir: Path, name: str) -> Path:
    safe = _validate_pipeline_name(name)
    base = pipelines_dir(project_dir).resolve()
    path = (base / f"{safe}.graph.json").resolve()
    if not str(path).startswith(str(base) + "/") and path.parent != base:
        raise ValueError("Invalid pipeline path")
    return path


def list_pipelines(project_dir: Path) -> list[dict[str, Any]]:
    """Return summaries for ``*.graph.json`` under the project pipelines dir."""
    root = pipelines_dir(project_dir)
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.graph.json")):
        name = path.name[: -len(".graph.json")]
        if not SAFE_PIPELINE_NAME_RE.match(name):
            continue
        meta_name = None
        node_count = 0
        updated_at = None
        try:
            updated_at = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            updated_at = None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                nodes = data.get("nodes")
                node_count = len(nodes) if isinstance(nodes, list) else 0
                md = data.get("metadata")
                if isinstance(md, dict):
                    meta_name = md.get("name")
        except Exception:
            log.debug("Skipping unreadable pipeline %s", path, exc_info=True)
        items.append(
            {
                "name": name,
                "updated_at": updated_at,
                "node_count": node_count,
                "graph_name": meta_name,
            }
        )
    return items


def get_pipeline(project_dir: Path, name: str) -> dict[str, Any]:
    path = _pipeline_path(project_dir, name)
    if not path.is_file():
        raise FileNotFoundError(f"Pipeline '{name}' not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to read pipeline '{name}': {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid pipeline '{name}'")
    # Validate shape
    load_ir(data)
    return data


def put_pipeline(
    project_dir: Path,
    name: str,
    payload: dict[str, Any],
    *,
    project_name: str,
) -> dict[str, Any]:
    """Validate, stamp project, and atomically write the pipeline Graph IR."""
    if not isinstance(payload, dict):
        raise ValueError("Pipeline body must be a Graph IR object")
    graph = load_ir(payload)
    assert_no_inline_secrets(graph)

    meta = graph.metadata
    updates: dict[str, Any] = {"project": project_name}
    if not getattr(meta, "name", None):
        updates["name"] = name
    new_meta = meta.model_copy(update=updates)
    graph = graph.model_copy(update={"metadata": new_meta})
    assert_no_inline_secrets(graph)

    out = dump_ir(graph)
    path = _pipeline_path(project_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
            fh.write("\n")
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return out


def delete_pipeline(project_dir: Path, name: str) -> None:
    path = _pipeline_path(project_dir, name)
    if not path.is_file():
        raise FileNotFoundError(f"Pipeline '{name}' not found")
    path.unlink()
