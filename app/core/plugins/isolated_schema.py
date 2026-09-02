# app/core/plugins/isolated_schema.py
"""Extract host-side Config + port schemas for isolated plugins without importing them.

Isolated plugins must not exec_module() in the host process. Stubs used to inherit
an empty NodeConfig (extra=forbid), so real graph knobs like model_builder
architecture=ds_cnn raised extra_forbidden. This module rebuilds a Pydantic
Config (and port maps) from:

  1. The nested ``class Config`` in entry-point source (AST, no exec)
  2. Optional ``config_schema`` JSON-Schema-like tables in plugin.toml

Ports use ``object`` data types so host validation does not import plugin models.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import Field, create_model

from app.core.nodes.config import NodeConfig
from app.core.nodes.ports import InputPort, OutputPort

log = logging.getLogger(__name__)

_MISSING = object()

_NAME_TYPES: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "Any": Any,
    "object": object,
    "Path": str,
    "None": type(None),
    "NoneType": type(None),
}

_JSON_TYPES: dict[str, Any] = {
    "string": str,
    "str": str,
    "integer": int,
    "int": int,
    "number": float,
    "float": float,
    "boolean": bool,
    "bool": bool,
    "array": list,
    "list": list,
    "object": dict,
    "dict": dict,
}


@dataclass
class IsolatedNodeSpec:
    """Host-visible contract for one isolated node type."""

    node_type: str
    config_fields: list[tuple[str, Any, Any]] = field(default_factory=list)
    input_ports: dict[str, InputPort] = field(default_factory=dict)
    output_ports: dict[str, OutputPort] = field(default_factory=dict)


def specs_from_source(source: str, *, filename: str = "<isolated>") -> dict[str, IsolatedNodeSpec]:
    """Parse entry-point source for node_type, Config fields, and ports."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        log.warning("isolated_schema: cannot parse %s: %s", filename, exc)
        return {}

    specs: dict[str, IsolatedNodeSpec] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        spec = _class_to_spec(node)
        if spec is None:
            continue
        specs[spec.node_type] = spec
    return specs


def specs_from_entry_points(plugin_dir, manifest) -> dict[str, IsolatedNodeSpec]:
    """AST-scan each manifest entry point; later files override earlier ones."""
    merged: dict[str, IsolatedNodeSpec] = {}
    from pathlib import Path

    root = Path(plugin_dir)
    for entry_point in getattr(manifest, "entry_points", ()) or ():
        path = root / entry_point
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("isolated_schema: cannot read %s: %s", path, exc)
            continue
        merged.update(specs_from_source(text, filename=str(path)))
    return merged


def config_class_for_spec(
    node_type: str,
    spec: IsolatedNodeSpec | None,
    toml_schema: dict[str, Any] | None,
) -> type[NodeConfig]:
    """Build a NodeConfig subclass: AST fields first, then plugin.toml schema."""
    fields: dict[str, tuple[Any, Any]] = {}
    if toml_schema:
        fields.update(_fields_from_json_schema(toml_schema))
    if spec is not None:
        for name, typ, default in spec.config_fields:
            fields[name] = _pydantic_field(typ, default)
    if not fields:
        class EmptyIsolatedConfig(NodeConfig):
            pass

        EmptyIsolatedConfig.__name__ = f"Isolated_{node_type}_Config"
        return EmptyIsolatedConfig
    return create_model(
        f"Isolated_{node_type}_Config",
        __base__=NodeConfig,
        **fields,
    )


def ports_for_spec(spec: IsolatedNodeSpec | None) -> tuple[dict, dict]:
    if spec is None:
        return {}, {}
    return dict(spec.input_ports), dict(spec.output_ports)


def _pydantic_field(typ: Any, default: Any) -> tuple[Any, Any]:
    if default is _MISSING:
        return (typ, ...)
    if default == [] or default == ():
        return (typ, Field(default_factory=list))
    if default == {}:
        return (typ, Field(default_factory=dict))
    return (typ, default)


