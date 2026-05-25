# app/core/nodes/compat.py
"""CompatibilityChecker and JSON Schema helpers for the Enhanced Node System."""
from __future__ import annotations

import types
from typing import Any, Union, get_args, get_origin

from app.core.nodes.errors import NodeTypeError


class CompatibilityChecker:
    """Determines whether an output port type is compatible with an input port type.

    All methods are static — no instance state is needed.
    """

    @staticmethod
    def are_compatible(
        output_type: type | None,
        input_type: type | None,
    ) -> bool:
        """Return ``True`` if a value of ``output_type`` can flow into ``input_type``.

        Rules applied in order:

        1. ``are_compatible(None, None)`` → ``True``
        2. ``are_compatible(X, None)`` or ``are_compatible(None, X)`` → ``False``
           for any non-``None`` ``X``
        3. Both plain (non-generic) classes → ``issubclass(output_type, input_type)``
        4. Either is a generic alias → origins must be identical AND each pair of
           corresponding ``get_args`` elements must be recursively compatible.
        """
        # Rule 1: both None
        if output_type is None and input_type is None:
            return True

        # Rule 2: one None
        if output_type is None or input_type is None:
            return False

        out_origin = get_origin(output_type)
        in_origin = get_origin(input_type)

        # Rule 3: both plain (non-generic) classes
        if out_origin is None and in_origin is None:
            try:
                return issubclass(output_type, input_type)
            except TypeError:
                return False

        # Rule 3b: input is plain `list` (no type args) — accept any list[X] output
        if in_origin is None and input_type is list and out_origin is list:
            return True

        # Rule 3c: input is `object` — accepts anything (universal sink)
        if in_origin is None and input_type is object:
            return True

        # Rule 3d: output is `object` — can flow into anything (universal source)
        if out_origin is None and output_type is object:
            return True

        # Rule 4a: Union / Optional handling.
        # Optional[X] is Union[X, None]; Union[X, Y] has origin=Union.
        # Two Union types are compatible if every output arg is compatible with
        # at least one input arg (covariant subset check).
        if out_origin is Union and in_origin is Union:
            out_args = get_args(output_type)
            in_args = get_args(input_type)
            return all(
                any(CompatibilityChecker.are_compatible(oa, ia) for ia in in_args)
                for oa in out_args
            )

        # Rule 4b: output is Union, input is plain type — all output args must be compatible
        if out_origin is Union and in_origin is None:
            return all(
                CompatibilityChecker.are_compatible(oa, input_type)
                for oa in get_args(output_type)
            )

        # Rule 4c: output is plain type, input is Union — output must be compatible with any arg
        if out_origin is None and in_origin is Union:
            return any(
                CompatibilityChecker.are_compatible(output_type, ia)
                for ia in get_args(input_type)
            )

        # Rule 4: at least one is a generic alias
        if out_origin != in_origin:
            return False

        out_args = get_args(output_type)
        in_args = get_args(input_type)

        if len(out_args) != len(in_args):
            return False

        return all(
            CompatibilityChecker.are_compatible(oa, ia)
            for oa, ia in zip(out_args, in_args)
        )

    @staticmethod
    def check_connection(
        src_node: Any,
        src_port: str,
        dst_node: Any,
        dst_port: str,
    ) -> None:
        """Validate a port-to-port connection, raising ``NodeTypeError`` if invalid.

        Checks:
        - ``src_port`` exists on ``src_node.output_ports``
        - ``dst_port`` exists on ``dst_node.input_ports``
        - ``are_compatible(src_port.data_type, dst_port.data_type)``

        Args:
            src_node: The upstream node instance.
            src_port: Name of the output port on ``src_node``.
            dst_node: The downstream node instance.
            dst_port: Name of the input port on ``dst_node``.

        Raises:
            NodeTypeError: If the port does not exist or types are incompatible.
        """
        if src_port not in src_node.output_ports:
            raise NodeTypeError(
                f"Node '{type(src_node).__name__}' has no output port '{src_port}'. "
                f"Available output ports: {list(src_node.output_ports)}"
            )
        if dst_port not in dst_node.input_ports:
            raise NodeTypeError(
                f"Node '{type(dst_node).__name__}' has no input port '{dst_port}'. "
                f"Available input ports: {list(dst_node.input_ports)}"
            )

        out_type = src_node.output_ports[src_port].data_type
        in_type = dst_node.input_ports[dst_port].data_type

        if not CompatibilityChecker.are_compatible(out_type, in_type):
            raise NodeTypeError(
                f"Incompatible connection: "
                f"'{type(src_node).__name__}.{src_port}' produces {out_type!r} "
                f"but '{type(dst_node).__name__}.{dst_port}' expects {in_type!r}"
            )


