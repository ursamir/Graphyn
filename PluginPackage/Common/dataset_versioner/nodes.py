"""DatasetVersionerNode — assign a version hash to a dataset for reproducibility.

Computes a SHA256 hash of the dataset contents, writes a manifest CSV and
lineage JSON, and optionally creates an immutable snapshot copy.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

log = logging.getLogger(__name__)


class DatasetVersionerNode(Node):
    """Assign a version hash to a dataset for reproducibility and lineage tracking.

    Computes a SHA256 hash of the training data contents, writes a manifest CSV
    (id, label, split, hash) and a lineage JSON, and optionally copies the dataset
    to a versioned directory.

    Config:
        output_dir (str): directory for manifest and lineage files
        version_tag (str): explicit version tag; auto-generated from hash if empty
        include_metadata (bool): include dataset metadata in lineage JSON
        create_snapshot (bool): copy dataset arrays to versioned .npz file
    """

    node_type: ClassVar[str] = "dataset_versioner"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="dataset_versioner",
        label="Dataset Versioner",
        description=(
            "Assign a SHA256 version hash to a dataset. "
            "Writes manifest CSV and lineage JSON for reproducibility."
        ),
        category="ML",
        version="1.0.0",
        tags=["ml", "dataset", "versioning", "lineage", "governance"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object,
            cardinality="single",
            required=True,
            description="DatasetArtifact to version",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=object,
            description="DatasetArtifact with version, hash, and manifest_path set",
        )
    }

    class Config(NodeConfig):
        output_dir: str = "workspace/datasets/versioned"
        version_tag: str = ""           # auto-generated from hash if empty
        include_metadata: bool = True
        create_snapshot: bool = False   # copy arrays to versioned .npz

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, dataset):
        result = copy.deepcopy(dataset)

        # Compute hash from training data
        dataset_hash = self._compute_hash(dataset)
        version = self.config.version_tag or f"v_{dataset_hash[:12]}"

        out_dir = Path(self.config.output_dir) / version
        out_dir.mkdir(parents=True, exist_ok=True)

        # Write manifest CSV, lineage JSON, and optional snapshot.
        # Clean up the output directory on any failure to avoid partial state.
        manifest_path = out_dir / "manifest.csv"
        lineage_path = out_dir / "lineage.json"
        try:
            self._write_manifest(dataset, manifest_path, dataset_hash)
            self._write_lineage(dataset, lineage_path, version, dataset_hash)
            if self.config.create_snapshot:
                snapshot_path = out_dir / "dataset.npz"
                self._write_snapshot(dataset, snapshot_path)
        except Exception:
            shutil.rmtree(out_dir, ignore_errors=True)
            raise

        result.metadata["versioner"] = {
            "version": version,
            "content_hash": dataset_hash,
            "manifest_path": str(manifest_path),
            "lineage_path": str(lineage_path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Set version/hash/manifest_path on the result.
        # Use model_copy() for Pydantic models; fall back to direct setattr.
        versioner_fields = {
            "version": version,
            "content_hash": dataset_hash,
            "manifest_path": str(manifest_path),
        }
        for field, value in versioner_fields.items():
            try:
                object.__setattr__(result, field, value)
            except (TypeError, AttributeError):
                pass  # field not present on this DatasetArtifact variant

        log.info(
            "DatasetVersionerNode: version=%s hash=%s manifest=%s",
            version, dataset_hash[:12], manifest_path,
        )
        return result

    # ── hash ──────────────────────────────────────────────────────────────────

    def _compute_hash(self, dataset) -> str:
        """SHA256 of concatenated train/val/test arrays + labels."""
        h = hashlib.sha256()
        for arr in [dataset.X_train, dataset.X_val, dataset.X_test,
                    dataset.y_train, dataset.y_val, dataset.y_test]:
            if arr is not None and hasattr(arr, "tobytes"):
                h.update(arr.tobytes())
        for label in (dataset.labels or []):
            h.update(label.encode())
        return h.hexdigest()

    # ── manifest ──────────────────────────────────────────────────────────────

    def _write_manifest(self, dataset, path: Path, dataset_hash: str) -> None:
        labels = dataset.labels or []
        if not labels:
            log.warning(
                "DatasetVersionerNode: labels list is empty — manifest will use numeric class indices"
            )
        rows: list[dict] = []
        idx = 0

        # Try to retrieve per-sample source paths from dataset metadata
        train_paths = dataset.metadata.get("train_paths", [])
        val_paths   = dataset.metadata.get("val_paths", [])
        test_paths  = dataset.metadata.get("test_paths", [])

        for split_name, y_arr, paths_list in [
            ("train", dataset.y_train, train_paths),
            ("val",   dataset.y_val,   val_paths),
            ("test",  dataset.y_test,  test_paths),
        ]:
            if y_arr is None:
                continue
            for i, yi in enumerate(y_arr):
                label = labels[int(yi)] if int(yi) < len(labels) else str(yi)
                src_path = paths_list[i] if i < len(paths_list) else ""
                rows.append({
                    "id": idx,
                    "path": src_path,
                    "label": label,
                    "split": split_name,
                    "hash": dataset_hash[:16],
                })
                idx += 1

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "path", "label", "split", "hash"])
            writer.writeheader()
            writer.writerows(rows)

    # ── lineage ───────────────────────────────────────────────────────────────

    def _write_lineage(self, dataset, path: Path, version: str, dataset_hash: str) -> None:
        lineage: dict = {
            "version": version,
            "hash": dataset_hash,
            "n_classes": dataset.n_classes,
            "labels": dataset.labels,
            "input_shape": list(dataset.input_shape) if dataset.input_shape else [],
            "split_sizes": {
                "train": int(len(dataset.y_train)) if dataset.y_train is not None else 0,
                "val":   int(len(dataset.y_val))   if dataset.y_val   is not None else 0,
                "test":  int(len(dataset.y_test))  if dataset.y_test  is not None else 0,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if self.config.include_metadata:
            lineage["metadata"] = dataset.metadata

        class _NumpyEncoder(json.JSONEncoder):
            """Convert numpy arrays and scalars to JSON-serialisable types."""
            def default(self, obj):
                import numpy as _np
                if isinstance(obj, _np.ndarray):
                    return obj.tolist()
                if isinstance(obj, (_np.integer,)):
                    return int(obj)
                if isinstance(obj, (_np.floating,)):
                    return float(obj)
                return super().default(obj)

        with open(path, "w") as f:
            json.dump(lineage, f, indent=2, cls=_NumpyEncoder)

    # ── snapshot ──────────────────────────────────────────────────────────────

    def _write_snapshot(self, dataset, path: Path) -> None:
        arrays = {}
        for name in ["X_train", "X_val", "X_test", "y_train", "y_val", "y_test"]:
            arr = getattr(dataset, name, None)
            if arr is not None and hasattr(arr, "shape"):
                arrays[name] = arr
        if arrays:
            np.savez_compressed(str(path), **arrays)
