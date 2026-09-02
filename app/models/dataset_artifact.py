# app/models/dataset_artifact.py
"""
Bounded Context:  Domain — Data Types
Responsibility:   Typed data contract for an ML-ready dataset with train/val/test
                  splits. Produced by dataset_builder; consumed by trainer,
                  model_builder, evaluator, balancer, and versioner.
Owns:             DatasetArtifact Pydantic model — split arrays, labels,
                  input_shape, n_classes, lineage fields.
Public Surface:   DatasetArtifact
Must NOT:         Import from app.core.nodes.registry or app.core.orchestrator.
                  Must not contain dataset-building logic.
Dependencies:     pydantic (PortDataType base), numpy, typing.
Reason To Change: DatasetArtifact schema gains new fields, or split/lineage
                  schema changes.

Registered in TypeCatalogue as 'app.models.dataset_artifact.DatasetArtifact'
by AutoDiscovery. Promoted from PluginPackage/Common/dataset_builder/types.py
so isolated workers can unpickle host-produced artifacts (stable module path).
"""
# NOTE: Do NOT use `from __future__ import annotations` here — it turns all
# annotations into strings (PEP 563), which breaks Pydantic v2 model_rebuild()
# when the module is loaded via importlib.

from typing import Any, Optional

import numpy as np
from pydantic import ConfigDict, Field, field_validator

from app.core.nodes.ports import PortDataType


class DatasetArtifact(PortDataType):
    """ML-ready dataset with train/val/test splits.

    Produced by DatasetBuilderNode. Carries numpy arrays for each split,
    class labels, input shape, and optional lineage/version metadata.

    Fields:
        X_train:       float32 ndarray, shape [N_train, ...]
        X_val:         float32 ndarray, shape [N_val, ...]
        X_test:        float32 ndarray, shape [N_test, ...]
        y_train:       int32 ndarray, shape [N_train]
        y_val:         int32 ndarray, shape [N_val]
        y_test:        int32 ndarray, shape [N_test]
        labels:        sorted list of class label strings
        input_shape:   tuple describing feature dimensions (e.g. (101, 40, 1))
        n_classes:     number of unique classes
        version:       optional version tag (set by dataset_versioner)
        content_hash:  optional SHA256 hash of dataset contents
        manifest_path: optional path to manifest CSV
        metadata:      arbitrary key/value annotations
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    X_train: Optional[Any] = None   # float32 ndarray
    X_val: Optional[Any] = None     # float32 ndarray
    X_test: Optional[Any] = None    # float32 ndarray
    y_train: Optional[Any] = None   # int32 ndarray
    y_val: Optional[Any] = None     # int32 ndarray
    y_test: Optional[Any] = None    # int32 ndarray
    labels: list[str] = Field(default_factory=list)
    input_shape: tuple = ()
    n_classes: int = 0
    version: str = ""
    content_hash: str = ""   # SHA256 hash of dataset contents (renamed from 'hash' to avoid shadowing built-in)
    manifest_path: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("X_train", "X_val", "X_test", mode="before")
    @classmethod
    def _coerce_float32(cls, v: Any) -> Any:
        if v is None:
            return np.zeros((0,), dtype=np.float32)
        return np.asarray(v, dtype=np.float32)

    @field_validator("y_train", "y_val", "y_test", mode="before")
    @classmethod
    def _coerce_int32(cls, v: Any) -> Any:
        if v is None:
            return np.zeros((0,), dtype=np.int32)
        return np.asarray(v, dtype=np.int32)
