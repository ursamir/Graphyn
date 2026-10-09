"""Port types for video_embed (Video pack). No `from __future__ import annotations`."""
from typing import Any, Optional

import numpy as np
from pydantic import ConfigDict, Field, field_validator

from app.core.nodes.ports import PortDataType


class EmbeddingVector(PortDataType):
    """CLIP embedding of a video (pooled over frames) or of one frame."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    embedding: Optional[Any] = None
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
