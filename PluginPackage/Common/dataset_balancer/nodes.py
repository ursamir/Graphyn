"""DatasetBalancerNode — balance dataset class distributions.

Strategies:
    oversample  — duplicate minority class samples (with optional jitter)
    undersample — randomly drop majority class samples
    weighted    — compute per-class sample weights (for loss weighting)
    synthetic   — flag minority samples for augmentation
"""
from __future__ import annotations

import copy
import logging
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

log = logging.getLogger(__name__)


class DatasetBalancerNode(Node):
    """Balance dataset class distributions to prevent training bias.

    Operates on a DatasetArtifact (from dataset_builder). Balancing is applied
    to the training split only; val and test splits are left unchanged.

    Config:
        strategy (str): "oversample" | "undersample" | "weighted" | "synthetic"
        target_count (int): target samples per class; 0 = match majority class
        balance_by (str): "class" | "speaker" | "duration"
        speaker_key (str): metadata key for speaker ID (balance_by="speaker")
        jitter_std (float): Gaussian jitter std for oversample (0 = exact copy)
        random_seed (int): RNG seed for reproducibility
    """

    node_type: ClassVar[str] = "dataset_balancer"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="dataset_balancer",
        label="Dataset Balancer",
        description=(
            "Balance dataset class distributions: oversample, undersample, "
            "weighted sampling, or synthetic flagging."
        ),
        category="ML",
        version="1.0.0",
        tags=["ml", "dataset", "balancing", "oversampling", "undersampling"],
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
            description="DatasetArtifact from dataset_builder",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=object,
            description="Balanced DatasetArtifact",
        )
    }

    class Config(NodeConfig):
        strategy: str = "oversample"    # "oversample"|"undersample"|"weighted"|"synthetic"
        target_count: int = 0           # 0 = match majority class
        balance_by: str = "class"       # "class" | "speaker" | "duration"
        speaker_key: str = "speaker_id"
        jitter_std: float = 0.0         # Gaussian noise std for oversample copies
        random_seed: int = 42

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, dataset):
        rng = np.random.default_rng(self.config.random_seed)
        strategy = self.config.strategy

        # Validate balance_by — speaker and duration balancing not yet implemented
        if self.config.balance_by != "class":
            raise NotImplementedError(
                f"DatasetBalancerNode: balance_by='{self.config.balance_by}' is not yet "
                "implemented. Only balance_by='class' is currently supported."
            )

        X = dataset.X_train
        y = dataset.y_train

        if X is None or len(X) == 0:
            log.warning("DatasetBalancerNode: empty training set — returning unchanged")
            return dataset

        if strategy == "oversample":
            X_bal, y_bal = self._oversample(X, y, rng)
        elif strategy == "undersample":
            X_bal, y_bal = self._undersample(X, y, rng)
        elif strategy == "weighted":
            X_bal, y_bal, weights = self._compute_weights(X, y)
            dataset = copy.deepcopy(dataset)
            dataset.metadata["class_weights"] = weights.tolist()
            dataset.X_train = X_bal
            dataset.y_train = y_bal
            dataset.metadata["balancer"] = {
                "strategy": "weighted",
                "class_weights": weights.tolist(),
            }
            return dataset
        elif strategy == "synthetic":
            X_bal, y_bal = self._flag_synthetic(X, y, dataset)
        else:
            raise ValueError(
                f"DatasetBalancerNode: unknown strategy '{strategy}'. "
                "Choose from: oversample, undersample, weighted, synthetic"
            )

        result = copy.deepcopy(dataset)
        result.X_train = X_bal.astype(np.float32)
        result.y_train = y_bal.astype(np.int32)
        result.metadata = {**dataset.metadata, "balancer": {
            "strategy": strategy,
            "original_count": len(y),
            "balanced_count": len(y_bal),
        }}
        return result

    # ── oversample ────────────────────────────────────────────────────────────

    def _oversample(self, X: np.ndarray, y: np.ndarray, rng) -> tuple:
        classes, counts = np.unique(y, return_counts=True)
        target = self.config.target_count or int(counts.max())

        X_parts = [X]
        y_parts = [y]

        for cls, cnt in zip(classes, counts):
            deficit = target - cnt
            if deficit <= 0:
                continue
            idx = np.where(y == cls)[0]
            chosen = rng.choice(idx, size=deficit, replace=True)
            X_extra = X[chosen].copy()
            if self.config.jitter_std > 0:
                X_extra += rng.normal(0, self.config.jitter_std, X_extra.shape).astype(np.float32)
            X_parts.append(X_extra)
            y_parts.append(np.full(deficit, cls, dtype=np.int32))

        X_bal = np.concatenate(X_parts, axis=0)
        y_bal = np.concatenate(y_parts, axis=0)
        # Shuffle
        perm = rng.permutation(len(y_bal))
        return X_bal[perm], y_bal[perm]

    # ── undersample ───────────────────────────────────────────────────────────

    def _undersample(self, X: np.ndarray, y: np.ndarray, rng) -> tuple:
        classes, counts = np.unique(y, return_counts=True)
        target = self.config.target_count or int(counts.min())

        keep_idx: list[np.ndarray] = []
        for cls in classes:
            idx = np.where(y == cls)[0]
            keep = rng.choice(idx, size=min(target, len(idx)), replace=False)
            keep_idx.append(keep)

        all_idx = np.concatenate(keep_idx)
        perm = rng.permutation(len(all_idx))
        all_idx = all_idx[perm]
        return X[all_idx], y[all_idx]

    # ── weighted ──────────────────────────────────────────────────────────────

    def _compute_weights(self, X: np.ndarray, y: np.ndarray) -> tuple:
        classes, counts = np.unique(y, return_counts=True)
        total = len(y)
        n_classes = len(classes)
        # sklearn-style balanced weights: n_samples / (n_classes * count_per_class)
        weight_map = {cls: total / (n_classes * cnt) for cls, cnt in zip(classes, counts)}
        weights = np.array([weight_map[yi] for yi in y], dtype=np.float32)
        return X, y, weights

    # ── synthetic flagging ────────────────────────────────────────────────────

    def _flag_synthetic(self, X: np.ndarray, y: np.ndarray, dataset) -> tuple:
        """Flag minority samples for augmentation by setting metadata on a copy."""
        result_dataset = copy.deepcopy(dataset)
        classes, counts = np.unique(y, return_counts=True)
        target = self.config.target_count or int(counts.max())
        result_dataset.metadata.setdefault("needs_augmentation", {})
        for cls, cnt in zip(classes, counts):
            deficit = target - cnt
            if deficit > 0:
                result_dataset.metadata["needs_augmentation"][int(cls)] = int(deficit)
        return X, y
