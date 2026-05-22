# app/models/feature_array.py
"""FeatureArray — acoustic feature array for one audio clip.

Migrated from examples/06_speech_commands_e2e/plugins/data_types.py.
Registered in TypeCatalogue as 'app.models.feature_array.FeatureArray'
by AutoDiscovery.
"""
# NOTE: Do NOT use `from __future__ import annotations` here — it turns all
# annotations into strings (PEP 563), which breaks Pydantic v2 model_rebuild()
# when the module is loaded via importlib.

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

    data: np.ndarray = Field(default=None)      # float32, shape [T, F]
    label: str = ""
    sample_rate: int = 16000
    source_path: str = ""
    feature_type: str = ""
    metadata: dict = {}

    @field_validator("data", mode="before")
    @classmethod
    def _coerce_float32(cls, v):
        """Coerce data to float32 ndarray; None → empty 2-D array."""
        if v is None:
            return np.zeros((0, 0), dtype=np.float32)
        return np.asarray(v, dtype=np.float32)

    def model_post_init(self, __context):
        """Ensure data is always a float32 array even when using default."""
        if self.data is None:
            object.__setattr__(self, 'data', np.zeros((0, 0), dtype=np.float32))
