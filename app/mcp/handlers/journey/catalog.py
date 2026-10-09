# app/mcp/handlers/journey/catalog.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Pack catalog, node spec, and template materialize MCP tools.
Owns:             materialize_template, get_node_spec, list_packs, describe_pack
Public Surface:   *_handler, *_DESCRIPTION, *_SCHEMA in this module
Must NOT:         Import app.domain except through journey.common; never return secret values.
Dependencies:     app.mcp.handlers.journey.common and the core package this tool calls.
Reason To Change: That MCP tool's arguments or result shape change.
"""
from __future__ import annotations

from typing import Any

from app.mcp.handlers.journey.common import handler_error, meta_props, require_project_dir

# ── Pack-first catalog tools (materialize / node spec / packs) ────────────────

MATERIALIZE_TEMPLATE_DESCRIPTION = (
    "Expand a marketplace template id into Graph IR 1.1 (does not save a pipeline). "
    "Use search_templates to find ids, then validate_graph / save_pipeline."
)
MATERIALIZE_TEMPLATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "template_id": {"type": "string", "description": "Marketplace template id (e.g. tpl-vision-yolo-detect-train-retail-shelf)."},
        "param_overrides": {
            "type": "object",
            "description": "Optional parameter overrides merged into template parameters.",
            "additionalProperties": True,
        },
        "merge_parameters_into_first": {
            "type": "boolean",
            "default": False,
            "description": "If true, also merge parameters into the first node's config.",
        },
        **meta_props(),
    },
    "required": ["template_id"],
    "additionalProperties": False,
}


def materialize_template_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Materialize marketplace catalog entry → Graph IR 1.1 dict."""
    from copy import deepcopy

    from app.core.templates.pipeline_template_materializer import (
        find_template,
        load_marketplace_catalog,
        materialize_template_entry,
    )

    args = arguments or {}
    tid = str(args.get("template_id") or "").strip()
    if not tid:
        return handler_error("validation_failed", "template_id is required")
    try:
        from app.core.templates.example_templates import seed_example_input_datasets
        from app.core.templates.pipeline_template_materializer import (
            find_template,
            load_marketplace_catalog,
            materialize_template_entry,
        )
        from app.core.host.registry_runtime import get_registry

        seed_example_input_datasets()
        catalog = load_marketplace_catalog()
        entry = find_template(tid, catalog)
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except KeyError:
        return handler_error("not_found", f"Template not found: {tid}")
    except Exception as exc:
        return handler_error("internal_error", f"Failed to load template: {exc}")

    entry = deepcopy(entry)
    overrides = args.get("param_overrides") or {}
    if overrides and not isinstance(overrides, dict):
        return handler_error("validation_failed", "param_overrides must be an object")
    if isinstance(overrides, dict) and overrides:
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
            merge_parameters_into_first=bool(args.get("merge_parameters_into_first")),
            registry=registry,
            ensure_seed_datasets=True,
        )
    except Exception as exc:
        return handler_error("validation_failed", f"Materialize failed: {exc}")
    return {"ok": True, "template_id": tid, "graph": graph}


GET_NODE_SPEC_DESCRIPTION = (
    "Return design-catalog node contract (ports, config, pack, status, honesty) "
    "from PLUGIN_NODE_PLATFORM_CATALOG.json + refinements (not only runtime registry)."
)
GET_NODE_SPEC_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "node_type": {"type": "string", "description": "Node type id (e.g. yolo_train, tflm_quantize)."},
        **meta_props(),
    },
    "required": ["node_type"],
    "additionalProperties": False,
}


def _platform_catalog_path():
    from pathlib import Path

    return Path(__file__).resolve().parents[4] / "docs" / "PLUGIN_NODE_PLATFORM_CATALOG.json"


def _refinements_path():
    from pathlib import Path

    return Path(__file__).resolve().parents[4] / "docs" / "PLUGIN_NODE_REFINEMENTS.json"


