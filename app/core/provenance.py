# app/core/provenance.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Artifact lineage tracking. Records which node/run produced
                  each artifact and what inputs it consumed.
Owns:             ProvenanceRecord (immutable model), ProvenanceStore (lineage
                  storage with by_run and by_graph_hash secondary indexes).
Public Surface:   ProvenanceStore.record(), .get_lineage(), .find_by_run(),
                  .find_reproducible(); ProvenanceRecord.
Must NOT:         Import from app.domain, app.api, or any execution module.
Dependencies:     stdlib, pydantic, app.core.config (provenance_dir).
Reason To Change: Provenance schema evolves, new index strategies are added,
                  or lineage query API changes.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ProvenanceRecord data model  (req-02 §1)
# ---------------------------------------------------------------------------


class ProvenanceRecord(BaseModel):
    """Immutable provenance envelope linking an artifact to its execution context.

    All fields are JSON-serializable via ``model.model_dump(mode="json")``.

    Requirements: req-02 §1
    """

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    """The artifact produced (references ArtifactRecord.artifact_id)."""

    run_id: str
    """The run that produced the artifact."""

    node_id: str
    """The IR node ID that produced the artifact."""

    node_type: str
    """The node type string (e.g. ``"clean"``, ``"train"``)."""

    graph_hash: str
    """SHA-256 of the canonical dump_ir(graph) JSON for this run."""

    input_artifact_ids: list[str]
    """Artifact IDs consumed as inputs (may be empty for source nodes)."""

    created_at: str
    """ISO 8601 UTC timestamp."""

    schema_version: str = "1.0"
    """Schema version for forward compatibility."""


# ---------------------------------------------------------------------------
# ProvenanceStore  (req-02 §2–§6)
# ---------------------------------------------------------------------------


