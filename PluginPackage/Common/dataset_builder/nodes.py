# PluginPackage/Common/dataset_builder/nodes.py
"""DatasetBuilderNode — assemble FeatureArray objects into ML-ready train/val/test datasets.

Migrated from app/core/nodes/ml/dataset_builder.py and expanded with:
  - Configurable split ratios (train/val/test)
  - Stratified splitting via sklearn
  - Shuffle before split
  - Fixed-length padding/truncation
  - Output formats: numpy, tensorflow, pytorch
  - DatasetArtifact output (typed PortDataType) instead of plain dict

Import note: sibling types.py is imported as `dataset_builder.types` because
plugin files are loaded with module name `{plugin_dir_name}.{stem}` by
AutoDiscovery (importlib.util.spec_from_file_location). Do NOT use relative
imports (`.types`) — they break under that loader.
"""
# NOTE: No `from __future__ import annotations` — avoids Pydantic forward-ref issues.

import logging
from typing import ClassVar

import importlib

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.feature_array import FeatureArray

# Import DatasetArtifact from the sibling types module.
# Plugin files are loaded with module name `{plugin_dir_name}.{stem}` by
# AutoDiscovery. The directory may be named "dataset_builder" (underscore)
# or "dataset-builder" (hyphen). We try both, then fall back to a relative import.
try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    DatasetArtifact = importlib.import_module(f"{_pkg}.types").DatasetArtifact
except (ImportError, ModuleNotFoundError):
    try:
        # Hyphen variant (installed package name)
        DatasetArtifact = importlib.import_module("dataset-builder.types").DatasetArtifact
    except (ImportError, ModuleNotFoundError):
        from .types import DatasetArtifact  # type: ignore

log = logging.getLogger(__name__)


