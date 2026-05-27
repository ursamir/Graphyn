# app/models/feature_array.py
"""
Bounded Context:  Domain — Data Types
Responsibility:   Typed data contract for acoustic feature arrays extracted
                  from audio clips. Produced by feature_frontend node.
Owns:             FeatureArray Pydantic model — data (float32 [T,F]), label,
                  sample_rate, source_path, feature_type, metadata.
Public Surface:   FeatureArray
Must NOT:         Import from app.core.nodes.registry or app.core.orchestrator.
                  Must not contain feature extraction logic.
Dependencies:     pydantic (PortDataType base), numpy, typing.
Reason To Change: FeatureArray schema gains new fields, or feature_type
                  enum values change.

Registered in TypeCatalogue as 'app.models.feature_array.FeatureArray'
by AutoDiscovery. Migrated from examples/06_speech_commands_e2e/.
"""
# NOTE: Do NOT use `from __future__ import annotations` here — it turns all
# annotations into strings (PEP 563), which breaks Pydantic v2 model_rebuild()
# when the module is loaded via importlib.

from typing import Any, Optional

import numpy as np
from pydantic import ConfigDict, Field, field_validator

from app.core.nodes.ports import PortDataType


class FeatureArray(PortDataType):
    """Acoustic feature array for one audio clip.

    Produced by FeatureExtractorNode / FeatureFrontendNode. Carries a 2-D
    float32 numpy array (shape [T, F]) alongside the originating label,
    sample rate, source path, feature type, and metadata dict (which includes
    the 'split' key set by the upstream split node).

    Fields:
        data:         float32 ndarray, shape [T, F]
        label:        class label string (e.g. "yes")
        sample_rate:  audio sample rate in Hz (typically 16000)
        source_path:  original WAV file path
        feature_type: feature extraction type (e.g. "log_mel", "mfcc",
                      "spectrogram", "chroma", "raw")
        metadata:     dict propagated from AudioSample; includes 'split' key
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: Optional[Any] = None              # numpy.ndarray | None; coerced to float32 [T,F] by validator
    label: str = ""
    sample_rate: int = 16000
    source_path: str = ""
    feature_type: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)  # Field(default_factory=dict) prevents shared mutable default with model_construct()

    @field_validator("data", mode="before")
    @classmethod
    def _coerce_float32(cls, v: Any) -> Any:
        """Coerce data to float32 ndarray; None → empty 2-D array."""
        if v is None:
            return np.zeros((0, 0), dtype=np.float32)
        return np.asarray(v, dtype=np.float32)

    def model_post_init(self, __context: Any) -> None:
        """Safety net for model_construct() callers that bypass validators.

        _coerce_float32 (mode="before") handles None during normal __init__.
        This guard covers model_construct() which skips field validators,
        ensuring self.data is always a float32 ndarray regardless of how the
        instance was created.
        """
        if self.data is None:
            object.__setattr__(self, "data", np.zeros((0, 0), dtype=np.float32))
