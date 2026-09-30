"""DatasetVersionerNode — assign a version hash to a dataset for reproducibility.

Computes a SHA256 hash of the dataset contents, writes a manifest CSV and
lineage JSON, and optionally creates an immutable snapshot copy.
"""
from __future__ import annotations

import copy
import csv
import re
import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar
from pydantic import Field

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.dataset_artifact import DatasetArtifact

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
            data_type=DatasetArtifact,
            cardinality="single",
            required=True,
            description="DatasetArtifact to version",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=DatasetArtifact,
            description="DatasetArtifact with version, hash, and manifest_path set",
        )
    }

    class Config(NodeConfig):
        output_dir: str = Field(default='workspace/datasets/output/versioned', title="Output dir", description="Project root under workspace/datasets/output/{project}; version_tag is appended.")
        project: str = Field(default='', title="Project", description="Optional project name; when set, output_dir becomes workspace/datasets/output/{project}.")
        version_tag: str = Field(default='v1', title="Version tag", description="Canonical version tag matching vN / vN.N.N (e.g. v1, v1.0.0). Empty defaults to v1 — hash-style tags are rejected.")
        include_metadata: bool = Field(default=True, title="Include metadata", description="Bundle model metadata / labels JSON with the package (On/Off).")
        create_snapshot: bool = Field(default=False, title="Create Snapshot", description="Enable create snapshot.")
        overwrite: bool = Field(default=False, title="Overwrite", description="Allow replacing an existing version directory whose content hash differs. Re-running identical data is always allowed.")

    # ── SISO process ──────────────────────────────────────────────────────────

    _VERSION_RE: ClassVar[re.Pattern[str]] = re.compile(r"^v\d+(\.\d+)*$")

    def process(self, dataset):
        if isinstance(dataset, dict):
            dataset = (
                dataset.get("dataset")
                or dataset.get("input")
                or dataset.get("output")
            )
        if dataset is None or isinstance(dataset, dict):
            raise ValueError("DatasetVersionerNode: expected a DatasetArtifact input")
        if getattr(dataset, "metadata", None) is None:
            try:
                object.__setattr__(dataset, "metadata", {})
            except Exception:
                pass
        result = copy.deepcopy(dataset)

        # Compute hash from training data
        dataset_hash = self._compute_hash(dataset)
        version = str(self.config.version_tag or "v1").strip() or "v1"
        if not self._VERSION_RE.match(version):
            raise ValueError(
                f"DatasetVersionerNode: version_tag {version!r} must match "
                "vN / vN.N.N (e.g. v1, v1.0.0) — hash-style tags like "
                f"v_{{hash}} are not allowed."
            )
        output_dir = str(self.config.output_dir or "").strip()
        project = str(getattr(self.config, "project", "") or "").strip()
        if project:
            output_dir = f"workspace/datasets/output/{project}"
        out_dir = Path(output_dir) / version
        pre_existed = out_dir.exists()
        if pre_existed:
            if not out_dir.is_dir():
                raise FileExistsError(f"DatasetVersionerNode: {out_dir} exists and is not a directory")
            prev_hash = self._existing_hash(out_dir / "lineage.json")
            overwrite = bool(getattr(self.config, "overwrite", False))
            if prev_hash != dataset_hash and not overwrite:
                raise FileExistsError(
                    f"DatasetVersionerNode: version {version!r} already exists at {out_dir} "
                    f"with different content (hash {str(prev_hash)[:12] or 'unknown'} != {dataset_hash[:12]}). "
                    "Bump version_tag or set overwrite=True."
                )
        # Never swallow: a failed mkdir must fail the node, not surface later as a write error.
        out_dir.mkdir(parents=True, exist_ok=True)

        # Write manifest CSV, lineage JSON, and optional snapshot.
        # Only a directory this run created is removed on failure — never a pre-existing version.
        manifest_path = out_dir / "manifest.csv"
        lineage_path = out_dir / "lineage.json"
        try:
            self._write_manifest(dataset, manifest_path, dataset_hash)
            self._write_lineage(dataset, lineage_path, version, dataset_hash)
            snapshot_path = out_dir / "dataset.npz"
            if self.config.create_snapshot:
                self._write_snapshot(dataset, snapshot_path)
            elif pre_existed and snapshot_path.exists():
                snapshot_path.unlink()  # stale snapshot from the overwritten version
        except Exception:
            if not pre_existed:
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

    @staticmethod
    def _existing_hash(lineage_path: Path) -> str:
        try:
            return str(json.loads(lineage_path.read_text(encoding="utf-8")).get("hash") or "")
        except (OSError, ValueError, AttributeError):
            return ""

    def _compute_hash(self, dataset) -> str:
        """SHA256 over a length-prefixed, self-describing encoding of every split.

        Each array contributes its field name, dtype, shape and bytes (all length-
        prefixed), and each label is length-prefixed, so different datasets cannot
        collide by shifting bytes between splits/labels.
        """
        h = hashlib.sha256()

        def put(tag: bytes, payload: bytes) -> None:
            h.update(tag)
            h.update(len(payload).to_bytes(8, "big"))
            h.update(payload)

        put(b"format", b"dataset_versioner/v2")
        for name in ("X_train", "X_val", "X_test", "y_train", "y_val", "y_test"):
            arr = getattr(dataset, name, None)
            put(b"field", name.encode())
            if arr is None:
                put(b"none", b"")
                continue
            a = np.ascontiguousarray(np.asarray(arr))
            put(b"dtype", a.dtype.str.encode())
            put(b"shape", ",".join(str(d) for d in a.shape).encode())
            put(b"data", a.tobytes())
        labels = list(getattr(dataset, "labels", None) or [])
        put(b"labels", str(len(labels)).encode())
        for label in labels:
            put(b"label", str(label).encode("utf-8"))
        return h.hexdigest()

    # ── manifest ──────────────────────────────────────────────────────────────

    def _write_manifest(self, dataset, path: Path, dataset_hash: str) -> None:
        labels = list(getattr(dataset, "labels", None) or [])
        meta = getattr(dataset, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        if not labels:
            log.warning(
                "DatasetVersionerNode: labels list is empty — manifest will use numeric class indices"
            )
        rows: list[dict] = []
        idx = 0

        # Try to retrieve per-sample source paths from dataset metadata
        train_paths = meta.get("train_paths", [])
        val_paths   = meta.get("val_paths", [])
        test_paths  = meta.get("test_paths", [])

        for split_name, y_arr, paths_list in [
            ("train", getattr(dataset, "y_train", None), train_paths),
            ("val",   getattr(dataset, "y_val", None),   val_paths),
            ("test",  getattr(dataset, "y_test", None),  test_paths),
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
            "node_type": self.node_type,
        }
        run_id = str(getattr(self, "_run_id", "") or "").strip()
        if run_id:
            lineage["run_id"] = run_id
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
