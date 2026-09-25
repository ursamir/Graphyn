# app/core/prove.py
"""
Bounded Context:  BC6 — Observability (Prove pillar)
Responsibility:   Normative AUD-PROV-010 capture set for terminal runs.
Owns:             ProveCaptureRecord, REQUIRED_PROVE_FIELDS, write_prove_capture.
Public Surface:   build_prove_capture, write_prove_capture, load_prove_capture,
                  required_fields_present
Must NOT:         Import app.api or orchestrator.
Dependencies:     stdlib, pydantic, app.__version__, sys
Reason To Change: SRS §22.2 Prove capture set evolves.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

# Normative minimum reproducibility fields (AUD-PROV-010). Values may be null
# where the SRS marks YES* (always present; null allowed).
REQUIRED_PROVE_FIELDS: tuple[str, ...] = (
    "graph_hash",
    "graph_schema_version",
    "pipeline_version",
    "dataset_versions",
    "input_artifact_hashes",
    "node_implementation_versions",
    "plugin_version",
    "runtime_version",
    "graphyn_version",
    "worker_id",
    "worker_software_version",
    "configuration",
    "seed",
    "actor",
    "trigger",
    "environment",
    "timestamp",
)


class ProveCaptureRecord(BaseModel):
    """Immutable Prove-pillar capture for a terminal run (SRS §22.2)."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    graph_hash: str
    graph_schema_version: str
    pipeline_version: Optional[str] = None
    dataset_versions: list[dict[str, Any]] = Field(default_factory=list)
    input_artifact_hashes: list[str] = Field(default_factory=list)
    node_implementation_versions: dict[str, str] = Field(default_factory=dict)
    plugin_version: dict[str, str] = Field(default_factory=dict)
    model_version: Optional[dict[str, Any]] = None
    runtime_version: str
    graphyn_version: str
    worker_id: Optional[str] = None
    worker_software_version: Optional[str] = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    seed: Optional[int] = None
    actor: str = "system"
    trigger: str = "api"
    environment: Optional[str] = None
    timestamp: str
    schema_version: str = "1.0"


def _platform_graphyn_version() -> str:
    try:
        import app as _app

        ver = getattr(_app, "__version__", None)
        if isinstance(ver, str) and ver.strip():
            return ver.strip()
    except Exception:
        pass
    return "unknown"


def _runtime_version() -> str:
    return f"python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}/{platform.system()}"


def _safe_plugin_versions() -> dict[str, str]:
    try:
        from app.core.plugins.store import PluginStore

        store = PluginStore()
        out: dict[str, str] = {}
        for name, rec in (getattr(store, "_plugins", None) or {}).items():
            if isinstance(rec, dict):
                ver = rec.get("version") or rec.get("installed_version") or ""
                if ver:
                    out[str(name)] = str(ver)
        return out
    except Exception:
        return {}


