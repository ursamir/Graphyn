# app/models/data_sample.py
"""
Bounded Context:  Domain — Data Types
Responsibility:   Domain-agnostic base type for pipeline data samples.
                  Subclass for new domains (TextSample, ImageSample, etc.).
Owns:             DataSample Pydantic model — id, source, metadata dict.
Public Surface:   DataSample
Must NOT:         Import from app.core.nodes.registry or app.core.orchestrator.
                  Must not contain pipeline execution logic.
Dependencies:     pydantic (PortDataType base), stdlib (typing).
Reason To Change: DataSample schema gains new fields, or the PortDataType
                  base class interface changes.

Subclass this for new domains: TextSample, ImageSample, etc.
AutoDiscovery registers every subclass in TypeCatalogue automatically.
"""
from __future__ import annotations

from typing import Any

from app.core.nodes.ports import PortDataType


class DataSample(PortDataType):
    """Domain-agnostic base type for pipeline data.

    Provides a minimal schema suitable for any domain. Subclass this to
    add domain-specific payload fields (e.g. TextSample, ImageSample).

    Fields
    ------
    id       : str — unique identifier (caller-assigned, default "")
    source   : str — origin path, URL, or identifier (default "")
    metadata : dict — arbitrary key/value annotations (default {})
    """

    id: str = ""
    source: str = ""
    metadata: dict[str, Any] = {}
