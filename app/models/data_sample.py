# app/models/data_sample.py
"""DataSample — domain-agnostic base type for pipeline data.

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
