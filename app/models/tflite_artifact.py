# app/models/tflite_artifact.py
"""TFLiteArtifact — TFLite model artifact.

Migrated from examples/06_speech_commands_e2e/plugins/data_types.py.
Registered in TypeCatalogue as 'app.models.tflite_artifact.TFLiteArtifact'
by AutoDiscovery.
"""
# NOTE: Do NOT use `from __future__ import annotations` here — it turns all
# annotations into strings (PEP 563), which breaks Pydantic v2 model_rebuild()
# when the module is loaded via importlib.

from pydantic import ConfigDict, field_validator

from app.core.nodes.ports import PortDataType


class TFLiteArtifact(PortDataType):
    """TFLite model artifact.

    Produced by TFLiteExporterNode.

    Fields:
        tflite_path:     path to the .tflite flatbuffer file
        labels:          sorted list of class label strings
        quantisation:    one of "float32", "float16", "int8"
        file_size_bytes: flatbuffer file size in bytes
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tflite_path: str = ""
    labels: list = []
    quantisation: str = "float32"
    file_size_bytes: int = 0

    @field_validator("quantisation")
    @classmethod
    def _validate_quantisation(cls, v: str) -> str:
        allowed = {"float32", "float16", "int8"}
        if v not in allowed:
            raise ValueError(
                f"quantisation must be one of {allowed}, got '{v}'"
            )
        return v
