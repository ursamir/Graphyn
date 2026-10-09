# app/core/nodes/type_names.py
"""
Bounded Context:  BC2 — Node Contract
Responsibility:   Canonical string labels for port data types, and the reverse
                  parse (label → Python type) used by the catalog / UI wire check.
Owns:             type_label(), parse_type_label().
Must NOT:         Import plugin modules (only resolves modules already loaded).
Reason To Change: New typing constructs appear in port declarations.

F19 / F-22: ``list[AudioSample]`` used to serialise as ``builtins.list`` (a
GenericAlias proxies ``__module__``/``__qualname__`` to ``list``), so the
catalog lost the element type and the UI's wire-time check had nothing to
compare. Labels now keep generics and unions, e.g.
``builtins.list[app.core.data_types.AudioSample]`` or
``builtins.object | None``, and parse back to the same type.
"""
from __future__ import annotations

import builtins
import functools
import operator
import sys
import types
import typing
from typing import Any, Callable, Union, get_args, get_origin

_UNION_ORIGINS = {Union, getattr(types, "UnionType", Union)}


def type_label(t: Any) -> str | None:
    """Return the canonical label for a port data type (``None`` → ``None``)."""
    if t is None:
        return None
    return _label(t)


def _label(t: Any) -> str:
    if t is None or t is type(None):
        return "None"
    if t is Any:
        return "typing.Any"
    origin = get_origin(t)
    if origin in _UNION_ORIGINS:
        return " | ".join(_label(a) for a in get_args(t))
    if origin is not None:
        args = get_args(t)
        base = _label(origin)
        if not args:
            return base
        return f"{base}[{', '.join('...' if a is Ellipsis else _label(a) for a in args)}]"
    if isinstance(t, type):
        return f"{t.__module__}.{t.__qualname__}"
    return str(t)


def _split_top(s: str, sep: str) -> list[str]:
    """Split *s* on *sep* where it is not nested inside brackets."""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth < 0:
                raise ValueError(f"unbalanced ']' in type label {s!r}")
        if depth == 0 and s.startswith(sep, i):
            out.append("".join(cur).strip())
            cur = []
            i += len(sep)
            continue
        cur.append(ch)
        i += 1
    if depth != 0:
        raise ValueError(f"unbalanced '[' in type label {s!r}")
    out.append("".join(cur).strip())
    return out


def _resolve_name(name: str, lookup: Callable[[str], type] | None) -> Any:
    if name == "None":
        return type(None)
    if name in ("typing.Any", "Any"):
        return Any
    if name == "...":
        return Ellipsis
    if "." not in name:
        name = f"builtins.{name}"
    mod_name, _, qual = name.rpartition(".")
    if mod_name == "builtins":
        obj = getattr(builtins, qual, None)
        if isinstance(obj, type):
            return obj
        raise LookupError(f"unknown builtin type {qual!r}")
    if mod_name == "typing":
        obj = getattr(typing, qual, None)
        if obj is not None:
            return obj
    if lookup is not None:
        try:
            return lookup(name)
        except Exception:
            pass
    mod = sys.modules.get(mod_name)
    if mod is not None:
        obj: Any = mod
        for part in qual.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                break
        if isinstance(obj, type):
            return obj
    raise LookupError(f"unknown port type {name!r}")


def parse_type_label(label: str, lookup: Callable[[str], type] | None = None) -> Any:
    """Parse a label produced by :func:`type_label` back into a Python type.

    *lookup* resolves registered port types by fully-qualified name (e.g.
    ``TypeCatalogue.resolve``); builtins, ``None`` and ``typing.Any`` are
    handled here, and other names fall back to already-imported modules.
    Raises ``LookupError`` / ``ValueError`` for unknown or malformed labels.
    """
    s = (label or "").strip()
    if not s:
        raise ValueError("empty type label")
    parts = _split_top(s, "|")
    if len(parts) > 1:
        members = [parse_type_label(p, lookup) for p in parts]
        return functools.reduce(operator.or_, members)
    if s.endswith("]") and "[" in s:
        base_s, _, rest = s.partition("[")
        base = _resolve_name(base_s.strip(), lookup)
        arg_s = rest[:-1]
        args = tuple(parse_type_label(a, lookup) if a != "..." else Ellipsis for a in _split_top(arg_s, ","))
        return base[args if len(args) > 1 else args[0]]
    return _resolve_name(s, lookup)
