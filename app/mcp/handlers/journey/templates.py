# app/mcp/handlers/journey/templates.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Template list/get/instantiate and marketplace search MCP tools.
Owns:             template and marketplace-search handlers and schemas
Public Surface:   *_handler, *_DESCRIPTION, *_SCHEMA in this module
Must NOT:         Import app.domain except through journey.common; never return secret values.
Dependencies:     app.mcp.handlers.journey.common and the core package this tool calls.
Reason To Change: That MCP tool's arguments or result shape change.
"""
from __future__ import annotations

from typing import Any

from app.mcp.handlers.journey.common import handler_error, meta_props, require_project_dir

# ── Templates (J1) ────────────────────────────────────────────────────────────

LIST_TEMPLATES_DESCRIPTION = "List available pipeline templates."
LIST_TEMPLATES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {**meta_props()},
    "additionalProperties": False,
}

GET_TEMPLATE_DESCRIPTION = "Get a pipeline template graph by name (optional version)."
GET_TEMPLATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "version": {"type": "string"},
        **meta_props(),
    },
    "required": ["name"],
    "additionalProperties": False,
}

INSTANTIATE_TEMPLATE_DESCRIPTION = (
    "Copy a template graph into a workspace pipeline draft (instantiate)."
)
INSTANTIATE_TEMPLATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Template name"},
        "project": {"type": "string"},
        "pipeline": {"type": "string", "description": "Destination pipeline name"},
        "version": {"type": "string"},
        **meta_props(),
    },
    "required": ["name", "project", "pipeline"],
    "additionalProperties": False,
}


def _templates_dir():
    from app.core.config import project_dir

    return project_dir() / "configs" / "templates"


def _load_template_graph(name: str, version: str | None = None) -> dict[str, Any]:
    import json
    from pathlib import Path

    templates_dir = _templates_dir()
    candidates: list[Path] = []
    if version:
        candidates.append(templates_dir / name / f"{version}.graph.json")
    else:
        tdir = templates_dir / name
        if tdir.is_dir():
            versions = sorted(tdir.glob("*.graph.json"))
            if versions:
                candidates.append(versions[-1])
        candidates.append(templates_dir / f"{name}.graph.json")
    for path in candidates:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            raise ValueError("Template is not a graph object")
    raise FileNotFoundError(f"Template '{name}' not found")


def list_templates_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import json

    templates_dir = _templates_dir()
    if not templates_dir.exists():
        return {"templates": [], "count": 0}
    items: list[dict[str, Any]] = []
    for f in sorted(templates_dir.glob("*.graph.json")):
        items.append({"name": f.name[: -len(".graph.json")], "kind": "legacy"})
    for d in sorted(templates_dir.iterdir()):
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        meta: dict[str, Any] = {"name": d.name, "kind": "versioned"}
        if meta_path.is_file():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    meta.update(loaded)
            except Exception:
                pass
        versions = [p.stem for p in sorted(d.glob("*.graph.json"))]
        meta["versions"] = versions
        items.append(meta)
    return {"templates": items, "count": len(items)}


def get_template_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments or {}
    name = str(args.get("name") or "").strip()
    version = args.get("version")
    version_s = str(version).strip() if isinstance(version, str) and version.strip() else None
    try:
        graph = _load_template_graph(name, version_s)
        return {"name": name, "version": version_s, "graph": graph}
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))
    except Exception as exc:
        return handler_error("internal_error", str(exc))


def instantiate_template_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.ir.secret_policy import InlineSecretError
    from app.core.pipelines.project_pipelines import put_pipeline

    args = arguments or {}
    name = str(args.get("name") or "").strip()
    pipeline = str(args.get("pipeline") or "").strip()
    version = args.get("version")
    version_s = str(version).strip() if isinstance(version, str) and version.strip() else None
    try:
        graph = _load_template_graph(name, version_s)
        project_dir, project_name = require_project_dir(str(args.get("project") or ""))
        saved = put_pipeline(project_dir, pipeline, graph, project_name=project_name)
        return {
            "ok": True,
            "project": project_name,
            "pipeline": pipeline,
            "template": name,
            "version": version_s,
            "saved": saved,
        }
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except InlineSecretError as exc:
        return handler_error("secret_in_ir", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))



SEARCH_TEMPLATES_DESCRIPTION = (
    "Search the pipeline template marketplace catalog (and optionally seeded "
    "workspace templates) by pack, industry, modality, lifecycle, tags, status, or text query."
)
SEARCH_TEMPLATES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "pack": {"type": "string", "description": "Primary pack filter (Audio, Vision, RAG, …)."},
        "industry": {"type": "string"},
        "modality": {"type": "string", "description": "Single modality to match (audio, vision, …)."},
        "lifecycle": {"type": "string", "description": "Lifecycle stage: ingest|prep|train|eval|deploy|observe|agent."},
        "tags": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string", "description": "proposed|seeded|needs-api|alter-existing"},
        "family": {"type": "string"},
        "q": {"type": "string", "description": "Substring match on id, name, description, tags."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
        "include_seeded_workspace": {
            "type": "boolean",
            "default": False,
            "description": "Also list legacy workspace configs/templates names.",
        },
        **meta_props(),
    },
    "additionalProperties": False,
}


def _marketplace_catalog_path():
    from pathlib import Path
    # repo docs/PIPELINE_TEMPLATE_CATALOG.json relative to app/
    return Path(__file__).resolve().parents[4] / "docs" / "PIPELINE_TEMPLATE_CATALOG.json"


def search_templates_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Filter marketplace catalog entries for pack-first agents."""
    import json
    from pathlib import Path

    args = arguments or {}
    limit = args.get("limit")
    try:
        limit_n = int(limit) if limit is not None else 25
    except (TypeError, ValueError):
        return handler_error("validation_failed", "limit must be an integer")
    limit_n = max(1, min(limit_n, 200))

    pack = str(args.get("pack") or "").strip().lower()
    industry = str(args.get("industry") or "").strip().lower()
    modality = str(args.get("modality") or "").strip().lower()
    lifecycle = str(args.get("lifecycle") or "").strip().lower()
    status = str(args.get("status") or "").strip().lower()
    family = str(args.get("family") or "").strip().lower()
    q = str(args.get("q") or "").strip().lower()
    tags_raw = args.get("tags") or []
    if tags_raw and not isinstance(tags_raw, list):
        return handler_error("validation_failed", "tags must be an array of strings")
    tags = [str(t).strip().lower() for t in tags_raw if str(t).strip()]

    catalog_path = _marketplace_catalog_path()
    items: list[dict[str, Any]] = []
    if catalog_path.is_file():
        try:
            doc = json.loads(catalog_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return handler_error("internal_error", f"Failed to read marketplace catalog: {exc}")
        for t in doc.get("templates") or []:
            if not isinstance(t, dict):
                continue
            if pack and str(t.get("pack") or "").lower() != pack and pack not in [
                str(p).lower() for p in (t.get("packs_used") or [])
            ]:
                continue
            if industry and str(t.get("industry") or "").lower() != industry:
                continue
            if modality and modality not in [str(m).lower() for m in (t.get("modality") or [])]:
                continue
            if lifecycle and lifecycle not in [str(x).lower() for x in (t.get("lifecycle") or [])]:
                continue
            if status and str(t.get("status") or "").lower() != status:
                continue
            if family and str(t.get("family") or "").lower() != family:
                continue
            if tags:
                ttags = {str(x).lower() for x in (t.get("tags") or [])}
                if not set(tags).issubset(ttags):
                    continue
            if q:
                blob = " ".join(
                    [
                        str(t.get("id") or ""),
                        str(t.get("name") or ""),
                        str(t.get("description") or ""),
                        " ".join(str(x) for x in (t.get("tags") or [])),
                    ]
                ).lower()
                if q not in blob:
                    continue
            items.append(
                {
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "pack": t.get("pack"),
                    "industry": t.get("industry"),
                    "modality": t.get("modality"),
                    "lifecycle": t.get("lifecycle"),
                    "tags": t.get("tags"),
                    "status": t.get("status"),
                    "family": t.get("family"),
                    "value_prop": t.get("value_prop"),
                    "node_types": [s.get("node_type") for s in (t.get("node_chain") or []) if isinstance(s, dict)],
                }
            )
    else:
        return handler_error(
            "not_found",
            f"Marketplace catalog missing at {catalog_path}. Run scripts/generate_pipeline_template_catalog.py",
        )

    total_matched = len(items)
    items = items[:limit_n]

    seeded: list[dict[str, Any]] = []
    if bool(args.get("include_seeded_workspace")):
        tdir = _templates_dir()
        if tdir.exists():
            for f in sorted(tdir.glob("*.graph.json")):
                seeded.append({"name": f.name[: -len(".graph.json")], "kind": "workspace_seed"})

    return {
        "templates": items,
        "count": len(items),
        "matched": total_matched,
        "limit": limit_n,
        "catalog": str(catalog_path),
        "seeded_workspace": seeded,
    }
