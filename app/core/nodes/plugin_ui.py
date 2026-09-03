# app/core/nodes/plugin_ui.py
"""
Bounded Context:  BC3 — Node Catalog
Responsibility:   Turn plugin.toml [config_schema.<node>] tables into JSON Schema
                  the Builder can render, overlaying Pydantic Config schemas.
Owns:             json_schema_from_toml_fields, overlay_plugin_ui
Public Surface:   json_schema_from_toml_fields, overlay_plugin_ui
Must NOT:         Import plugins, execute plugin code, or talk to the API.
Dependencies:     copy
Reason To Change: Plugin UI hint keys (widget, enum, title) evolve.

Plugin authors declare fields in plugin.toml. The host is a generic form
renderer. plugin.toml wins over in-code Pydantic for title, description,
enum, default, type, and widget when the plugin sets them.
"""
from __future__ import annotations

import copy
from typing import Any

_PROP_KEYS = (
    "type",
    "title",
    "description",
    "default",
    "enum",
    "widget",
    "minimum",
    "maximum",
    "format",
)


def json_schema_from_toml_fields(fields: dict[str, Any] | None) -> dict[str, Any]:
    """Convert a flat toml field table into a JSON Schema object."""
    props: dict[str, Any] = {}
    if not isinstance(fields, dict):
        return {"type": "object", "properties": props}
    for key, spec in fields.items():
        if not isinstance(key, str) or not key or not isinstance(spec, dict):
            continue
        prop: dict[str, Any] = {}
        for name in _PROP_KEYS:
            if name in spec:
                prop[name] = spec[name]
        ui = spec.get("ui")
        if ui and "widget" not in prop:
            prop["widget"] = ui
        if prop:
            props[key] = prop
    return {"type": "object", "properties": props}


def overlay_plugin_ui(base: dict[str, Any] | None, fields: dict[str, Any] | None) -> dict[str, Any]:
    """Merge plugin.toml field specs onto a Pydantic model_json_schema() dict.

    Plugin-declared keys keep their relative order first, then leftover
    Pydantic-only keys. Declared plugin properties overwrite matching JSON
    Schema keys (enum, title, description, widget, default, type).
    """
    overlay = json_schema_from_toml_fields(fields)
    plugin_props = overlay.get("properties") or {}
    if not plugin_props:
        return copy.deepcopy(base) if isinstance(base, dict) else overlay
    out: dict[str, Any] = copy.deepcopy(base) if isinstance(base, dict) else {"type": "object"}
    out["type"] = "object"
    existing = dict(out.get("properties") or {})
    merged: dict[str, Any] = {}
    for key, spec in plugin_props.items():
        prev = existing.get(key) if isinstance(existing.get(key), dict) else {}
        merged[key] = {**prev, **spec}
    for key, spec in existing.items():
        if key not in merged:
            merged[key] = spec
    out["properties"] = merged
    return out