class ProvenanceStore:
    """Stores and queries provenance records for artifact lineage tracking.

    Directory layout::

        workspace/
        └── provenance/
            ├── {artifact_id}.json   # full ProvenanceRecord per artifact
            └── by_run/
                └── {run_id}.json    # JSON array of artifact_ids per run

    Requirements: req-02 §2, §3, §4, §5, §6
    """

    def __init__(self, base_dir: str | None = None) -> None:
        from app.core.config import provenance_dir as _provenance_dir
        if base_dir is not None:
            # base_dir is the workspace root — provenance lives under it
            self.base: Path = Path(base_dir) / "provenance"
        else:
            self.base = _provenance_dir()
        self._lock = threading.Lock()
        self._init_workspace()

    # ------------------------------------------------------------------
    # Initialization  (req-02 §2)
    # ------------------------------------------------------------------

    def _init_workspace(self) -> None:
        """Create provenance/ and provenance/by_run/ and provenance/by_graph_hash/ if they don't exist."""
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "by_run").mkdir(parents=True, exist_ok=True)
        (self.base / "by_graph_hash").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # record()  (req-02 §3)
    # ------------------------------------------------------------------

    def record(
        self,
        artifact_id: str,
        run_id: str,
        node_id: str,
        node_type: str,
        graph_hash: str,
        input_artifact_ids: list[str],
    ) -> ProvenanceRecord:
        """Record provenance for an artifact.

        Writes ``{base}/{artifact_id}.json`` and appends ``artifact_id`` to
        ``{base}/by_run/{run_id}.json`` (idempotent — no duplicates).

        Thread-safe via ``threading.Lock()``.

        Requirements: req-02 §3
        """
        created_at = datetime.now(timezone.utc).isoformat()
        prov = ProvenanceRecord(
            artifact_id=artifact_id,
            run_id=run_id,
            node_id=node_id,
            node_type=node_type,
            graph_hash=graph_hash,
            input_artifact_ids=input_artifact_ids,
            created_at=created_at,
        )

        with self._lock:
            # Write {artifact_id}.json atomically
            record_path = self.base / f"{artifact_id}.json"
            if record_path.exists():
                logger.warning(
                    "ProvenanceStore: overwriting existing provenance record for artifact %s "
                    "(run_id=%s, node_id=%s)",
                    artifact_id, run_id, node_id,
                )
            tmp_record = record_path.with_suffix(".json.tmp")
            tmp_record.write_text(
                json.dumps(prov.model_dump(mode="json"), indent=2), encoding="utf-8"
            )
            tmp_record.replace(record_path)

            # Append artifact_id to by_run/{run_id}.json atomically (no duplicates)
            by_run_path = self.base / "by_run" / f"{run_id}.json"
            if by_run_path.exists():
                try:
                    existing: list[str] = json.loads(by_run_path.read_text(encoding="utf-8"))
                    if not isinstance(existing, list):
                        existing = []
                except Exception:
                    existing = []
            else:
                existing = []

            if artifact_id not in existing:
                existing.append(artifact_id)

            tmp_by_run = by_run_path.with_suffix(".json.tmp")
            tmp_by_run.write_text(json.dumps(existing, indent=2), encoding="utf-8")
            tmp_by_run.replace(by_run_path)

            # NEW-11 fix: use the full graph_hash as the index filename instead
            # of truncating to 16 chars. Truncation caused two graphs sharing
            # the same 16-char prefix to collide into the same index file.
            if graph_hash:
                (self.base / "by_graph_hash").mkdir(exist_ok=True)
                by_hash_path = self.base / "by_graph_hash" / f"{graph_hash}.json"
                if by_hash_path.exists():
                    try:
                        hash_ids: list[str] = json.loads(by_hash_path.read_text(encoding="utf-8"))
                        if not isinstance(hash_ids, list):
                            hash_ids = []
                    except Exception:
                        hash_ids = []
                else:
                    hash_ids = []
                if artifact_id not in hash_ids:
                    hash_ids.append(artifact_id)
                tmp_by_hash = by_hash_path.with_suffix(".json.tmp")
                tmp_by_hash.write_text(json.dumps(hash_ids, indent=2), encoding="utf-8")
                tmp_by_hash.replace(by_hash_path)

        return prov

    # ------------------------------------------------------------------
    # get_lineage()  (req-02 §4)
    # ------------------------------------------------------------------

    def get_lineage(
        self, artifact_id: str, max_depth: int = 100
    ) -> dict:
        """Return the full upstream lineage tree rooted at ``artifact_id``.

        Uses path-aware recursion to correctly detect cycles (B-17 fix).
        Each call tracks its own ``ancestors`` set (the path from root to
        current node), so sibling branches don't share ancestor state.

        Args:
            artifact_id: Root artifact to build lineage for.
            max_depth: Maximum recursion depth. Nodes beyond this depth are
                       returned with ``error: "max_depth_exceeded"`` rather
                       than being traversed. Default: 100.

        Never raises — returns error nodes for missing records, cycles, or
        depth limit exceeded.

        Requirements: req-02 §4
        """
        return self._build_lineage_node(artifact_id, frozenset(), max_depth=max_depth, depth=0)

    def _build_lineage_node(
        self, artifact_id: str, ancestors: frozenset, max_depth: int, depth: int
    ) -> dict:
        """Build one lineage node, recursing into inputs.

        ``ancestors`` is the set of artifact IDs on the current path from the
        root to this node. Using a frozenset (immutable) means each recursive
        call gets its own copy — siblings don't share ancestor state, so a
        node that appears in two branches is not falsely flagged as a cycle.
        """
        # Depth limit: prevent unbounded recursion on very deep lineage trees
        if depth >= max_depth:
            logger.warning(
                "ProvenanceStore.get_lineage: max_depth=%d reached at artifact %s — truncating",
                max_depth, artifact_id,
            )
            return {"artifact_id": artifact_id, "inputs": [], "error": "max_depth_exceeded"}

        # Cycle detection: this artifact is its own ancestor
        if artifact_id in ancestors:
            return {"artifact_id": artifact_id, "inputs": [], "error": "cycle_detected"}

        record_path = self.base / f"{artifact_id}.json"
        if not record_path.exists():
            return {"artifact_id": artifact_id, "inputs": [], "error": "no_provenance_record"}

        try:
            data = json.loads(record_path.read_text(encoding="utf-8"))
            prov = ProvenanceRecord.model_validate(data)
        except Exception as exc:
            logger.warning(
                "ProvenanceStore: failed to load record for %s (%s) — returning error node",
                artifact_id, exc,
            )
            return {"artifact_id": artifact_id, "inputs": [], "error": "no_provenance_record"}

        # Add this artifact to the current path before recursing into inputs
        new_ancestors = ancestors | {artifact_id}

        inputs = [
            self._build_lineage_node(input_id, new_ancestors, max_depth=max_depth, depth=depth + 1)
            for input_id in prov.input_artifact_ids
        ]

        return {
            "artifact_id": prov.artifact_id,
            "run_id": prov.run_id,
            "node_id": prov.node_id,
            "node_type": prov.node_type,
            "graph_hash": prov.graph_hash,
            "created_at": prov.created_at,
            "inputs": inputs,
        }

    # ------------------------------------------------------------------
    # find_by_run()  (req-02 §5)
    # ------------------------------------------------------------------

    def find_by_run(self, run_id: str) -> list[ProvenanceRecord]:
        """Return all ProvenanceRecords for the given run.

        Returns ``[]`` if the run has no provenance records or is unknown.

        Requirements: req-02 §5
        """
        by_run_path = self.base / "by_run" / f"{run_id}.json"
        if not by_run_path.exists():
            return []

        try:
            artifact_ids: list[str] = json.loads(by_run_path.read_text(encoding="utf-8"))
            if not isinstance(artifact_ids, list):
                return []
        except Exception as exc:
            logger.warning(
                "ProvenanceStore: failed to read by_run/%s.json (%s) — returning []",
                run_id,
                exc,
            )
            return []

        records: list[ProvenanceRecord] = []
        for aid in artifact_ids:
            record_path = self.base / f"{aid}.json"
            if not record_path.exists():
                logger.warning(
                    "ProvenanceStore: artifact %s listed in by_run/%s.json but record missing — skipping",
                    aid,
                    run_id,
                )
                continue
            try:
                data = json.loads(record_path.read_text(encoding="utf-8"))
                records.append(ProvenanceRecord.model_validate(data))
            except Exception as exc:
                logger.warning(
                    "ProvenanceStore: failed to load record for %s (%s) — skipping",
                    aid,
                    exc,
                )

        return records

    # ------------------------------------------------------------------
    # find_reproducible()  (req-02 §6)
    # ------------------------------------------------------------------

    def find_reproducible(self, graph_hash: str) -> list[ProvenanceRecord]:
        """Return all ProvenanceRecords whose ``graph_hash`` matches.

        Uses the ``by_graph_hash/`` secondary index when available (O(k) where
        k = artifacts for that graph hash), falling back to a full scan only
        when the index file is missing (e.g. for records written before the
        index was introduced).

        Args:
            graph_hash: The graph hash to search for. An empty string is not
                        a supported query — returns [] immediately.

        Requirements: req-02 §6
        """
        if not graph_hash:
            # Empty graph_hash is not a meaningful query — runs that failed
            # before save_graph_ir() was called all share graph_hash="" and
            # a full scan would return all of them.
            return []

        if not self.base.is_dir():
            return []

        # Fast path: use the by_graph_hash index
        # NEW-11 fix: use the full graph_hash as the filename (no truncation).
        by_hash_path = self.base / "by_graph_hash" / f"{graph_hash}.json"
        if by_hash_path.exists():
            try:
                artifact_ids: list[str] = json.loads(by_hash_path.read_text(encoding="utf-8"))
                if not isinstance(artifact_ids, list):
                    artifact_ids = []
            except Exception as exc:
                logger.warning(
                    "ProvenanceStore: failed to read by_graph_hash index (%s) — falling back to full scan",
                    exc,
                )
                # Fall through to slow path below
            else:
                records: list[ProvenanceRecord] = []
                for aid in artifact_ids:
                    record_path = self.base / f"{aid}.json"
                    if not record_path.exists():
                        continue
                    try:
                        data = json.loads(record_path.read_text(encoding="utf-8"))
                        rec = ProvenanceRecord.model_validate(data)
                        # Full hash comparison — no truncation so no false positives.
                        if rec.graph_hash == graph_hash:
                            records.append(rec)
                    except Exception as exc:
                        logger.warning(
                            "ProvenanceStore: failed to load record %s (%s) — skipping", aid, exc
                        )
                return records

        # Slow path: full directory scan (for records written before the index existed)
        records = []
        for entry in self.base.iterdir():
            if not entry.is_file() or entry.suffix != ".json":
                continue
            try:
                data = json.loads(entry.read_text(encoding="utf-8"))
                record = ProvenanceRecord.model_validate(data)
                if record.graph_hash == graph_hash:
                    records.append(record)
            except Exception as exc:
                logger.warning(
                    "ProvenanceStore: failed to load record at %s (%s) — skipping",
                    entry,
                    exc,
                )

        return records
