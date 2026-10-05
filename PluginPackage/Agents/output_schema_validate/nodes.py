"""OutputSchemaValidateNode — Validate LLM JSON vs schema

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json
import re

import importlib
import logging
from typing import ClassVar, Any
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("output_schema_validate.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

log = logging.getLogger(__name__)

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


_FENCE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?```\s*$", re.S | re.I)


def _parse_payload(raw: Any) -> tuple[Any, list[str]]:
    """Coerce LLM output to a JSON value: parse strings / ChatMessage.content."""
    data = _dump(raw)
    if isinstance(data, dict) and "role" in data and isinstance(data.get("content"), str) \
            and set(data) <= {"role", "content", "name", "metadata"}:
        data = data["content"]
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    if isinstance(data, str):
        text = data
        m = _FENCE.match(text)
        if m:
            text = m.group(1)
        try:
            return json.loads(text), []
        except ValueError as exc:
            return None, [f"$: invalid JSON ({exc})"]
    return data, []


_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: (isinstance(v, int) and not isinstance(v, bool))
    or (isinstance(v, float) and v.is_integer()),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, (list, tuple)),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def validate(value: Any, schema: Any, path: str = "$") -> list[str]:
    """Minimal JSON-Schema subset: type (incl. list), required, properties,
    additionalProperties=false, items, enum, const, min/max length/items,
    minimum/maximum, anyOf/oneOf/allOf. bool is never an integer/number."""
    if schema is True or schema is None or schema == {}:
        return []
    if schema is False:
        return [f"{path}: no value allowed"]
    if not isinstance(schema, dict):
        return [f"{path}: invalid schema {schema!r}"]
    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        types_ = expected if isinstance(expected, list) else [expected]
        unknown = [t for t in types_ if t not in _TYPE_CHECKS]
        if unknown:
            return [f"{path}: unsupported schema type {unknown}"]
        if not any(_TYPE_CHECKS[t](value) for t in types_):
            return [f"{path}: expected {'|'.join(types_)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: {value!r} != const {schema['const']!r}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(str(schema["pattern"]), value):
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, dict):
        for key in schema.get("required") or []:
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        props = schema.get("properties") or {}
        for key, sub in props.items():
            if key in value:
                errors.extend(validate(value[key], sub, f"{path}.{key}"))
        addl = schema.get("additionalProperties", True)
        extras = [k for k in value if k not in props]
        if addl is False and extras:
            errors.append(f"{path}: additional properties not allowed {sorted(map(str, extras))}")
        elif isinstance(addl, dict):
            for key in extras:
                errors.extend(validate(value[key], addl, f"{path}.{key}"))
    if isinstance(value, (list, tuple)):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(value):
                errors.extend(validate(item, items, f"{path}[{i}]"))
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            errors.append(f"{path}: fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path}: more than maxItems {schema['maxItems']}")
    for sub in schema.get("allOf") or []:
        errors.extend(validate(value, sub, path))
    if schema.get("anyOf"):
        if not any(not validate(value, sub, path) for sub in schema["anyOf"]):
            errors.append(f"{path}: does not match anyOf")
    if schema.get("oneOf"):
        n = sum(1 for sub in schema["oneOf"] if not validate(value, sub, path))
        if n != 1:
            errors.append(f"{path}: matches {n} of oneOf (expected exactly 1)")
    return errors


def _schema_validate(config, inputs, types) -> dict:
    schema = config.json_schema or {}
    if isinstance(schema, str):
        schema = json.loads(schema) if schema.strip() else {}
    value, errors = _parse_payload(inputs.get("input"))
    if not errors:
        errors = validate(value, schema)
    if errors and bool(config.strict):
        raise ValueError("output_schema_validate: " + "; ".join(errors))
    # Branch-style output: only the active port is emitted (``output`` when
    # valid, ``errors`` when invalid) so the inactive branch is skipped.
    if errors:
        return {"errors": errors}
    return {"output": value}



class OutputSchemaValidateNode(Node):
    """Validate LLM JSON vs schema"""

    node_type: ClassVar[str] = "output_schema_validate"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="output_schema_validate",
        label="Output Schema Validate",
        description="Validate LLM JSON vs schema",
        category="Quality",
        version="0.1.0",
        tags=["agents"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="Any"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="Parsed JSON value (port omitted when invalid)"),
        "errors": OutputPort(name="errors", data_type=object, description="list[str] (port omitted when valid)"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        json_schema: dict = Field(default_factory=dict, title="Json schema", description="JSON Schema (subset: type, required, properties, items, enum, const, bounds, anyOf/oneOf/allOf).")
        strict: bool = Field(default=True, title="Strict", description="Raise on invalid output; when false emit only the `errors` port.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        if stub:
            log.warning(
                "%s: stub mode (config.stub=True) returned a placeholder, not a real result",
                getattr(self, "node_type", type(self).__name__),
            )
            # Fail closed: no port produced → downstream branches are skipped.
            return {}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"output_schema_validate: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return _schema_validate(self.config, inputs, _types)