# ── JSON Schema helpers ───────────────────────────────────────────────────────

_BUILTIN_TYPE_MAP: dict[type, str] = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
    bytes: "string",
}


def _type_to_schema(t: type | None) -> dict[str, Any] | None:
    """Convert a port ``data_type`` to a minimal JSON Schema dict.

    Returns:
        A JSON Schema dict, or ``None`` if ``t`` is ``None``.
    """
    if t is None:
        return None

    from pydantic import BaseModel as PydanticBaseModel

    # Pydantic model → full JSON Schema
    if isinstance(t, type) and issubclass(t, PydanticBaseModel):
        return t.model_json_schema()

    origin = get_origin(t)

    if origin is list:
        args = get_args(t)
        item_schema = _type_to_schema(args[0]) if args else {}
        return {"type": "array", "items": item_schema or {}}

    if origin is dict or t is dict:
        return {"type": "object"}

    if origin is tuple:
        args = get_args(t)
        if args:
            return {"type": "array", "prefixItems": [_type_to_schema(a) for a in args]}
        return {"type": "array"}

    # Built-in scalar types
    if t in _BUILTIN_TYPE_MAP:
        return {"type": _BUILTIN_TYPE_MAP[t]}

    # Handle Union / Optional (typing.Union)
    if origin is Union:
        args = get_args(t)
        non_none_args = [a for a in args if a is not type(None)]
        nullable = len(non_none_args) < len(args)  # True if NoneType was in args
        if len(non_none_args) == 1:
            # Optional[X] — single non-None type
            inner = _type_to_schema(non_none_args[0])
            if inner is None:
                return None
            if nullable:
                return {**inner, "nullable": True}
            return inner
        else:
            # Union[X, Y, ...] — multiple non-None types
            schemas = [_type_to_schema(a) for a in non_none_args]
            schemas = [s for s in schemas if s is not None]
            if not schemas:
                return None
            result: dict[str, Any] = {"oneOf": schemas}
            if nullable:
                result["nullable"] = True
            return result

    # Handle Python 3.10+ union syntax (X | Y) which uses types.UnionType
    try:
        if isinstance(t, types.UnionType):
            args = get_args(t)
            non_none_args = [a for a in args if a is not type(None)]
            nullable = len(non_none_args) < len(args)
            if len(non_none_args) == 1:
                inner = _type_to_schema(non_none_args[0])
                if inner is None:
                    return None
                if nullable:
                    return {**inner, "nullable": True}
                return inner
            else:
                schemas = [_type_to_schema(a) for a in non_none_args]
                schemas = [s for s in schemas if s is not None]
                if not schemas:
                    return None
                result = {"oneOf": schemas}
                if nullable:
                    result["nullable"] = True
                return result
    except AttributeError:
        pass  # Python < 3.10 — types.UnionType does not exist

    # Fallback: use the type name as a JSON Schema title (not as "type" — that's invalid)
    type_name = getattr(t, "__name__", str(t))
    return {"type": "object", "title": type_name}


# SA-B5 fix: public alias so callers can import type_to_schema without
# depending on a private name. The private _type_to_schema is kept for
# backward compatibility with any existing call sites.
type_to_schema = _type_to_schema
