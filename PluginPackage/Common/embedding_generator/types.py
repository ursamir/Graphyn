"""EmbeddingVector — semantic embedding vector for one audio clip.

Defined here (inside the plugin) so it is registered in TypeCatalogue
only when the embedding_generator plugin is installed.
"""
# NOTE: Do NOT use `from __future__ import annotations` here — breaks Pydantic v2.

from typing import Any, Optional

import numpy as np
from pydantic import ConfigDict, Field, field_validator

from app.core.nodes.ports import PortDataType


class EmbeddingVector(PortDataType):
    """Semantic embedding vector for one audio clip.

    Produced by EmbeddingGeneratorNode. Carries a 1-D float32 numpy array
    alongside the source path, label, embedding model name, and pooling strategy.

    Fields:
        embedding:       float32 ndarray, shape [D]
        source_path:     original audio file path
        label:           class label string
        embedding_model: model used to produce the embedding (e.g. "wav2vec2")
        pooling:         pooling strategy used ("mean", "cls", "last", "none")
        metadata:        dict propagated from AudioSample
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    embedding: Optional[Any] = None     # float32 ndarray, shape [D]
    source_path: str = ""
    label: str = ""
    embedding_model: str = ""
    pooling: str = "mean"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("embedding", mode="before")
    @classmethod
    def _coerce_float32(cls, v: Any) -> Any:
        if v is None:
            return np.zeros((0,), dtype=np.float32)
        return np.asarray(v, dtype=np.float32)