class DatasetBuilderNode(Node):
    """Assemble FeatureArray objects into ML-ready train/val/test datasets.

    Supports two modes:
    1. **Metadata-split mode** (legacy): reads ``metadata["split"]`` key from
       each FeatureArray (set by upstream SplitNode / StratifiedSplitNode), or
       infers split from the source_path directory structure.
    2. **Auto-split mode**: when no split metadata is present, uses
       ``split_ratios`` + optional stratification to partition the data.

    Input:  list of FeatureArray objects
    Output: DatasetArtifact with X_train/val/test, y_train/val/test, labels,
            input_shape, n_classes, and optional tf/torch datasets in metadata.
    """

    node_type: ClassVar[str] = "dataset_builder"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="dataset_builder",
        label="Dataset Builder",
        description="Assemble FeatureArray objects into ML-ready train/val/test datasets with configurable splits.",
        category="ML",
        version="1.0.0",
        tags=["ml", "dataset", "training", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
        batch_support=True,
    )

    input_ports: ClassVar[dict] = {
        "input": InputPort(
            name="input",
            data_type=list,
            cardinality="single",
            required=True,
            description="List of FeatureArray objects.",
        )
    }

    output_ports: ClassVar[dict] = {
        "output": OutputPort(
            name="output",
            data_type=DatasetArtifact,
            description="ML-ready DatasetArtifact with train/val/test splits.",
        )
    }

    class Config(NodeConfig):
        split_ratios: dict = {"train": 0.7, "val": 0.15, "test": 0.15}
        shuffle: bool = True
        stratify: bool = True          # stratified split by label
        output_format: str = "numpy"   # "numpy" | "tensorflow" | "pytorch"
        fixed_length: int = 0          # 0 = no padding; N = pad/truncate to N frames
        random_seed: int = 42

    # ── helpers ──────────────────────────────────────────────────────────────

    def _pad_or_truncate(self, data: np.ndarray, length: int) -> np.ndarray:
        """Pad or truncate the time dimension (axis 0) of a 2-D array to *length* frames."""
        if data.ndim == 1:
            data = data[:, np.newaxis]  # promote 1-D to 2-D
        T, F = data.shape
        if T == length:
            return data
        if T > length:
            return data[:length, :]
        # Pad with zeros
        pad = np.zeros((length - T, F), dtype=np.float32)
        return np.concatenate([data, pad], axis=0)

    def _to_arrays(
        self,
        feature_list: list,
        label_to_idx: dict,
        fixed_length: int,
    ):
        """Stack features into [N, T, F, 1] X array and [N] y array."""
        if not feature_list:
            return (
                np.zeros((0, 1, 1, 1), dtype=np.float32),
                np.zeros((0,), dtype=np.int32),
            )
        frames = []
        for f in feature_list:
            arr = f.data  # shape [T, F] or arbitrary
            # Normalise to 2-D: flatten everything except the first axis
            if arr.ndim == 1:
                arr = arr[:, np.newaxis]
            elif arr.ndim > 2:
                arr = arr.reshape(arr.shape[0], -1)
            if fixed_length > 0:
                arr = self._pad_or_truncate(arr, fixed_length)
            frames.append(arr)
        # Guard: when fixed_length==0, all frames must have the same shape
        if fixed_length == 0:
            shapes = {arr.shape for arr in frames}
            if len(shapes) > 1:
                raise ValueError(
                    f"DatasetBuilderNode: variable-length features detected {shapes}. "
                    "Set fixed_length > 0 to enable automatic padding/truncation."
                )
        X = np.stack(frames)                    # [N, T, F]
        X = X[..., np.newaxis].astype(np.float32)  # [N, T, F, 1]
        y = np.array(
            [label_to_idx[f.label] for f in feature_list], dtype=np.int32
        )
        return X, y

    def _infer_split(self, f) -> str | None:
        """Get split from metadata, or infer from source_path directory structure."""
        valid_splits = {"train", "val", "test"}
        split = f.metadata.get("split")
        if split in valid_splits:
            return split
        # Infer from path: look for /train/, /val/, /test/ in the path
        path_lower = (f.source_path or "").replace("\\", "/").lower()
        for s in valid_splits:
            if f"/{s}/" in path_lower:
                return s
        return split  # None or invalid value

    def _auto_split(
        self,
        features: list,
        labels_arr: np.ndarray,
        label_to_idx: dict,
    ) -> dict:
        """Partition features using split_ratios with optional stratification/shuffle."""
        from sklearn.model_selection import train_test_split

        cfg = self.config
        ratios = cfg.split_ratios
        train_r = ratios.get("train", 0.7)
        val_r = ratios.get("val", 0.15)
        test_r = ratios.get("test", 0.15)

        total = train_r + val_r + test_r
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"DatasetBuilderNode: split_ratios must sum to 1.0, got {total:.4f} "
                f"(train={train_r}, val={val_r}, test={test_r})"
            )

        indices = np.arange(len(features))
        stratify_labels = labels_arr if cfg.stratify else None

        # First split: train vs (val+test)
        val_test_r = val_r + test_r
        try:
            train_idx, val_test_idx = train_test_split(
                indices,
                test_size=val_test_r,
                shuffle=cfg.shuffle,
                stratify=stratify_labels,
                random_state=cfg.random_seed,
            )
        except ValueError as exc:
            # Stratification can fail when a class has too few samples; fall back
            log.warning(
                "DatasetBuilderNode: stratified split failed (%s); falling back to non-stratified.",
                exc,
            )
            train_idx, val_test_idx = train_test_split(
                indices,
                test_size=val_test_r,
                shuffle=cfg.shuffle,
                stratify=None,
                random_state=cfg.random_seed,
            )

        # Second split: val vs test (within the val+test portion)
        val_fraction_of_remainder = val_r / val_test_r if val_test_r > 0 else 0.5
        val_test_labels = labels_arr[val_test_idx] if cfg.stratify else None
        try:
            val_idx, test_idx = train_test_split(
                val_test_idx,
                test_size=(1.0 - val_fraction_of_remainder),
                shuffle=cfg.shuffle,
                stratify=val_test_labels,
                random_state=cfg.random_seed,
            )
        except ValueError as exc:
            log.warning(
                "DatasetBuilderNode: stratified val/test split failed (%s); falling back.",
                exc,
            )
            val_idx, test_idx = train_test_split(
                val_test_idx,
                test_size=(1.0 - val_fraction_of_remainder),
                shuffle=cfg.shuffle,
                stratify=None,
                random_state=cfg.random_seed,
            )

        return {
            "train": [features[i] for i in train_idx],
            "val":   [features[i] for i in val_idx],
            "test":  [features[i] for i in test_idx],
        }

    def _build_tf_datasets(self, X_train, y_train, X_val, y_val, X_test, y_test) -> dict:
        """Build tf.data.Dataset objects (lazy — only if tensorflow is installed)."""
        try:
            import tensorflow as tf  # noqa: PLC0415
        except ImportError:
            log.warning(
                "DatasetBuilderNode: output_format='tensorflow' requested but "
                "tensorflow is not installed. Skipping tf.data.Dataset creation."
            )
            return {}
        return {
            "tf_dataset_train": tf.data.Dataset.from_tensor_slices((X_train, y_train)),
            "tf_dataset_val":   tf.data.Dataset.from_tensor_slices((X_val,   y_val)),
            "tf_dataset_test":  tf.data.Dataset.from_tensor_slices((X_test,  y_test)),
        }

    def _build_torch_datasets(self, X_train, y_train, X_val, y_val, X_test, y_test) -> dict:
        """Build torch TensorDataset objects (lazy — only if torch is installed)."""
        try:
            import torch  # noqa: PLC0415
            from torch.utils.data import TensorDataset  # noqa: PLC0415
        except ImportError:
            log.warning(
                "DatasetBuilderNode: output_format='pytorch' requested but "
                "torch is not installed. Skipping TensorDataset creation."
            )
            return {}
        return {
            "torch_dataset_train": TensorDataset(
                torch.from_numpy(X_train), torch.from_numpy(y_train)
            ),
            "torch_dataset_val": TensorDataset(
                torch.from_numpy(X_val), torch.from_numpy(y_val)
            ),
            "torch_dataset_test": TensorDataset(
                torch.from_numpy(X_test), torch.from_numpy(y_test)
            ),
        }

    # ── main process ─────────────────────────────────────────────────────────

    def process(self, inputs: dict) -> dict:
        """Assemble features into a DatasetArtifact.

        Args:
            inputs: dict with key "input" → list of FeatureArray objects

        Returns:
            dict with key "output" → DatasetArtifact

        Raises:
            ValueError: if split_ratios don't sum to 1.0, or if metadata-split
                        mode encounters an invalid split value.
        """
        features = inputs.get("input") or []
        if not features:
            return {"output": DatasetArtifact(
                X_train=np.zeros((0, 1, 1, 1), dtype=np.float32),
                y_train=np.zeros((0,), dtype=np.int32),
                X_val=np.zeros((0, 1, 1, 1), dtype=np.float32),
                y_val=np.zeros((0,), dtype=np.int32),
                X_test=np.zeros((0, 1, 1, 1), dtype=np.float32),
                y_test=np.zeros((0,), dtype=np.int32),
                labels=[],
                input_shape=(1, 1, 1),
                n_classes=0,
            )}

        cfg = self.config
        fixed_length = cfg.fixed_length

        # Build sorted label list and index mapping
        labels = sorted({f.label for f in features})
        label_to_idx = {lbl: i for i, lbl in enumerate(labels)}
        labels_arr = np.array([label_to_idx[f.label] for f in features], dtype=np.int32)

        # ── Determine split mode ──────────────────────────────────────────────
        # Use metadata-split mode only when ALL features have a valid split in
        # metadata/path. If only SOME do (mixed batch), fall back to auto-split
        # to avoid a misleading ValueError for features without split info.
        valid_splits = {"train", "val", "test"}
        has_split_metadata = all(
            self._infer_split(f) in valid_splits for f in features
        )

        if has_split_metadata:
            # Validate all split values
            for f in features:
                split = self._infer_split(f)
                if split not in valid_splits:
                    raise ValueError(
                        f"DatasetBuilderNode: invalid split value '{split}' "
                        f"for sample '{f.source_path}'. "
                        f"Expected one of {valid_splits}."
                    )
            # Group by split, sorted by source_path for determinism
            split_groups: dict = {"train": [], "val": [], "test": []}
            for f in sorted(features, key=lambda x: x.source_path or ""):
                split_groups[self._infer_split(f)].append(f)
        else:
            # Auto-split using split_ratios
            split_groups = self._auto_split(features, labels_arr, label_to_idx)

        # ── Build numpy arrays ────────────────────────────────────────────────
        X_train, y_train = self._to_arrays(split_groups["train"], label_to_idx, fixed_length)
        X_val,   y_val   = self._to_arrays(split_groups["val"],   label_to_idx, fixed_length)
        X_test,  y_test  = self._to_arrays(split_groups["test"],  label_to_idx, fixed_length)

        # Derive input_shape from first non-empty split
        if len(X_train) > 0:
            input_shape = X_train.shape[1:]   # (T, F, 1)
        elif len(X_val) > 0:
            input_shape = X_val.shape[1:]
        elif len(X_test) > 0:
            input_shape = X_test.shape[1:]
        else:
            input_shape = (1, 1, 1)

        # ── Optional framework datasets ───────────────────────────────────────
        extra_metadata: dict = {}
        if cfg.output_format == "tensorflow":
            extra_metadata.update(
                self._build_tf_datasets(X_train, y_train, X_val, y_val, X_test, y_test)
            )
        elif cfg.output_format == "pytorch":
            extra_metadata.update(
                self._build_torch_datasets(X_train, y_train, X_val, y_val, X_test, y_test)
            )

        return {"output": DatasetArtifact(
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            X_test=X_test,
            y_test=y_test,
            labels=labels,
            input_shape=input_shape,
            n_classes=len(labels),
            metadata=extra_metadata,
        )}
