# app/core/execution/cache_rescope.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Keep pipeline-cache hits run-local: decide whether a node may
                  use the cache at all (plugin ``cacheable``), and re-home cached
                  outputs that embed another run's ``artifacts/<slug>/runs/<id>``
                  paths into the current run before they are handed downstream.
Owns:             node_is_cacheable(), rescope_cached_outputs().
Public Surface:   node_is_cacheable(node_type, ir_node=None) -> bool
                  rescope_cached_outputs(outputs, run_id) -> Any | None
Must NOT:         Compute cache keys, read/write the cache store, or know any
                  domain model (pydantic models are walked duck-typed).
Dependencies:     stdlib (re, shutil, pathlib), app.core.host.registry_runtime
                  (lazy), app.core.paths.workspace_paths.artifact_fs_path (lazy).
Reason To Change: Run-scoped artifact layout changes, or cache identity policy
                  for path-bearing outputs changes.

Cache identity stays on the *logical* config (so seeds/hashes are stable across
runs), but a node's materialized config writes into
``workspace/artifacts/<slug>/runs/<run_id>/``. A hit recorded by run A would
otherwise return run A's paths to run B. On a hit we copy every referenced
run-A file/dir into the matching run-B location and rewrite the strings; when
that is impossible (source deleted, reference inside free text or an opaque
object) the hit is discarded and the node re-executes.
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ``…artifacts/<slug>/runs/<run_id>`` (posix workspace form or absolute fs path).
_RUN_SEGMENT_RE = re.compile(r"(?P<head>(?:^|/)artifacts/[^/\s]+/runs/)(?P<rid>[^/\s]+)")
_MAX_DEPTH = 32


class _NotRescopable(Exception):
    """A foreign run reference that cannot be safely re-homed."""


def node_is_cacheable(node_type: str, ir_node: Any = None) -> bool:
    """True unless the node (plugin metadata, IR override) declares cacheable=False.

    Checked *before* ``cache.load`` so a stale entry written while a node was
    (wrongly) cacheable can never be served afterwards.
    """
    try:
        from app.core.host.registry_runtime import get_registry, resolve_capability

        registry = get_registry()
        if ir_node is not None:
            return bool(resolve_capability(ir_node, registry).cacheable)
        return bool(registry.get_metadata(node_type).cacheable)
    except Exception:
        return True


def _fs_path(text: str) -> Path:
    if text.startswith("/"):
        return Path(text)
    from app.core.paths.workspace_paths import artifact_fs_path

    return artifact_fs_path(text)


def _rewrite_str(value: str, run_id: str, copies: list[tuple[str, str]]) -> str:
    matches = [m for m in _RUN_SEGMENT_RE.finditer(value) if m.group("rid") != run_id]
    if not matches:
        return value
    if any(ch.isspace() for ch in value) or len(matches) > 1:
        # Free text / multiple runs in one string: cannot map to one path.
        raise _NotRescopable(value)
    m = matches[0]
    new = value[: m.start("rid")] + run_id + value[m.end("rid"):]
    copies.append((value, new))
    return new


def _walk(value: Any, run_id: str, copies: list[tuple[str, str]], depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return value
    if isinstance(value, str):
        return _rewrite_str(value, run_id, copies)
    if isinstance(value, Path):
        text = value.as_posix()
        new = _rewrite_str(text, run_id, copies)
        return value if new == text else Path(new)
    if value is None or isinstance(value, (bool, int, float, bytes)):
        return value
    if isinstance(value, dict):
        out = {k: _walk(v, run_id, copies, depth + 1) for k, v in value.items()}
        return value if all(out[k] is value[k] for k in value) else out
    if isinstance(value, (list, tuple)):
        items = [_walk(v, run_id, copies, depth + 1) for v in value]
        if all(a is b for a, b in zip(items, value)):
            return value
        return type(value)(items) if isinstance(value, tuple) else items
    fields = getattr(type(value), "model_fields", None)
    if isinstance(fields, dict) and hasattr(value, "model_copy"):
        update: dict[str, Any] = {}
        for name in fields:
            cur = getattr(value, name, None)
            new = _walk(cur, run_id, copies, depth + 1)
            if new is not cur:
                update[name] = new
        return value.model_copy(update=update) if update else value
    return value


def _materialize(copies: list[tuple[str, str]]) -> None:
    for src_text, dst_text in copies:
        src, dst = _fs_path(src_text), _fs_path(dst_text)
        if dst.exists():
            continue
        if not src.exists():
            raise _NotRescopable(src_text)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def rescope_cached_outputs(outputs: Any, run_id: str | None) -> Any | None:
    """Return ``outputs`` re-homed into ``run_id``'s artifact dir, or None (= miss).

    Outputs without foreign run paths are returned unchanged (same object).
    """
    rid = str(run_id or "").strip()
    if not rid or outputs is None:
        return outputs
    copies: list[tuple[str, str]] = []
    try:
        rewritten = _walk(outputs, rid, copies, 0)
        if copies:
            _materialize(copies)
    except _NotRescopable as exc:
        log.info("cache hit discarded: output references another run (%s)", exc)
        return None
    except OSError as exc:
        log.warning("cache hit discarded: copying run-scoped outputs failed (%s)", exc)
        return None
    return rewritten