def get_node_spec_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lookup node_type in platform catalog (+ refinement added nodes)."""
    import json

    args = arguments or {}
    nt = str(args.get("node_type") or "").strip()
    if not nt:
        return handler_error("validation_failed", "node_type is required")

    path = _platform_catalog_path()
    if not path.is_file():
        return handler_error("not_found", f"Platform catalog missing at {path}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return handler_error("internal_error", f"Failed to read platform catalog: {exc}")

    nodes = list(doc.get("nodes") or [])
    nodes.extend(doc.get("refinement_added_nodes") or [])

    # Also merge refinements JSON if present
    ref_path = _refinements_path()
    if ref_path.is_file():
        try:
            ref = json.loads(ref_path.read_text(encoding="utf-8"))
            nodes.extend(ref.get("added_nodes") or [])
        except Exception:
            pass

    match = None
    for n in nodes:
        if isinstance(n, dict) and n.get("node_type") == nt:
            match = n
            break
    runtime_fallback = False
    if match is None:
        # Catalog drift safety: synthesize a minimal spec from the live node registry
        # so runtime-complete plugins (e.g. send_email) stay discoverable.
        from app.core.nodes import registry as _node_registry
        from app.core.nodes.errors import NodeNotFoundError

        try:
            cls = _node_registry.get_class(nt)
        except NodeNotFoundError:
            cls = None
        except Exception:
            cls = None
        if cls is None:
            return handler_error("not_found", f"Unknown node_type in design catalog: {nt}")
        runtime_fallback = True
        meta = getattr(cls, "metadata", None)
        inputs = []
        for name, port in (getattr(cls, "input_ports", None) or {}).items():
            inputs.append(
                {
                    "name": name,
                    "type": str(getattr(port, "data_type", "Any")),
                    "required": bool(getattr(port, "required", True)),
                }
            )
        outputs = []
        for name, port in (getattr(cls, "output_ports", None) or {}).items():
            outputs.append(
                {
                    "name": name,
                    "type": str(getattr(port, "data_type", "Any")),
                }
            )
        config = []
        cfg_cls = getattr(cls, "Config", None)
        if cfg_cls is not None:
            fields = getattr(cfg_cls, "model_fields", None) or {}
            for fname, finfo in fields.items():
                default = getattr(finfo, "default", None)
                config.append(f"{fname}:{type(default).__name__ if default is not None else 'Any'}={default!r}")
        match = {
            "node_type": nt,
            "pack": f"(runtime) {getattr(meta, 'category', '')}".strip(),
            "category": getattr(meta, "category", None) if meta else None,
            "purpose": ((getattr(meta, "description", None) or getattr(meta, "label", None)) if meta else None),
            "status": "Existing",
            "inputs": inputs,
            "outputs": outputs,
            "config": config,
            "notes": "Synthesized from runtime registry (design catalog miss).",
            "optional_dependencies_runtime": None,
            "kind": "runtime_fallback",
        }

    honesty = {}
    needs_api = {"mcu_flash_ota", "mcu_ondevice_metrics"}
    if nt in needs_api:
        honesty = {
            "needs_api": True,
            "banner": "MCU flash/OTA and on-device metrics require Devices APIs — never fake device control.",
        }
    # Refinement honesty banner
    if ref_path.is_file():
        try:
            ref = json.loads(ref_path.read_text(encoding="utf-8"))
            h = ref.get("honesty") or {}
            if nt in set(h.get("needs_api_nodes") or []):
                honesty = {
                    "needs_api": True,
                    "banner": h.get("banner")
                    or "Requires Devices APIs — never fake device control.",
                }
        except Exception:
            pass

    return {
        "ok": True,
        "node_type": nt,
        "pack": match.get("pack"),
        "category": match.get("category"),
        "purpose": match.get("purpose"),
        "status": match.get("status"),
        "kind": match.get("kind"),
        "inputs": match.get("inputs") or [],
        "outputs": match.get("outputs") or [],
        "config": match.get("config") or [],
        "notes": match.get("notes"),
        "optional_dependencies_runtime": match.get("optional_dependencies_runtime"),
        "honesty": honesty,
        "related": match.get("related"),
        "refinement": match.get("refinement"),
        "source": "runtime_registry" if runtime_fallback else "design_catalog",
    }


LIST_PACKS_DESCRIPTION = (
    "List Graphyn packs (Audio, Common, TinyML, Vision, RAG, Video, Agents, MLOps, WakeWord) "
    "with design-catalog node counts and marketplace template family counts."
)
LIST_PACKS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {**meta_props()},
    "additionalProperties": False,
}


def list_packs_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import json
    from collections import Counter
    from pathlib import Path

    packs = [
        "Audio",
        "Common",
        "TinyML",
        "Vision",
        "RAG",
        "Video",
        "Agents",
        "MLOps",
        "WakeWord",
    ]
    cat_path = _platform_catalog_path()
    node_counts: Counter[str] = Counter()
    if cat_path.is_file():
        doc = json.loads(cat_path.read_text(encoding="utf-8"))
        # Prefer counts_by_pack if present
        cbp = doc.get("counts_by_pack") or {}
        if cbp:
            for k, v in cbp.items():
                node_counts[str(k)] = int(v)
        else:
            for n in list(doc.get("nodes") or []) + list(doc.get("refinement_added_nodes") or []):
                pack = str(n.get("pack") or "")
                for name in packs:
                    if f"/{name}/" in pack or pack.endswith(f"/{name}"):
                        node_counts[name] += 1
                        break

    tpl_path = Path(__file__).resolve().parents[4] / "docs" / "PIPELINE_TEMPLATE_CATALOG.json"
    tpl_counts: Counter[str] = Counter()
    if tpl_path.is_file():
        tdoc = json.loads(tpl_path.read_text(encoding="utf-8"))
        cbp = tdoc.get("counts_by_pack") or {}
        if cbp:
            for k, v in cbp.items():
                tpl_counts[str(k)] = int(v)
        else:
            for t in tdoc.get("templates") or []:
                tpl_counts[str(t.get("pack") or "")] += 1

    items = []
    for name in packs:
        items.append(
            {
                "pack": name,
                "node_count": int(node_counts.get(name, 0)),
                "template_count": int(tpl_counts.get(name, 0)),
                "plugin_root": f"PluginPackage/{name}/",
            }
        )
    return {"ok": True, "packs": items, "count": len(items)}


DESCRIBE_PACK_DESCRIPTION = (
    "Describe one pack: node_types from the design catalog and sample marketplace template ids."
)
DESCRIBE_PACK_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "pack": {"type": "string", "description": "Pack name (Audio, Vision, RAG, …)."},
        "template_limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        **meta_props(),
    },
    "required": ["pack"],
    "additionalProperties": False,
}


def describe_pack_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import json
    from pathlib import Path

    args = arguments or {}
    pack = str(args.get("pack") or "").strip()
    if not pack:
        return handler_error("validation_failed", "pack is required")
    try:
        limit = int(args.get("template_limit") or 10)
    except (TypeError, ValueError):
        return handler_error("validation_failed", "template_limit must be an integer")
    limit = max(1, min(limit, 50))

    cat_path = _platform_catalog_path()
    if not cat_path.is_file():
        return handler_error("not_found", f"Platform catalog missing at {cat_path}")
    doc = json.loads(cat_path.read_text(encoding="utf-8"))
    node_types = []
    for n in list(doc.get("nodes") or []) + list(doc.get("refinement_added_nodes") or []):
        p = str(n.get("pack") or "")
        if f"/{pack}/" in p or p.rstrip("/").endswith(pack) or str(n.get("pack_name") or "") == pack:
            node_types.append(
                {
                    "node_type": n.get("node_type"),
                    "status": n.get("status"),
                    "category": n.get("category"),
                    "purpose": n.get("purpose"),
                }
            )

    tpl_path = Path(__file__).resolve().parents[4] / "docs" / "PIPELINE_TEMPLATE_CATALOG.json"
    templates = []
    if tpl_path.is_file():
        tdoc = json.loads(tpl_path.read_text(encoding="utf-8"))
        for t in tdoc.get("templates") or []:
            if str(t.get("pack") or "").lower() != pack.lower() and pack.lower() not in [
                str(x).lower() for x in (t.get("packs_used") or [])
            ]:
                continue
            templates.append(
                {
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "family": t.get("family"),
                    "status": t.get("status"),
                    "industry": t.get("industry"),
                }
            )
            if len(templates) >= limit:
                break

    return {
        "ok": True,
        "pack": pack,
        "node_types": node_types,
        "node_count": len(node_types),
        "templates_sample": templates,
        "template_sample_count": len(templates),
        "plugin_root": f"PluginPackage/{pack}/",
    }