def _fields_from_json_schema(schema: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties")
    if not isinstance(props, dict):
        # Flat {field: {type, default}} form
        props = {
            k: v
            for k, v in schema.items()
            if isinstance(v, dict) and ("type" in v or "default" in v)
        }
    required = set(schema.get("required") or [])
    out: dict[str, tuple[Any, Any]] = {}
    for name, spec in props.items():
        if not isinstance(spec, dict):
            if isinstance(spec, str):
                out[name] = (_JSON_TYPES.get(spec, Any), ...)
            continue
        typ = _JSON_TYPES.get(str(spec.get("type", "string")).lower(), Any)
        if "default" in spec:
            out[name] = _pydantic_field(typ, spec["default"])
        elif name in required or "default" not in spec:
            out[name] = (typ, ...)
    return out


def _class_to_spec(cls: ast.ClassDef) -> IsolatedNodeSpec | None:
    node_type = _extract_node_type(cls)
    if not node_type:
        return None
    spec = IsolatedNodeSpec(node_type=node_type)
    for stmt in cls.body:
        if isinstance(stmt, ast.ClassDef) and stmt.name == "Config":
            spec.config_fields = _config_fields(stmt)
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            name = _target_name(stmt)
            value = stmt.value if isinstance(stmt, ast.Assign) else stmt.value
            if name == "input_ports" and value is not None:
                spec.input_ports = _extract_input_ports(value)
            elif name == "output_ports" and value is not None:
                spec.output_ports = _extract_output_ports(value)
    return spec


def _target_name(stmt: ast.AST) -> str | None:
    if isinstance(stmt, ast.Assign) and stmt.targets:
        t = stmt.targets[0]
        if isinstance(t, ast.Name):
            return t.id
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return stmt.target.id
    return None


def _extract_node_type(cls: ast.ClassDef) -> str | None:
    for stmt in cls.body:
        name = _target_name(stmt)
        if name == "node_type":
            value = stmt.value if isinstance(stmt, ast.Assign) else getattr(stmt, "value", None)
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
        if name == "metadata":
            value = stmt.value if isinstance(stmt, ast.Assign) else getattr(stmt, "value", None)
            found = _node_type_from_metadata_call(value)
            if found:
                return found
    return None


def _node_type_from_metadata_call(value: ast.AST | None) -> str | None:
    if not isinstance(value, ast.Call):
        return None
    if "NodeMetadata" not in _call_name(value):
        return None
    for kw in value.keywords:
        if kw.arg == "node_type":
            lit = _eval_literal(kw.value)
            if isinstance(lit, str):
                return lit
    if value.args:
        lit = _eval_literal(value.args[0])
        if isinstance(lit, str):
            return lit
    return None


def _config_fields(cls: ast.ClassDef) -> list[tuple[str, Any, Any]]:
    fields: list[tuple[str, Any, Any]] = []
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            fname = stmt.target.id
            if fname.startswith("_"):
                continue
            typ = _eval_type(stmt.annotation)
            default = _MISSING if stmt.value is None else _eval_literal(stmt.value)
            if default is _MISSING and stmt.value is not None:
                # non-literal default — keep as required-with-type is wrong;
                # treat as Any default None if we cannot eval
                default = None
                typ = typ | type(None) if typ is not Any else Any
            fields.append((fname, typ, default))
        elif isinstance(stmt, ast.Assign) and stmt.targets:
            t = stmt.targets[0]
            if isinstance(t, ast.Name) and not t.id.startswith("_"):
                default = _eval_literal(stmt.value)
                if default is _MISSING:
                    continue
                fields.append((t.id, type(default) if default is not None else Any, default))
    return fields


def _eval_type(node: ast.AST | None) -> Any:
    if node is None:
        return Any
    if isinstance(node, ast.Name):
        return _NAME_TYPES.get(node.id, Any)
    if isinstance(node, ast.Attribute):
        return _NAME_TYPES.get(node.attr, Any)
    if isinstance(node, ast.Constant):
        if node.value is None:
            return type(None)
        return type(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _eval_type(node.left)
        right = _eval_type(node.right)
        try:
            return left | right
        except TypeError:
            return Any
    if isinstance(node, ast.Subscript):
        origin_name = ""
        if isinstance(node.value, ast.Name):
            origin_name = node.value.id
        elif isinstance(node.value, ast.Attribute):
            origin_name = node.value.attr
        sl = node.slice
        args: tuple[Any, ...]
        if isinstance(sl, ast.Tuple):
            args = tuple(_eval_type(e) for e in sl.elts)
        else:
            args = (_eval_type(sl),)
        if origin_name in {"Optional", "optional"}:
            return args[0] | type(None) if args else Any
        if origin_name in {"ClassVar", "Final"}:
            return args[0] if args else Any
        origin = _NAME_TYPES.get(origin_name, Any)
        try:
            if origin is list and args:
                return list[args[0]]
            if origin is dict and len(args) >= 2:
                return dict[args[0], args[1]]
        except TypeError:
            return origin
        return origin
    return Any


def _eval_literal(node: ast.AST) -> Any:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _eval_literal(node.operand)
        if inner is _MISSING:
            return _MISSING
        try:
            return -inner
        except TypeError:
            return _MISSING
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return _MISSING


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _kw_const(call: ast.Call, key: str, default: Any) -> Any:
    for kw in call.keywords:
        if kw.arg == key:
            val = _eval_literal(kw.value)
            return default if val is _MISSING else val
    return default


def _extract_input_ports(value: ast.AST) -> dict[str, InputPort]:
    ports: dict[str, InputPort] = {}
    if not isinstance(value, ast.Dict):
        return ports
    for key, val in zip(value.keys, value.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            continue
        name = key.value
        required = True
        cardinality = "single"
        description = ""
        if isinstance(val, ast.Call) and "InputPort" in _call_name(val):
            required = bool(_kw_const(val, "required", True))
            cardinality = str(_kw_const(val, "cardinality", "single") or "single")
            description = str(_kw_const(val, "description", "") or "")
            name = str(_kw_const(val, "name", name) or name)
        data_type: Any = object if required else (object | type(None))
        try:
            ports[name] = InputPort(
                name=name,
                data_type=data_type,
                cardinality=cardinality if cardinality in ("single", "multi") else "single",
                required=required,
                description=description,
            )
        except Exception as exc:
            log.warning("isolated_schema: skip input port %s: %s", name, exc)
    return ports


def _extract_output_ports(value: ast.AST) -> dict[str, OutputPort]:
    ports: dict[str, OutputPort] = {}
    if not isinstance(value, ast.Dict):
        return ports
    for key, val in zip(value.keys, value.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            continue
        name = key.value
        description = ""
        if isinstance(val, ast.Call):
            description = str(_kw_const(val, "description", "") or "")
            name = str(_kw_const(val, "name", name) or name)
        try:
            ports[name] = OutputPort(name=name, data_type=object, description=description)
        except Exception as exc:
            log.warning("isolated_schema: skip output port %s: %s", name, exc)
    return ports
