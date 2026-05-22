# app/models/deployment_artifact.py
"""DeploymentArtifact — a packaged model ready for edge/cloud deployment.

Represents the output of a deployment packaging node — a self-contained
bundle containing the model, runtime metadata, hardware target info,
and benchmark results.

V1.md §5.3 — standardized typed data contract.
V1.md §14 — Edge AI deployment targets.
Phase 6 prerequisite: supports_edge capability field maps to this type.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from app.core.nodes.ports import PortDataType


class DeploymentArtifact(PortDataType):
    """A packaged model artifact ready for deployment to a target runtime.

    Produced by deployment packaging nodes (e.g. TFLiteExporterNode,
    ONNXExporterNode, future EdgePackagerNode). Carries the model path,
    target hardware/runtime info, quantization details, and benchmark results.

    Fields:
        artifact_path:    Path to the deployment bundle (file or directory)
        model_format:     Runtime format: "tflite", "onnx", "tensorrt", "coreml", etc.
        target_hardware:  Deployment target: "cpu", "gpu", "tpu", "npu", "edge", etc.
        quantization:     Quantization scheme: "none", "int8", "float16", "dynamic", etc.
        labels:           Class label list (one per output class)
        input_shape:      Model input shape as list of ints (e.g. [1, 101, 40])
        output_shape:     Model output shape as list of ints (e.g. [1, 6])
        file_size_bytes:  Size of the deployment artifact in bytes
        benchmark:        Optional benchmark results dict (latency_ms, throughput, etc.)
        metadata:         Arbitrary key/value annotations (versions, checksums, etc.)
    """

    artifact_path: str = ""
    model_format: str = ""
    target_hardware: str = "cpu"
    quantization: str = "none"
    labels: list[str] = Field(default_factory=list)
    input_shape: list[int] = Field(default_factory=list)
    output_shape: list[int] = Field(default_factory=list)
    file_size_bytes: int = 0
    benchmark: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
