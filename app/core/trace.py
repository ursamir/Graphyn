# app/core/trace.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Assemble a unified backtrack (Trace) payload from artifact /
                  run / node identifiers for Accountability UX.
Owns:             assemble_trace() and related helpers.
Public Surface:   assemble_trace(artifact_id=, run_id=, node_id=).
Must NOT:         Import from app.api.
Dependencies:     ArtifactStore, ProvenanceStore, runs meta on disk.
Reason To Change: Trace payload shape evolves or new lineage sources appear.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("trace: failed to read %s (%s)", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _load_run_meta(run_id: str) -> dict[str, Any] | None:
    from app.core.config import runs_dir

    if not run_id or not _RUN_ID_RE.match(run_id):
        return None
    runs_root = runs_dir().resolve()
    path = (runs_root / run_id).resolve()
    try:
        if not path.is_relative_to(runs_root):
            return None
    except AttributeError:
        # Python < 3.9 fallback — not expected on this codebase
        if runs_root not in path.parents and path != runs_root:
            return None
    meta = _safe_load_json(path / "meta.json")
    if meta is None and not path.exists():
        return None
    if meta is None:
        return {"run_id": run_id}
    out = dict(meta)
    out.setdefault("run_id", run_id)
    return out


def _load_run_graph_summary(run_id: str, meta: dict[str, Any] | None) -> dict[str, Any] | None:
    from app.core.config import runs_dir

    if not run_id or not _RUN_ID_RE.match(run_id):
        return None
    run_path = runs_dir() / run_id
    graph: dict[str, Any] | None = None
    for name in ("graph.json", "ir.json", "pipeline.graph.json"):
        graph = _safe_load_json(run_path / name)
        if graph:
            break
    if graph is None:
        # Some runs store config.yaml only — still surface meta fields.
        if not meta:
            return None
        return {
            "name": meta.get("graph_name"),
            "schema_version": meta.get("schema_version") or meta.get("ir_version"),
            "node_count": None,
            "hash": meta.get("graph_hash"),
        }

    nodes = graph.get("nodes")
    node_count = len(nodes) if isinstance(nodes, list) else None
    gmeta = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}
    name = (
        (meta or {}).get("graph_name")
        or gmeta.get("name")
        or graph.get("name")
    )
    schema_version = (
        graph.get("schema_version")
        or gmeta.get("schema_version")
        or (meta or {}).get("schema_version")
        or (meta or {}).get("ir_version")
    )
    graph_hash = (meta or {}).get("graph_hash") or gmeta.get("graph_hash")
    return {
        "name": name,
        "schema_version": schema_version,
        "node_count": node_count,
        "hash": graph_hash,
    }


