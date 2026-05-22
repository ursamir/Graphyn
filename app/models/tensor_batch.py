# app/models/tensor_batch.py
"""TensorBatch — a batch of tensors for ML training/inference.

Used as the typed data contract between feature extraction, dataset assembly,
and model training nodes. Supports multimodal workflows (audio, vision, text).

V1.md §5.3 — standardized typed data contract.
"""
# NOTE: Do NOT use `from __future__ import annotations` here — it turns all
# annotations into strings (PEP 563), which breaks Pydantic v2 model_rebuild()
# when the module is loaded via importlib.

from typing import Any, Optional

import numpy as np
from pydantic import ConfigDict, Field, field_validator

from app.core.nodes.ports import PortDataType


class TensorBatch(PortDataType):
    """A batch of tensors for ML training or inference.

    Carries a primary data tensor (shape [N, ...]) alongside labels,
    split assignment, and arbitrary metadata. Suitable for any domain
    (audio features, image embeddings, text encodings, etc.).

    Fields:
        data:       float32 ndarray, shape [batch_size, *feature_dims]
        labels:     list of string class labels, length == batch_size
        split:      dataset split assignment ("train", "val", "test", or "")
        source_ids: list of source identifiers (file paths, IDs, etc.)
        metadata:   arbitrary key/value annotations
        batch_size: number of samples in the batch (derived from data.shape[0])
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: np.ndarray = Field(default=None)
    labels: list[str] = Field(default_factory=list)
    split: str = ""
    source_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def _coerce_float32(cls, v):
        """Coerce data to float32 ndarray; None → empty 1-D array."""
        if v is None:
            return np.zeros((0,), dtype=np.float32)
        return np.asarray(v, dtype=np.float32)

    @property
    def batch_size(self) -> int:
        """Number of samples in the batch."""
        return self.data.shape[0] if self.data.ndim > 0 else 0

    def model_post_init(self, __context: Any) -> None:
        """Ensure data is always a float32 array even when using default."""
        if self.data is None:
            object.__setattr__(self, "data", np.zeros((0,), dtype=np.float32))
