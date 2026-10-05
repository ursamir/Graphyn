# app/core/ir/parameters.py
"""
Bounded Context:  BC1 — Graph Language
Responsibility:   Resolve graph-level ``parameters`` (GraphIR.parameters) for
                  one run and substitute ``${params.NAME}`` references inside
                  node configs.
Owns:             apply_parameters(), resolve_parameter_values(),
                  ParameterError, PARAM_REF_RE.
Public Surface:   apply_parameters(graph, values) -> GraphIR;
                  resolve_parameter_values(graph, values) -> dict.
Must NOT:         Import app.core.execution / app.api / app.domain. Pure.
Dependencies:     app.core.ir.models (+ stdlib re/json).
Reason To Change: Parameter reference syntax or type coercion rules change.

Rules:
  * Graphs that declare no ``parameters`` are returned unchanged and any
    supplied value is an error (unknown parameter).
  * A config string that is exactly ``${params.NAME}`` becomes the typed
    value; a string that merely contains references gets ``str(value)``
    interpolated. Only node ``config`` values are rewritten.
  * Values are type-checked against ``IRParameter.type`` (int, float/number,
    str/string, bool/boolean, list/array, dict/object; other types: any).
"""
from __future__ import annotations

import re
from typing import Any

from app.core.ir.models import GraphIR, IRNode, deep_unfreeze

PARAM_REF_RE = re.compile(r"\$\{params\.([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_EXACT_RE = re.compile(r"^\$\{params\.([A-Za-z_][A-Za-z0-9_]{0,63})\}$")


class ParameterError(ValueError):
    """Unknown parameter, missing required value, or wrong type."""


def _check_type(name: str, declared: str, value: Any) -> Any:
    t = (declared or "").strip().lower()
    if t in ("int", "integer"):
        if isinstance(value, bool) or not isinstance(value, int):
            if isinstance(value, float) and value.is_integer():
                return int(value)
            raise ParameterError(f"parameter {name!r} must be an integer")
        return value
    if t in ("float", "number"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ParameterError(f"parameter {name!r} must be a number")
        return value
    if t in ("str", "string"):
        if not isinstance(value, str):
            raise ParameterError(f"parameter {name!r} must be a string")
        return value
    if t in ("bool", "boolean"):
        if not isinstance(value, bool):
            raise ParameterError(f"parameter {name!r} must be a boolean")
        return value
    if t in ("list", "array"):
        if not isinstance(value, list):
            raise ParameterError(f"parameter {name!r} must be an array")
        return value
    if t in ("dict", "object"):
        if not isinstance(value, dict):
            raise ParameterError(f"parameter {name!r} must be an object")
        return value
    return value


def resolve_parameter_values(graph: GraphIR, values: dict[str, Any] | None) -> dict[str, Any]:
    """Merge supplied ``values`` with declared defaults; validate names/types."""
    supplied = dict(values or {})
    declared = dict(getattr(graph, "parameters", None) or {})
    unknown = sorted(set(supplied) - set(declared))
    if unknown:
        raise ParameterError(
            f"Unknown parameter(s) {unknown}. Declared: {sorted(declared) or '(none)'}"
        )
    out: dict[str, Any] = {}
    for name, spec in declared.items():
        if name in supplied:
            out[name] = _check_type(name, spec.type, supplied[name])
        else:
            out[name] = deep_unfreeze(spec.default)
    return out


def _substitute(value: Any, params: dict[str, Any]) -> Any:
    if isinstance(value, str):
        exact = _EXACT_RE.match(value)
        if exact and exact.group(1) in params:
            return params[exact.group(1)]

        def _repl(m: re.Match) -> str:
            key = m.group(1)
            return str(params[key]) if key in params else m.group(0)

        return PARAM_REF_RE.sub(_repl, value)
    if isinstance(value, dict):
        return {k: _substitute(v, params) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_substitute(v, params) for v in value]
    return value


def apply_parameters(graph: GraphIR, values: dict[str, Any] | None = None) -> GraphIR:
    """Return ``graph`` with ``${params.NAME}`` references substituted.

    No-op (same object) when the graph declares no parameters and no values
    are supplied.
    """
    declared = getattr(graph, "parameters", None) or {}
    if not declared:
        if values:
            raise ParameterError(
                f"Graph declares no parameters; got {sorted(values)}"
            )
        return graph
    params = resolve_parameter_values(graph, values)
    new_nodes = []
    for node in graph.nodes:
        cfg = deep_unfreeze(node.config or {})
        new_cfg = _substitute(cfg, params)
        if new_cfg == cfg:
            new_nodes.append(node)
        else:
            new_nodes.append(IRNode.model_validate({**node.model_dump(), "config": new_cfg}))
    return graph.model_copy(update={"nodes": new_nodes})
