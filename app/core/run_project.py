# app/core/run_project.py
"""Helpers for project / version_tag scoping on pipeline runs (Phase 2)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SAFE_PROJECT_RE = re.compile(r"^[\w\-]{1,128}$")


def normalize_project_name(value: Any) -> str | None:
    """Return a stripped project name or None if empty/invalid-looking."""
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name:
        return None
    if not _SAFE_PROJECT_RE.match(name):
        return None
    return name


def normalize_version_tag(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    tag = value.strip()
    return tag or None


def extract_project_fields_from_graph(graph: Any) -> dict[str, str]:
    """Pull project / version_tag from GraphIR metadata or node configs."""
    out: dict[str, str] = {}
    meta = getattr(graph, "metadata", None)
    if meta is not None:
        if isinstance(meta, dict):
            p = normalize_project_name(meta.get("project"))
            vt = normalize_version_tag(meta.get("version_tag"))
        else:
            p = normalize_project_name(getattr(meta, "project", None))
            vt = normalize_version_tag(getattr(meta, "version_tag", None))
        if p:
            out["project"] = p
        if vt:
            out["version_tag"] = vt

    if "project" in out and "version_tag" in out:
        return out

    nodes = getattr(graph, "nodes", None) or []
    for node in nodes:
        cfg = getattr(node, "config", None)
        if cfg is None and isinstance(node, dict):
            cfg = node.get("config")
        if not isinstance(cfg, dict):
            continue
        if "project" not in out:
            p = normalize_project_name(cfg.get("project"))
            if p:
                out["project"] = p
        if "version_tag" not in out:
            vt = normalize_version_tag(cfg.get("version_tag"))
            if vt:
                out["version_tag"] = vt
        if "project" in out and "version_tag" in out:
            break
    return out


def extract_project_fields_from_payload(payload: dict[str, Any], graph: Any = None) -> dict[str, str]:
    """Resolve project fields from request body and/or loaded graph."""
    out: dict[str, str] = {}
    if isinstance(payload, dict):
        p = normalize_project_name(payload.get("project"))
        if p:
            out["project"] = p
        vt = normalize_version_tag(payload.get("version_tag"))
        if vt:
            out["version_tag"] = vt
        # Optional train→package lineage (Edge wizard / accountable packaging)
        src = payload.get("source_run_id")
        if isinstance(src, str) and src.strip():
            cleaned = src.strip()
            if re.match(r"^[A-Za-z0-9_-]{4,128}$", cleaned):
                out["source_run_id"] = cleaned
        art = payload.get("source_artifact_id")
        if isinstance(art, str) and art.strip():
            cleaned_a = art.strip()
            if re.match(r"^[A-Za-z0-9_-]{4,128}$", cleaned_a):
                out["source_artifact_id"] = cleaned_a
        meta = payload.get("metadata")
        if isinstance(meta, dict):
            if "project" not in out:
                p = normalize_project_name(meta.get("project"))
                if p:
                    out["project"] = p
            if "version_tag" not in out:
                vt = normalize_version_tag(meta.get("version_tag"))
                if vt:
                    out["version_tag"] = vt
    if graph is not None:
        from_graph = extract_project_fields_from_graph(graph)
        if "project" not in out and "project" in from_graph:
            out["project"] = from_graph["project"]
        if "version_tag" not in out and "version_tag" in from_graph:
            out["version_tag"] = from_graph["version_tag"]
    return out


def infer_project_from_graph_file(run_path: Path) -> dict[str, str]:
    """Soft-upgrade: read project fields from journal graph.json when meta lacks them."""
    graph_path = run_path / "graph.json"
    if not graph_path.is_file():
        return {}
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    meta = data.get("metadata")
    if isinstance(meta, dict):
        p = normalize_project_name(meta.get("project"))
        if p:
            out["project"] = p
        vt = normalize_version_tag(meta.get("version_tag"))
        if vt:
            out["version_tag"] = vt
    if "project" in out:
        return out
    nodes = data.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            cfg = node.get("config")
            if not isinstance(cfg, dict):
                continue
            p = normalize_project_name(cfg.get("project"))
            if p:
                out["project"] = p
                vt = normalize_version_tag(cfg.get("version_tag"))
                if vt:
                    out["version_tag"] = vt
                break
    return out


def resolve_run_project(meta: dict[str, Any], run_path: Path | None = None) -> str | None:
    """Authoritative project for a run: meta.project, else inferred from graph.json."""
    p = normalize_project_name(meta.get("project"))
    if p:
        return p
    if run_path is not None:
        inferred = infer_project_from_graph_file(run_path)
        return inferred.get("project")
    return None


def project_matches(meta: dict[str, Any], project: str, run_path: Path | None = None) -> bool:
    """Hard match: resolved project equals the filter (exact, case-sensitive after strip)."""
    needle = normalize_project_name(project)
    if not needle:
        return True
    resolved = resolve_run_project(meta, run_path)
    return resolved == needle
