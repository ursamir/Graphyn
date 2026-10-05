# app/core/execution/dataset_refs.py
"""
Bounded Context:  BC5 Execution Runtime — graph preparation
Responsibility:   Resolve ``…/latest`` dataset-version references in node
                  config strings to the newest concrete version directory
                  (``v1``, ``v2``, ``v1.0.3`` …) *before* a run starts, so the
                  executed graph snapshot, the run record's external inputs and
                  "Replay exactly" all point at one immutable version.
Owns:             resolve_latest_refs(), newest_version_dir().
Public Surface:   resolve_latest_refs(graph) -> (graph, [resolution, …])
Must NOT:         Import app.domain; create or modify any dataset directory;
                  resolve anything that is not a path whose ``latest`` segment
                  has version-named siblings.
Dependencies:     app.core.ir.loader (dump/load), pathlib, re, logging.
Reason To Change: Version naming rules change (keep in sync with
                  app/core/mlops/dataset_versions.py), or a richer dataset
                  reference syntax (``project/version@hash``) is introduced.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"^v\d+(?:\.\d+)*$")
_LATEST = "latest"


def _version_key(name: str) -> tuple[int, ...]:
    return tuple(int(p) for p in name[1:].split("."))


def newest_version_dir(parent: Path) -> str | None:
    """Name of the newest non-empty ``v<N>(.<N>)*`` child of ``parent``, or None."""
    try:
        names = [
            c.name
            for c in parent.iterdir()
            if c.is_dir() and _VERSION_RE.match(c.name) and any(c.iterdir())
        ]
    except OSError:
        return None
    return max(names, key=_version_key) if names else None


def _resolve_string(value: str) -> str | None:
    """Concrete path for a ``…/latest[/rest]`` string, or None when not applicable."""
    if "/" not in value or "://" in value:
        return None
    parts = value.split("/")
    if _LATEST not in parts:
        return None
    idx = parts.index(_LATEST)
    if idx == 0:
        return None
    parent = Path("/".join(parts[:idx]) or "/")
    chosen = newest_version_dir(parent)
    if chosen is None:
        return None
    return "/".join(parts[:idx] + [chosen] + parts[idx + 1 :])


def _walk(obj: Any, node_id: str, key: str, out: list[dict[str, str]]) -> Any:
    if isinstance(obj, str):
        resolved = _resolve_string(obj)
        if resolved is not None and resolved != obj:
            out.append({"node_id": node_id, "key": key, "ref": obj, "resolved": resolved})
            return resolved
        return obj
    if isinstance(obj, dict):
        return {k: _walk(v, node_id, f"{key}.{k}" if key else str(k), out) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v, node_id, f"{key}[{i}]", out) for i, v in enumerate(obj)]
    return obj


def resolve_latest_refs(graph: Any) -> tuple[Any, list[dict[str, str]]]:
    """Replace ``…/latest`` dataset paths in node configs with the newest version.

    Accepts a GraphIR (returns a GraphIR) or an IR dict (returns a dict). Strings
    whose ``latest`` parent has no version-named children are left untouched, so
    the ingest node fails with its usual "path not found" message.
    """
    from app.core.ir.loader import dump_ir, load_ir

    is_dict = isinstance(graph, dict)
    data = graph if is_dict else dump_ir(graph)
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(nodes, list):
        return graph, []
    resolutions: list[dict[str, str]] = []
    new_nodes = []
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("config"), dict):
            node = {**node, "config": _walk(node["config"], str(node.get("id", "")), "", resolutions)}
        new_nodes.append(node)
    if not resolutions:
        return graph, []
    for r in resolutions:
        log.info("dataset ref %s (%s.%s) → %s", r["ref"], r["node_id"], r["key"], r["resolved"])
    new_data = {**data, "nodes": new_nodes}
    return (new_data if is_dict else load_ir(new_data)), resolutions
