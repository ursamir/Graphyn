# app/api/routers/pipeline_templates.py
"""
Bounded Context:  REST API Layer
Responsibility:   Workspace template and marketplace catalog routes under /pipelines.
Owns:             /pipelines/templates/*, /pipelines/examples, marketplace search and materialize.
                  Template cards carry ``runnable`` / ``missing_node_types``
                  (vs the host node registry) and ``group`` / ``phase`` /
                  ``step_title`` from graph metadata.
Public Surface:   router — included by app.api.routers.pipelines.
Must NOT:         Run pipelines. Must not own validate or /run.
Dependencies:     fastapi, app.core.templates, app.core.host.registry_runtime
Reason To Change: Template storage or marketplace browse changes.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _templates_dir() -> Path:
    """Return the templates directory, resolved from GRAPHYN_PROJECT_DIR."""
    from app.core.config import project_dir as _project_dir
    return _project_dir() / "configs" / "templates"


def _template_meta_path(name: str) -> Path:
    return _templates_dir() / name / "meta.json"


def _template_version_path(name: str, version: str) -> Path:
    return _templates_dir() / name / f"{version}.graph.json"


def _read_template_meta(name: str) -> dict[str, Any]:
    path = _template_meta_path(name)
    if not path.exists():
        return {"name": name, "latest_version": None, "versions": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"name": name, "latest_version": None, "versions": {}}



def _load_template_graph_dict(name: str) -> dict[str, Any] | None:
    """Best-effort load of a template Graph IR dict (latest version or legacy flat)."""
    templates_dir = _templates_dir()
    meta = _read_template_meta(name)
    latest = meta.get("latest_version")
    candidates: list[Path] = []
    if isinstance(latest, str) and _SAFE_VERSION_RE.match(latest):
        candidates.append(_template_version_path(name, latest))
    candidates.append(templates_dir / f"{name}.graph.json")
    template_dir = templates_dir / name
    if template_dir.is_dir():
        versions = sorted(
            p for p in template_dir.glob("*.graph.json") if p.name != "latest.graph.json"
        )
        if versions:
            candidates.append(versions[-1])
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "nodes" in data:
                return data
        except Exception:
            continue
    return None


_SOURCE_HINTS = ("ingest", "input", "load", "read", "fetch", "dataset")
_SINK_HINTS = ("export", "write", "save", "output", "upload", "publish")


def _summarize_template(name: str) -> dict[str, Any]:
    """Card-facing fields for Templates UI (description, I/O, plugins, difficulty)."""
    from app.core.templates.example_templates import resolve_template_title

    summary: dict[str, Any] = {
        "name": name,
        "title": resolve_template_title(name),
        "description": "",
        "difficulty": None,
        "required_plugins": [],
        "inputs": [],
        "outputs": [],
        "tags": [],
        "node_count": 0,
        "node_types": [],
        # UX: can this template run on this host? (all node types registered)
        "runnable": False,
        "missing_node_types": [],
        # Multi-step example grouping (metadata.group / phase / step_title).
        "group": None,
        "phase": None,
        "step_title": None,
    }
    graph = _load_template_graph_dict(name)
    if not graph:
        return summary
    meta = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    # Synced copies may predate metadata.title in the repo source graph.
    summary["title"] = resolve_template_title(name, meta)
    summary["description"] = str(meta.get("description") or "")[:400]
    difficulty = meta.get("difficulty")
    if isinstance(difficulty, str) and difficulty.strip():
        summary["difficulty"] = difficulty.strip()
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    summary["tags"] = [str(t) for t in tags if t is not None][:12]
    plugins = meta.get("required_plugins") or meta.get("plugins") or []
    if isinstance(plugins, list):
        summary["required_plugins"] = [str(p) for p in plugins if p][:16]
    node_types: list[str] = []
    inputs: list[str] = []
    outputs: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nt = str(node.get("node_type") or "")
        if not nt:
            continue
        clean = nt.replace("Isolated_", "")
        node_types.append(clean)
        low = clean.lower()
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
        if any(h in low for h in _SOURCE_HINTS):
            path = cfg.get("path") or cfg.get("source") or cfg.get("uri") or cfg.get("url")
            inputs.append(str(path) if path else clean)
        if any(h in low for h in _SINK_HINTS):
            out = cfg.get("path") or cfg.get("destination") or cfg.get("output_dir") or clean
            outputs.append(str(out))
    # Deduplicate while preserving order
    def _uniq(items: list[str], limit: int = 8) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
            if len(out) >= limit:
                break
        return out

    summary["missing_node_types"] = _missing_node_types(node_types)
    summary["runnable"] = bool(node_types) and not summary["missing_node_types"]
    for key in ("group", "phase", "step_title"):
        val = meta.get(key)
        if isinstance(val, (str, int, float)) and not isinstance(val, bool) and str(val).strip():
            summary[key] = val.strip() if isinstance(val, str) else val
    summary["node_count"] = len(node_types)
    summary["node_types"] = _uniq(node_types, 12)
    summary["inputs"] = _uniq(inputs)
    summary["outputs"] = _uniq(outputs)
    if not summary["required_plugins"]:
        # Derive crude plugin pack hints from node type prefixes / known packs
        packs: list[str] = []
        for nt in summary["node_types"]:
            if "_" in nt:
                packs.append(nt.split("_", 1)[0].lower())
            else:
                packs.append(nt.lower())
        # Prefer unique short names that look like packs, skip generic verbs
        skip = {"dataset", "python", "http", "file", "code", "branch", "if", "map"}
        derived = [p for p in _uniq(packs, 10) if p not in skip and len(p) > 2]
        summary["required_plugins"] = derived[:8]
    return summary


def _missing_node_types(node_types: list[str]) -> list[str]:
    """Node types of a template that are not registered on this host."""
    try:
        from app.core.host.registry_runtime import get_registry

        reg = get_registry()
    except Exception:
        return []
    missing: list[str] = []
    for nt in node_types:
        if not nt or nt in missing:
            continue
        try:
            known = nt in reg or f"Isolated_{nt}" in reg
        except Exception:
            known = True
        if not known:
            missing.append(nt)
    return missing


def _write_template_meta(name: str, meta: dict[str, Any]) -> None:
    meta_path = _template_meta_path(name)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


# ── Request models ────────────────────────────────────────────────────────────

class SaveTemplateRequest(BaseModel):
    name: str
    yaml: str  # field name kept for API backward compat; value is now IR JSON string
    version: str | None = None
    description: str = ""


# ── Templates ─────────────────────────────────────────────────────────────────

@router.post("/templates/sync-examples", summary="Import example graphs as templates")
def sync_example_templates(force: bool = True):
    """Copy all ``examples/**/*.graph.json`` into the project templates directory.

    Absolute paths under the repo root are rewritten to relative paths so graphs
    run correctly from the project root. Safe to re-run (overwrites when force=true).
    """
    from app.core.templates.example_templates import sync_example_templates as _sync

    return _sync(force=force)


@router.get("/examples", summary="List bundled example Graph IR files")
def list_examples():
    """Return metadata for Graph IR examples under the repository ``examples/`` tree."""
    from app.core.templates.example_templates import discover_example_graphs

    return discover_example_graphs()


@router.get("/templates", summary="List pipeline templates")
def list_templates():
    """Return card summaries for available pipeline templates.

    Each item includes ``name`` plus optional card fields (description,
    difficulty, required_plugins, inputs, outputs, tags, node_count) derived
    from the latest Graph IR when readable.

    Supports both legacy flat templates (`{name}.graph.json`) and
    versioned templates (`{name}/{version}.graph.json` + meta.json).
    """
    templates_dir = _templates_dir()
    if not templates_dir.exists():
        return []
    names: set[str] = set()
    for f in sorted(templates_dir.glob("*.graph.json")):
        names.add(f.stem.replace(".graph", ""))
    for d in sorted(templates_dir.iterdir()):
        if d.is_dir() and _SAFE_NAME_RE.match(d.name):
            names.add(d.name)
    return [_summarize_template(name) for name in sorted(names)]


@router.get("/templates/{name}/versions", summary="List template versions")
def list_template_versions(name: str):
    """List available versions for one template.

    Supports versioned dirs (`{name}/{version}.graph.json`) and legacy flat
    files (`{name}.graph.json`). Legacy-only templates return ``versions: []``
    with ``storage: "legacy_flat"`` (HTTP 200) so clients can still open them
    via ``GET /templates/{name}`` without a version query.
    """
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    templates_dir = _templates_dir()
    template_dir = templates_dir / name
    legacy_path = templates_dir / f"{name}.graph.json"
    has_dir = template_dir.is_dir()
    has_legacy = legacy_path.is_file()
    if not has_dir and not has_legacy:
        raise HTTPException(status_code=404, detail="Template not found")

    versions: list[str] = []
    if has_dir:
        versions = sorted(
            p.stem.replace(".graph", "")
            for p in template_dir.glob("*.graph.json")
            if p.name != "latest.graph.json"
        )
    meta = _read_template_meta(name) if has_dir else {}
    latest = meta.get("latest_version") if has_dir else None
    if latest is None and versions:
        latest = versions[-1]
    return {
        "name": name,
        "latest_version": latest,
        "versions": versions,
        "storage": "versioned" if versions else ("legacy_flat" if has_legacy else "empty"),
    }


@router.get("/templates/{name}", summary="Get a pipeline template")
def get_template(name: str, version: str | None = None):
    """Return the content of a named template.

    Supports both legacy YAML payloads and IR-JSON payloads.
    """
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    if version is not None and not _SAFE_VERSION_RE.match(version):
        raise HTTPException(status_code=400, detail="Invalid template version")

    path: Path
    if version:
        path = _template_version_path(name, version)
    else:
        meta = _read_template_meta(name)
        latest = meta.get("latest_version")
        if isinstance(latest, str) and _SAFE_VERSION_RE.match(latest):
            path = _template_version_path(name, latest)
        else:
            path = _templates_dir() / f"{name}.graph.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    text = path.read_text(encoding="utf-8")
    import json as _json
    try:
        graph = _json.loads(text)
        # Always migrate legacy node aliases so the console never paints
        # obsolete types like ``input`` / ``clean`` that are not registered.
        from app.core.ir.loader import dump_ir, load_ir
        from app.core.paths.workspace_paths import apply_output_rewire

        graph = dump_ir(apply_output_rewire(load_ir(graph)))
        response = {"name": name, "graph": graph}
        if version:
            response["version"] = version
        return response
    except _json.JSONDecodeError:
        return {"name": name, "yaml": text}
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Template IR is invalid or could not be migrated: {exc}",
        ) from exc


@router.post("/templates", summary="Save a pipeline template")
def save_template(payload: SaveTemplateRequest, request: Request):
    """Save a new pipeline template as IR JSON."""
    if not _SAFE_NAME_RE.match(payload.name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    # Validate submitted template is parseable IR JSON.
    try:
        from app.core.ir.loader import load_ir  # noqa: PLC0415
        parsed = json.loads(payload.yaml)
        load_ir(parsed)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid IR JSON template: {exc}")

    from app.core.paths.workspace_paths import rewire_graph_outputs

    parsed = rewire_graph_outputs(parsed, slug=payload.name)
    body = json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"

    version = payload.version or datetime.now(timezone.utc).strftime("v%Y%m%dT%H%M%SZ")
    if not _SAFE_VERSION_RE.match(version):
        raise HTTPException(status_code=400, detail="Invalid template version")

    template_dir = _templates_dir() / payload.name
    template_dir.mkdir(parents=True, exist_ok=True)
    path = _template_version_path(payload.name, version)
    path.write_text(body, encoding="utf-8")

    # Backward-compat latest pointer for older clients.
    legacy_path = _templates_dir() / f"{payload.name}.graph.json"
    legacy_path.write_text(body, encoding="utf-8")

    meta = _read_template_meta(payload.name)
    versions = meta.get("versions", {})
    versions[version] = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "description": payload.description or "",
    }
    meta.update(
        {
            "name": payload.name,
            "latest_version": version,
            "versions": versions,
        }
    )
    _write_template_meta(payload.name, meta)
    try:
        from app.core.trust.audit import record_audit

        from app.api.actor import resolve_actor

        record_audit(
            actor=resolve_actor(request),
            action="template.save",
            resource_type="template",
            resource_id=payload.name,
            meta={"version": version, "description": payload.description or ""},
        )
    except Exception:
        pass
    return {"name": payload.name, "version": version, "saved": True}


@router.delete("/templates/{name}", summary="Delete a pipeline template")
def delete_template(name: str, version: str | None = None):
    """Delete a named pipeline template."""
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    if version is not None and not _SAFE_VERSION_RE.match(version):
        raise HTTPException(status_code=400, detail="Invalid template version")

    template_dir = _templates_dir() / name
    legacy_path = _templates_dir() / f"{name}.graph.json"

    if version:
        path = _template_version_path(name, version)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Template version not found")
        path.unlink()

        meta = _read_template_meta(name)
        versions = meta.get("versions", {})
        versions.pop(version, None)
        latest = meta.get("latest_version")
        if latest == version:
            remaining = sorted(versions.keys())
            meta["latest_version"] = remaining[-1] if remaining else None
        meta["versions"] = versions
        _write_template_meta(name, meta)
        return {"name": name, "version": version, "deleted": True}

    # Delete full template (all versions + legacy pointer)
    if not template_dir.exists() and not legacy_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    if template_dir.exists():
        for p in template_dir.glob("*.graph.json"):
            p.unlink()
        meta_path = template_dir / "meta.json"
        if meta_path.exists():
            meta_path.unlink()
        try:
            template_dir.rmdir()
        except OSError:
            pass

    if legacy_path.exists():
        legacy_path.unlink()

    if not template_dir.exists() and not legacy_path.exists():
        return {"name": name, "deleted": True}
    raise HTTPException(status_code=500, detail="Failed to delete template cleanly")


# ── Marketplace catalog (pack-first browse + materialize) ─────────────────────


class MarketplaceMaterializeBody(BaseModel):
    template_id: str
    param_overrides: dict[str, Any] | None = None
    merge_parameters_into_first: bool = False


@router.get("/marketplace/templates", summary="Search marketplace template catalog")
def search_marketplace_templates_api(
    pack: str = "",
    industry: str = "",
    modality: str = "",
    lifecycle: str = "",
    status: str = "",
    family: str = "",
    q: str = "",
    tags: str = "",
    limit: int = 25,
):
    """Filter ``docs/PIPELINE_TEMPLATE_CATALOG.json`` for console + agents.

    ``tags`` is a comma-separated list. Server-side filter — catalog is ~3k entries.
    """
    from app.core.templates.pipeline_template_materializer import search_marketplace_templates

    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    result = search_marketplace_templates(
        pack=pack,
        industry=industry,
        modality=modality,
        lifecycle=lifecycle,
        status=status,
        family=family,
        q=q,
        tags=tag_list,
        limit=limit,
    )
    if result.get("catalog_missing"):
        raise HTTPException(
            status_code=404,
            detail="Marketplace catalog missing — run scripts/generate_pipeline_template_catalog.py",
        )
    return result


@router.post("/marketplace/materialize", summary="Materialize marketplace template to Graph IR")
def materialize_marketplace_template_api(body: MarketplaceMaterializeBody):
    """Expand a marketplace template id into Graph IR 1.1 (does not save a pipeline).

    Out-of-box: seeds bundled example datasets, binds ingest paths to those seeds,
    and sanitizes config keys against the live node registry (extra=forbid).
    """
    from copy import deepcopy

    from app.core.templates.example_templates import seed_example_input_datasets
    from app.core.templates.pipeline_template_materializer import (
        find_template,
        load_marketplace_catalog,
        materialize_template_entry,
    )
    from app.core.host.registry_runtime import get_registry

    tid = (body.template_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="template_id is required")
    try:
        seed_example_input_datasets()
        catalog = load_marketplace_catalog()
        entry = find_template(tid, catalog)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Template not found: {tid}") from None

    entry = deepcopy(entry)
    overrides = body.param_overrides or {}
    if overrides:
        params = dict(entry.get("parameters") or {})
        params.update(overrides)
        entry["parameters"] = params
    try:
        try:
            registry = get_registry()
        except Exception:
            registry = None
        graph = materialize_template_entry(
            entry,
            merge_parameters_into_first=bool(body.merge_parameters_into_first),
            registry=registry,
            ensure_seed_datasets=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Materialize failed: {exc}") from exc
    return {"ok": True, "template_id": tid, "graph": graph, "status": entry.get("status")}
