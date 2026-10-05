# app/core/execution/run_inputs.py
"""
Bounded Context:  BC5 — Execution Runtime (run preparation)
Responsibility:   Validate caller-supplied run inputs (``{node_id: {port:
                  value}}`` → ``input_overrides``) and graph parameters, and
                  stamp their fingerprints into run meta for audit.
Owns:             RunInputsError, prepare_run_inputs(), prepare_parameters(),
                  persist_run_inputs_meta(), inputs_max_bytes(), canonical_sha256().
Public Surface:   The functions above. Meta fields written: ``inputs_sha256``,
                  ``input_keys`` (["node.port", …]), ``inputs_bytes``,
                  ``parameters_sha256``, ``parameter_names``.
Must NOT:         Import app.api or app.domain; log input values.
Dependencies:     stdlib (hashlib, json, os), app.core.ir.parameters,
                  app.core.host.registry_runtime (port lookup, optional).
Reason To Change: Input size policy, validation rules or meta fields change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_MAX_BYTES = 1024 * 1024


class RunInputsError(ValueError):
    """Run inputs / parameters are malformed, too large, or reference unknown ports."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def inputs_max_bytes() -> int:
    """``GRAPHYN_RUN_INPUTS_MAX_BYTES`` (default 1 MiB)."""
    raw = (os.environ.get("GRAPHYN_RUN_INPUTS_MAX_BYTES") or "").strip()
    try:
        return max(1, int(raw)) if raw else _DEFAULT_MAX_BYTES
    except ValueError:
        return _DEFAULT_MAX_BYTES


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _input_ports_for(node_type: str) -> set[str] | None:
    try:
        from app.core.host.registry_runtime import get_registry

        cls = get_registry().get_class(node_type)
    except Exception:
        return None
    ports = getattr(cls, "input_ports", None)
    return set(ports) if isinstance(ports, dict) else None


def prepare_run_inputs(
    graph: Any, raw: Any, *, max_bytes: int | None = None
) -> tuple[dict[str, dict[str, Any]] | None, dict[str, Any]]:
    """Validate ``raw`` run inputs against ``graph``.

    Returns ``(input_overrides or None, meta_fields)``. Raises RunInputsError
    (413 when over the size cap, 422 otherwise).
    """
    if raw is None or raw == {}:
        return None, {}
    if not isinstance(raw, dict):
        raise RunInputsError("inputs must be an object {node_id: {port: value}}")
    limit = int(max_bytes or inputs_max_bytes())
    try:
        blob = canonical_bytes(raw)
    except (TypeError, ValueError) as exc:
        raise RunInputsError(f"inputs must be JSON-serializable: {exc}") from exc
    if len(blob) > limit:
        raise RunInputsError(
            f"inputs are {len(blob)} bytes; limit is {limit} (GRAPHYN_RUN_INPUTS_MAX_BYTES)",
            status_code=413,
        )
    nodes = {n.id: n for n in getattr(graph, "nodes", [])}
    overrides: dict[str, dict[str, Any]] = {}
    keys: list[str] = []
    for node_id, ports in raw.items():
        if node_id not in nodes:
            raise RunInputsError(f"inputs reference unknown node {node_id!r}")
        if not isinstance(ports, dict) or not ports:
            raise RunInputsError(f"inputs[{node_id!r}] must be a non-empty object {{port: value}}")
        known = _input_ports_for(nodes[node_id].node_type)
        for port in ports:
            if not isinstance(port, str) or not port:
                raise RunInputsError(f"inputs[{node_id!r}] has an invalid port name")
            if known is not None and port not in known:
                raise RunInputsError(
                    f"node {node_id!r} ({nodes[node_id].node_type}) has no input port "
                    f"{port!r}; available: {sorted(known)}"
                )
            keys.append(f"{node_id}.{port}")
        overrides[node_id] = dict(ports)
    meta = {
        "inputs_sha256": hashlib.sha256(blob).hexdigest(),
        "input_keys": sorted(keys),
        "inputs_bytes": len(blob),
    }
    return overrides, meta


def prepare_parameters(graph: Any, raw: Any) -> tuple[Any, dict[str, Any]]:
    """Apply graph parameters; returns ``(graph, meta_fields)``."""
    from app.core.ir.parameters import ParameterError, apply_parameters, resolve_parameter_values

    if raw is not None and not isinstance(raw, dict):
        raise RunInputsError("parameters must be an object {name: value}")
    declared = getattr(graph, "parameters", None) or {}
    if not declared and not raw:
        return graph, {}
    try:
        values = resolve_parameter_values(graph, raw or {})
        new_graph = apply_parameters(graph, raw or {})
    except ParameterError as exc:
        raise RunInputsError(str(exc)) from exc
    return new_graph, {
        "parameters_sha256": canonical_sha256(values),
        "parameter_names": sorted(values),
    }


def persist_run_inputs_meta(run_manager: Any, fields: dict[str, Any]) -> None:
    """Write input / parameter fingerprints into run meta (never raises)."""
    writer = getattr(run_manager, "_write_meta_field", None)
    if not callable(writer):
        return
    for key, value in (fields or {}).items():
        try:
            writer(key, value)
        except Exception:
            log.debug("run_inputs: could not persist %s", key, exc_info=True)


# ── Retained inputs (exact replay) ───────────────────────────────────────────

RUN_INPUTS_FILE = "inputs.json"


def inputs_retention_enabled() -> bool:
    """``GRAPHYN_RETAIN_RUN_INPUTS`` (default on): keep run inputs for exact replay."""
    import os

    return os.environ.get("GRAPHYN_RETAIN_RUN_INPUTS", "1").strip().lower() not in ("0", "false", "no", "off")


def persist_run_inputs(run_manager: Any, overrides: dict[str, Any] | None) -> None:
    """Keep the exact run inputs next to the journal (``runs/<id>/inputs.json``).

    Without them "Replay exactly" of a webhook / input-driven run would run on
    no payload and silently take a different path. The record keeps only the
    sha256; this file holds the values (opt out with GRAPHYN_RETAIN_RUN_INPUTS=0,
    in which case replay refuses instead of guessing). Never raises.
    """
    if not overrides:
        return
    writer = getattr(run_manager, "_write_meta_field", None)
    retained = False
    if inputs_retention_enabled():
        try:
            run_dir = getattr(run_manager, "base_path", None) or getattr(run_manager, "run_dir", None)
            if run_dir is not None:
                from pathlib import Path

                path = Path(run_dir) / RUN_INPUTS_FILE
                path.write_bytes(canonical_bytes(overrides))
                retained = True
        except Exception:
            retained = False
    if callable(writer):
        try:
            writer("inputs_retained", retained)
        except Exception:
            pass


def load_retained_inputs(run_dir: Any, expected_sha256: str | None) -> dict[str, Any] | None:
    """Inputs saved for ``run_dir`` if present and matching ``expected_sha256``.

    Returns None when not retained. Raises ValueError when the file exists but
    its hash differs from the recorded one (tampered / corrupted).
    """
    import json
    from pathlib import Path

    path = Path(run_dir) / RUN_INPUTS_FILE
    if not path.is_file():
        return None
    blob = path.read_bytes()
    actual = hashlib.sha256(blob).hexdigest()
    if expected_sha256 and actual != expected_sha256:
        raise ValueError(f"retained inputs hash {actual[:12]} does not match the record {expected_sha256[:12]}")
    data = json.loads(blob.decode("utf-8"))
    return data if isinstance(data, dict) else None
