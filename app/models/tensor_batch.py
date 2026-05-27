# app/models/tensor_batch.py
"""
Bounded Context:  Domain — Data Types
Responsibility:   Typed data contract for batches of tensors used between
                  feature extraction, dataset assembly, and model training nodes.
                  Supports multimodal workflows (audio, vision, text).
Owns:             TensorBatch Pydantic model — data (float32 [N,...]), labels,
                  split, source_ids, metadata.
Public Surface:   TensorBatch
Must NOT:         Import from app.core.nodes.registry or app.core.orchestrator.
                  Must not contain tensor manipulation logic.
Dependencies:     pydantic (PortDataType base), stdlib (typing).
Reason To Change: TensorBatch schema gains new fields, or split enum values
                  change. V1.md §5.3.
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
        """Coerce data to float32 ndarray; None → empty 1-D array.

        Raises ValueError for a non-empty 1-D array: the contract requires
        shape [batch_size, *feature_dims], so a flat vector is ambiguous and
        almost certainly a caller error.
        """
        if v is None:
            return np.zeros((0,), dtype=np.float32)
        arr = np.asarray(v, dtype=np.float32)
        if arr.ndim == 1 and arr.shape[0] > 0:
            raise ValueError(
                "TensorBatch.data must be 2-D or higher for non-empty batches "
                f"(got shape {arr.shape}). Reshape to (N, 1) if each element "
                "is a scalar sample."
            )
        return arr

    @property
    def batch_size(self) -> int:
        """Number of samples in the batch."""
        return self.data.shape[0] if self.data.ndim > 0 else 0

    def model_post_init(self, __context: Any) -> None:
        """Safety net for model_construct() callers that bypass field_validator.

        Normal construction always passes through _coerce_float32, so this
        branch is unreachable in practice.  It exists solely to guarantee a
        valid float32 array when TensorBatch is assembled via
        ``TensorBatch.model_construct(data=None)`` (e.g. in test fixtures or
        deserialization shims that skip validation).
        """
        if self.data is None:
            object.__setattr__(self, "data", np.zeros((0,), dtype=np.float32))