def _node_impl_versions(node_types: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not node_types:
        return out
    try:
        from app.core.nodes import registry

        for nt in node_types:
            if nt in out:
                continue
            cls = registry.get(nt) if hasattr(registry, "get") else None
            if cls is None:
                try:
                    cls = registry[nt]  # type: ignore[index]
                except Exception:
                    cls = None
            ver = getattr(cls, "VERSION", None) or getattr(cls, "version", None) or "builtin"
            out[nt] = str(ver)
    except Exception:
        for nt in node_types:
            out.setdefault(nt, "unknown")
    return out


def build_prove_capture(
    *,
    run_id: str,
    graph_hash: str = "",
    meta: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    artifacts: list[Any] | None = None,
) -> ProveCaptureRecord:
    """Assemble a ProveCaptureRecord from run meta + optional graph/artifacts."""
    meta = dict(meta or {})
    graph = dict(graph or {})
    graph_meta = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}

    schema_ver = (
        str(graph.get("schema_version") or meta.get("graph_schema_version") or "")
        or "unknown"
    )
    seed_raw = graph_meta.get("seed", meta.get("seed"))
    seed: Optional[int]
    try:
        seed = int(seed_raw) if seed_raw is not None else None
    except (TypeError, ValueError):
        seed = None

    node_types: list[str] = []
    for n in graph.get("nodes") or []:
        if isinstance(n, dict) and n.get("type"):
            node_types.append(str(n["type"]))
    for s in meta.get("node_stats") or []:
        if isinstance(s, dict) and s.get("node_type"):
            node_types.append(str(s["node_type"]))

    input_hashes: list[str] = []
    for a in artifacts or []:
        if hasattr(a, "content_hash") and getattr(a, "content_hash"):
            input_hashes.append(str(a.content_hash))
        elif isinstance(a, dict) and a.get("content_hash"):
            input_hashes.append(str(a["content_hash"]))
        elif hasattr(a, "artifact_id"):
            # Prefer content-addressed id when hash missing
            aid = str(getattr(a, "artifact_id"))
            if aid and aid not in input_hashes:
                pass  # output artifacts — capture as empty inputs set below
    # Prefer explicit input hashes from meta when present
    if isinstance(meta.get("input_artifact_hashes"), list):
        input_hashes = [str(x) for x in meta["input_artifact_hashes"]]

    dataset_versions = meta.get("dataset_versions")
    if not isinstance(dataset_versions, list):
        dataset_versions = []

    configuration: dict[str, Any] = {}
    if isinstance(meta.get("configuration"), dict):
        configuration = dict(meta["configuration"])
    elif isinstance(meta.get("params"), dict):
        configuration = dict(meta["params"])
    # Non-secret node configs from graph (names only for secret refs — leave as-is)
    if graph.get("nodes") and "nodes" not in configuration:
        configuration["node_ids"] = [
            str(n.get("id")) for n in (graph.get("nodes") or []) if isinstance(n, dict)
        ]

    actor = str(meta.get("actor") or os.environ.get("GRAPHYN_ACTOR") or "system")
    trigger = str(meta.get("trigger") or "api")
    environment = meta.get("environment")
    if environment is not None:
        environment = str(environment)

    plugin_version = meta.get("plugin_version")
    if not isinstance(plugin_version, dict):
        plugin_version = _safe_plugin_versions()

    return ProveCaptureRecord(
        run_id=run_id,
        graph_hash=str(graph_hash or meta.get("graph_hash") or ""),
        graph_schema_version=schema_ver,
        pipeline_version=meta.get("pipeline_version"),
        dataset_versions=list(dataset_versions),
        input_artifact_hashes=list(input_hashes),
        node_implementation_versions=_node_impl_versions(node_types),
        plugin_version={str(k): str(v) for k, v in plugin_version.items()},
        model_version=meta.get("model_version") if isinstance(meta.get("model_version"), dict) else None,
        runtime_version=str(meta.get("runtime_version") or _runtime_version()),
        graphyn_version=str(meta.get("graphyn_version") or _platform_graphyn_version()),
        worker_id=meta.get("worker_id"),
        worker_software_version=meta.get("worker_software_version"),
        configuration=configuration,
        seed=seed,
        actor=actor,
        trigger=trigger,
        environment=environment,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def write_prove_capture(
    run_dir: str | Path,
    *,
    run_id: str,
    graph_hash: str = "",
    meta: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    artifacts: list[Any] | None = None,
) -> ProveCaptureRecord:
    """Write immutable ``prove.json`` under the run directory (first-writer-wins)."""
    rec = build_prove_capture(
        run_id=run_id,
        graph_hash=graph_hash,
        meta=meta,
        graph=graph,
        artifacts=artifacts,
    )
    path = Path(run_dir) / "prove.json"
    if path.exists():
        return rec
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec.model_dump(mode="json"), indent=2), encoding="utf-8")
    tmp.replace(path)
    return rec


def load_prove_capture(run_dir: str | Path) -> Optional[ProveCaptureRecord]:
    path = Path(run_dir) / "prove.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ProveCaptureRecord.model_validate(data)
    except Exception as exc:
        log.warning("prove: failed to load %s: %s", path, exc)
        return None


def required_fields_present(rec: ProveCaptureRecord | dict[str, Any]) -> list[str]:
    """Return list of missing REQUIRED_PROVE_FIELDS (empty = complete)."""
    data = rec.model_dump(mode="json") if isinstance(rec, ProveCaptureRecord) else dict(rec)
    missing: list[str] = []
    for key in REQUIRED_PROVE_FIELDS:
        if key not in data:
            missing.append(key)
    return missing
