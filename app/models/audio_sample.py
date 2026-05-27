# app/models/audio_sample.py
"""
Bounded Context:  Domain — Audio Data Types
Responsibility:   Domain data type for a single audio clip. Participates in
                  the TypeCatalogue and port-type compatibility checks.
Owns:             AudioSample Pydantic model — waveform array, sample rate,
                  label, path, metadata dict.
Public Surface:   AudioSample
Must NOT:         Import from app.core.nodes.registry or app.core.orchestrator.
                  Must not contain pipeline execution logic.
Dependencies:     pydantic (PortDataType base), stdlib (typing).
Reason To Change: AudioSample schema gains new fields, or the PortDataType
                  base class interface changes.

Migrated from @dataclass to Pydantic PortDataType so that it participates
in the Enhanced Node System's TypeCatalogue and port-type compatibility checks.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
from pydantic import ConfigDict, Field, field_validator

from app.core.nodes.ports import PortDataType


class AudioSample(PortDataType):
    """A single audio clip with its waveform, sample rate, label, and metadata.

    Replaces the old @dataclass. Registered in TypeCatalogue as
    'app.models.audio_sample.AudioSample' by AutoDiscovery.

    Fields
    ------
    path        : str — source file path (may be empty for generated samples)
    sample_rate : int — samples per second
    data        : numpy.ndarray — float32 waveform; coerced from None to empty array
    label       : str — class label (default "")
    metadata    : dict — arbitrary key/value annotations
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: str
    sample_rate: int
    data: Optional[Any] = None   # numpy.ndarray | None
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def _coerce_data(cls, v: Any) -> Any:
        """Coerce None → empty float32 array before Pydantic stores the value."""
        if v is None:
            return np.array([], dtype=np.float32)
        return v

    def model_post_init(self, __context: Any) -> None:
        """Ensure data is always a float32 ndarray after construction."""
        if not isinstance(self.data, np.ndarray):
            object.__setattr__(
                self, "data", np.asarray(self.data, dtype=np.float32)
            )