def _flatten_lineage_inputs(lineage: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract immediate input summaries from a provenance lineage tree."""
    if not lineage or not isinstance(lineage, dict):
        return []
    raw = lineage.get("inputs")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append({"artifact_id": item, "error": None})
            continue
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "artifact_id": item.get("artifact_id"),
                "run_id": item.get("run_id"),
                "node_id": item.get("node_id"),
                "node_type": item.get("node_type"),
                "error": item.get("error"),
            }
        )
    return out


def _chain_step(step: str, label: str, **extra: Any) -> dict[str, Any]:
    row = {"step": step, "label": label}
    row.update({k: v for k, v in extra.items() if v is not None})
    return row


def assemble_trace(
    *,
    artifact_id: str | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Build a unified Trace backtrack payload.

    Partial chains are returned when pieces are missing (never raises for
    missing stores). Raises ``ValueError`` only when neither artifact_id nor
    run_id is provided, or when IDs fail basic format checks.
    """
    artifact_id = (artifact_id or "").strip() or None
    run_id = (run_id or "").strip() or None
    node_id = (node_id or "").strip() or None

    if not artifact_id and not run_id:
        raise ValueError("Provide artifact_id and/or run_id")
    if artifact_id and not _ARTIFACT_ID_RE.match(artifact_id):
        raise ValueError("Invalid artifact_id")
    if run_id and not _RUN_ID_RE.match(run_id):
        raise ValueError("Invalid run_id")

    from app.core.artifact_store import ArtifactNotFoundError, ArtifactStore
    from app.core.provenance import ProvenanceStore

    warnings: list[str] = []
    artifact_record: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    lineage_tree: dict[str, Any] | None = None

    subject: dict[str, Any]
    if artifact_id:
        subject = {"kind": "artifact", "id": artifact_id}
    else:
        subject = {"kind": "run", "id": run_id}

    # ── Artifact + provenance ───────────────────────────────────────────────
    if artifact_id:
        try:
            art = ArtifactStore().get(artifact_id)
            artifact_record = art.model_dump(mode="json")
            if not run_id:
                run_id = str(artifact_record.get("run_id") or "") or None
            if not node_id:
                node_id = str(artifact_record.get("node_id") or "") or None
        except ArtifactNotFoundError:
            warnings.append(f"artifact_not_found:{artifact_id}")
        except Exception as exc:
            warnings.append(f"artifact_load_error:{exc}")

        try:
            pstore = ProvenanceStore()
            rec_path = pstore.base / f"{artifact_id}.json"
            if rec_path.exists():
                raw = json.loads(rec_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    provenance = raw
                    if not run_id:
                        run_id = str(raw.get("run_id") or "") or None
                    if not node_id:
                        node_id = str(raw.get("node_id") or "") or None
            lineage_tree = pstore.get_lineage(artifact_id)
        except Exception as exc:
            warnings.append(f"provenance_error:{exc}")

    # ── Run meta ────────────────────────────────────────────────────────────
    run_meta = _load_run_meta(run_id) if run_id else None
    if run_id and run_meta is None:
        warnings.append(f"run_not_found:{run_id}")

    run_block: dict[str, Any] | None = None
    if run_meta is not None:
        workers = run_meta.get("distributed_node_workers")
        if not isinstance(workers, dict):
            workers = {}
        run_block = {
            "run_id": run_meta.get("run_id") or run_id,
            "status": run_meta.get("status"),
            "graph_name": run_meta.get("graph_name"),
            "created_at": run_meta.get("created_at") or run_meta.get("started_at"),
            "distributed_node_workers": workers,
            "graph_hash": run_meta.get("graph_hash"),
        }
    elif run_id:
        run_block = {
            "run_id": run_id,
            "status": None,
            "graph_name": None,
            "created_at": None,
            "distributed_node_workers": {},
            "graph_hash": None,
        }

    # ── Graph summary ───────────────────────────────────────────────────────
    graph_block = _load_run_graph_summary(run_id, run_meta) if run_id else None
    if graph_block is None and run_meta:
        graph_block = {
            "name": run_meta.get("graph_name"),
            "schema_version": run_meta.get("schema_version"),
            "node_count": None,
            "hash": run_meta.get("graph_hash") or (provenance or {}).get("graph_hash"),
        }
    elif graph_block is not None and provenance and not graph_block.get("hash"):
        graph_block["hash"] = provenance.get("graph_hash")

    # ── Node + worker ───────────────────────────────────────────────────────
    node_type = None
    if artifact_record:
        node_type = artifact_record.get("node_type")
    if provenance and not node_type:
        node_type = provenance.get("node_type")
    if not node_id and provenance:
        node_id = provenance.get("node_id")

    worker_id = None
    workers_map = (run_block or {}).get("distributed_node_workers") or {}
    if isinstance(workers_map, dict) and node_id and node_id in workers_map:
        worker_id = workers_map.get(node_id)
    elif isinstance(workers_map, dict) and len(workers_map) == 1:
        # Single placement — useful hint even without a focused node
        worker_id = next(iter(workers_map.values()), None)

    node_block: dict[str, Any] | None = None
    if node_id or node_type or worker_id:
        node_block = {
            "id": node_id,
            "node_type": node_type,
            "worker_id": worker_id,
        }

    # ── Lineage ─────────────────────────────────────────────────────────────
    inputs = _flatten_lineage_inputs(lineage_tree)
    if not inputs and provenance and isinstance(provenance.get("input_artifact_ids"), list):
        inputs = [{"artifact_id": i, "error": None} for i in provenance["input_artifact_ids"]]

    lineage_block = {
        "inputs": inputs,
        "downstream_hint": (
            "Open Artifacts filtered by this run_id, or replay the artifact to fork a new run."
            if artifact_id
            else "Open Artifacts with run_id filter to browse outputs of this run."
        ),
        "tree": lineage_tree,
    }

    # ── Chain (visual steps) ────────────────────────────────────────────────
    chain: list[dict[str, Any]] = []
    if artifact_id:
        label = artifact_id
        if artifact_record and artifact_record.get("artifact_type"):
            label = f"{artifact_record['artifact_type']} · {artifact_id}"
        chain.append(_chain_step("artifact", label, id=artifact_id, present=artifact_record is not None))
    if node_block:
        nlabel = node_block.get("node_type") or node_block.get("id") or "node"
        chain.append(
            _chain_step(
                "node",
                str(nlabel),
                id=node_block.get("id"),
                node_type=node_block.get("node_type"),
                present=bool(node_block.get("id") or node_block.get("node_type")),
            )
        )
    if run_block:
        rlabel = run_block.get("graph_name") or run_block.get("run_id") or "run"
        chain.append(
            _chain_step(
                "run",
                str(rlabel),
                id=run_block.get("run_id"),
                status=run_block.get("status"),
                present=run_meta is not None,
            )
        )
    if graph_block:
        glabel = graph_block.get("name") or graph_block.get("hash") or "graph"
        chain.append(
            _chain_step(
                "graph",
                str(glabel),
                hash=graph_block.get("hash"),
                schema_version=graph_block.get("schema_version"),
                present=True,
            )
        )
    if worker_id:
        chain.append(_chain_step("worker", str(worker_id), id=worker_id, present=True))
    elif isinstance(workers_map, dict) and workers_map:
        # Multiple workers — summarize
        ids = sorted({str(v) for v in workers_map.values() if v})
        chain.append(
            _chain_step(
                "worker",
                ", ".join(ids[:4]) + ("…" if len(ids) > 4 else ""),
                ids=ids,
                present=True,
            )
        )

    return {
        "subject": subject,
        "run": run_block,
        "graph": graph_block,
        "node": node_block,
        "artifact": artifact_record,
        "provenance": provenance,
        "lineage": lineage_block,
        "chain": chain,
        "warnings": warnings,
    }
