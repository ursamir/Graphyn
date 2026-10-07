"""Object store port types (Mode B: local uri via ArtifactRef)."""
from typing import Any, List

from pydantic import Field

from app.core.nodes.ports import PortDataType
from app.models.artifact_ref import ArtifactRef


class ObjectRef(PortDataType):
    key: str = ""
    uri: str = ""
    backend: str = "local"
    size: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    refs: List[ArtifactRef] = Field(default_factory=list)


class ObjectList(PortDataType):
    keys: list = Field(default_factory=list)
    backend: str = "local"
    prefix: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
