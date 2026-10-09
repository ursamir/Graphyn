# app/core/nodes/payload.py
"""
Bounded Context:  Node runtime (shared by every plugin)
Responsibility:   The ONE canonical inter-node payload contract (F19 / F-06).
Public Surface:   unwrap_payload(value) -> Any
                  payload_paths(value) -> list[str]
                  WRAPPER_FIELDS

Many nodes emit a thin *wrapper* around the value the user cares about:
``python_code`` → ``CodeResult{data, metadata}``, ``csv_table`` →
``CsvTableResult{rows, …}``, ``set_map`` → ``MappedPayload{data}``,
``http_request`` → ``HttpResponse{body, …}`` … Downstream nodes must operate on
the *payload*, not on the wrapper. Every consumer calls :func:`unwrap_payload`
so the rule lives in exactly one place:

* known wrapper instance → its payload field (recursively, so a wrapper of a
  wrapper unwraps fully)
* the same wrapper serialised as a dict (Mode B transfer, JSON round-trip)
  → detected by its exact field set, then unwrapped
* any other ``PortDataType`` / pydantic model → ``model_dump()`` (plain dict)
* lists / tuples → each element unwrapped
* everything else → unchanged

``payload_paths`` is the matching rule for nodes that consume *files*
(object_store put): strings, ``Path``, ``.path`` attributes, dicts with
``path``/``paths``/``file``/``files``/``uri``, ArtifactRefs, nested lists.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# wrapper class name -> payload field
WRAPPER_FIELDS: dict[str, str] = {
    "CodeResult": "data",
    "JsonDocument": "data",
    "MappedPayload": "data",
    "MergedPayload": "data",
    "StructuredDocument": "data",
    "CsvTableResult": "rows",
    "HttpResponse": "body",
    "BranchResult": "payload",
}

# exact dict field sets of the wrappers above (serialised form)
_DICT_SIGNATURES: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"data", "metadata"}), "data"),
    (frozenset({"data", "mode", "metadata"}), "data"),
    (frozenset({"data", "schema_name", "provider", "raw_text", "metadata"}), "data"),
    (frozenset({"path", "operation", "rows", "row_count", "metadata", "refs"}), "rows"),
    (frozenset({"url", "method", "status_code", "ok", "headers", "body", "text", "metadata"}), "body"),
    (frozenset({"matched", "branch", "payload", "metadata"}), "payload"),
)

_MAX_DEPTH = 8


def wrapper_field(value: Any) -> str | None:
    """Payload field name when *value* is a known wrapper (instance or dict form)."""
    if isinstance(value, dict):
        keys = frozenset(value.keys())
        for sig, fld in _DICT_SIGNATURES:
            if keys == sig:
                return fld
        return None
    name = type(value).__name__
    fld = WRAPPER_FIELDS.get(name)
    if fld and hasattr(value, fld):
        return fld
    return None


def unwrap_payload(value: Any, *, _depth: int = 0) -> Any:
    """Return the user payload carried by *value* (see module docstring)."""
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return value
    if _depth > _MAX_DEPTH:
        return value
    fld = wrapper_field(value)
    if fld is not None:
        inner = value[fld] if isinstance(value, dict) else getattr(value, fld)
        return unwrap_payload(inner, _depth=_depth + 1)
    if isinstance(value, (list, tuple)):
        return [unwrap_payload(v, _depth=_depth + 1) for v in value]
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        try:
            return value.model_dump(mode="json")
        except Exception:
            try:
                return value.model_dump()
            except Exception:
                return value
    return value


_PATH_KEYS = ("path", "file", "filepath", "file_path", "local_path", "source_path", "uri")
_PATHS_KEYS = ("paths", "files", "file_paths", "outputs")


def _looks_local(text: str) -> bool:
    t = text.strip()
    if not t or "\n" in t or len(t) > 4096:
        return False
    if "://" in t and not t.startswith("file://"):
        return False
    return True


def payload_paths(value: Any, *, _depth: int = 0) -> list[str]:
    """File paths carried by *value* (wrappers, dicts, ``.path`` objects, lists)."""
    out: list[str] = []
    if value is None or _depth > _MAX_DEPTH:
        return out
    if isinstance(value, Path):
        return [str(value)]
    if isinstance(value, str):
        text = value[len("file://"):] if value.startswith("file://") else value
        return [text] if _looks_local(text) else []
    if isinstance(value, (list, tuple, set)):
        for v in value:
            out.extend(payload_paths(v, _depth=_depth + 1))
        return out
    if isinstance(value, dict):
        for k in _PATH_KEYS:
            v = value.get(k)
            if isinstance(v, (str, Path)) and str(v).strip():
                out.extend(payload_paths(v, _depth=_depth + 1))
                break
        for k in _PATHS_KEYS:
            if isinstance(value.get(k), (list, tuple)):
                out.extend(payload_paths(value[k], _depth=_depth + 1))
        if not out and "data" in value:
            out.extend(payload_paths(value.get("data"), _depth=_depth + 1))
        return out
    # objects: ArtifactRef / CsvTableResult / ObjectRef / any `.path`
    for attr in ("path", "source_path", "local_path", "file_path"):
        v = getattr(value, attr, None)
        if isinstance(v, (str, Path)) and str(v).strip():
            out.extend(payload_paths(v, _depth=_depth + 1))
            break
    if not out:
        refs = getattr(value, "refs", None)
        if isinstance(refs, (list, tuple)) and refs:
            for r in refs:
                out.extend(payload_paths(r, _depth=_depth + 1))
    if not out and hasattr(value, "data"):
        out.extend(payload_paths(getattr(value, "data"), _depth=_depth + 1))
    if not out and hasattr(value, "paths"):
        out.extend(payload_paths(getattr(value, "paths"), _depth=_depth + 1))
    return out


__all__ = ["WRAPPER_FIELDS", "payload_paths", "unwrap_payload", "wrapper_field"]
