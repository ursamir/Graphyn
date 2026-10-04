# app/core/runs/prove.py
"""
Bounded Context:  BC6 — Observability (Prove pillar)
Responsibility:   Normative AUD-PROV-010 capture set for terminal runs
                  (``prove.json``) — a thin typed facade over
                  app.core.runs.audit_record, which builds, hash-chains and
                  verifies the record (schema 2.0).
Owns:             ProveCaptureRecord, REQUIRED_PROVE_FIELDS.
Public Surface:   build_prove_capture, write_prove_capture, load_prove_capture,
                  required_fields_present
Must NOT:         Import app.api or orchestrator.
Dependencies:     stdlib, pydantic, app.core.runs.audit_record (lazy).
Reason To Change: SRS §22.2 Prove capture set evolves.
"""
from __future__ import annotations

import json
import logging
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
    """Immutable Prove-pillar capture for a terminal run (SRS §22.2).

    Schema 2.0 adds structured ``pipeline_version`` / ``environment`` /
    ``node_implementation_versions`` objects and the audit fields
    (external_inputs, outputs, cache, record_hash, chain …) as extras.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    run_id: str
    graph_hash: str
    graph_schema_version: str
    pipeline_version: Optional[Any] = None
    dataset_versions: list[dict[str, Any]] = Field(default_factory=list)
    input_artifact_hashes: list[str] = Field(default_factory=list)
    node_implementation_versions: dict[str, Any] = Field(default_factory=dict)
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
    environment: Optional[Any] = None
    timestamp: str
    schema_version: str = "1.0"


def build_prove_capture(
    *,
    run_id: str,
    graph_hash: str = "",
    meta: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    artifacts: list[Any] | None = None,
    run_dir: str | Path | None = None,
    status: str = "succeeded",
) -> ProveCaptureRecord:
    """Assemble (without sealing) a record from run meta + graph/artifacts."""
    from app.core.runs.audit_record import build_record

    meta = dict(meta or {})
    if graph_hash and not meta.get("graph_hash"):
        meta["graph_hash"] = graph_hash
    rec = build_record(
        Path(run_dir) if run_dir else Path("."),
        run_id=run_id,
        status=str(meta.get("status") or status),
        meta=meta,
        graph=dict(graph or {}),
        artifacts=artifacts,
        include_outputs=run_dir is not None,
    )
    return ProveCaptureRecord.model_validate(rec)


def write_prove_capture(
    run_dir: str | Path,
    *,
    run_id: str,
    graph_hash: str = "",
    meta: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    artifacts: list[Any] | None = None,
    status: str = "succeeded",
) -> ProveCaptureRecord | None:
    """Seal immutable ``prove.json`` under the run directory (first-writer-wins)."""
    from app.core.runs.audit_record import load_record, seal_run_record

    meta = dict(meta or {})
    if graph_hash and not meta.get("graph_hash"):
        meta["graph_hash"] = graph_hash
    rec = seal_run_record(run_dir, run_id=run_id, status=status, meta=meta, graph=graph, artifacts=artifacts)
    if rec is None:
        rec = load_record(run_dir)
    if rec is None:
        return None
    try:
        return ProveCaptureRecord.model_validate(rec)
    except Exception:
        return None


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
