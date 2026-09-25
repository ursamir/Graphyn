"""TflmQuantizeNode — Int8/int16 TFLM-compatible quantize

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=True returns typed minimal outputs without heavy deps.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.dataset_artifact import DatasetArtifact
from app.models.model_artifact import ModelArtifact
from app.models.tflite_artifact import TFLiteArtifact

log = logging.getLogger(__name__)


class TflmQuantizeNode(Node):
    """Int8/int16 TFLM-compatible quantize"""

    node_type: ClassVar[str] = "tflm_quantize"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="tflm_quantize",
        label="Tflm Quantize",
        description="Int8/int16 TFLM-compatible quantize",
        category="ML",
        version="0.2.0",
        tags=["tinyml", "wave1"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="ModelArtifact"),
        "calib": InputPort(name="calib", data_type=object | None, required=False, description="DatasetArtifact optional"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="TFLiteArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        quantization: str = Field(default='int8', title="Quantization", description="Quantization.")
        full_integer: bool = Field(default=True, title="Full integer", description="Full integer.")
        representative_samples: int = Field(default=100, title="Representative samples", description="Representative samples.")
        ensure_tflm_ops: bool = Field(default=True, title="Ensure tflm ops", description="Ensure tflm ops.")
        output_path: str = Field(default='workspace/artifacts/optimized/tflm', title="Output path", description="Output path.")


    def process(self, inputs=None, **kwargs):
        """Quantize to TFLM-friendly int8/int16; stub writes placeholder .tflite."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        stub = bool(getattr(self.config, "stub", True))
        out_dir = Path(getattr(self.config, "output_path", None) or "workspace/artifacts/optimized/tflm")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "model_quantized.tflite"
        if stub:
            out_file.write_bytes(b"TFLM_STUB_INT8")
            return {
                "output": TFLiteArtifact(
                    tflite_path=str(out_file),
                    labels=[],
                    quantisation=str(getattr(self.config, "quantization", "int8")),
                    file_size_bytes=out_file.stat().st_size,
                )
            }
        try:
            import tensorflow as tf  # type: ignore
        except ImportError as exc:
            from app.core.plugins.wave1_runtime import install_hint

            raise ImportError(install_hint("tinyml", ["tensorflow>=2.13"])) from exc
        src = inputs.get("input") or inputs.get("model")
        src_path = getattr(src, "model_path", None) or (src if isinstance(src, str) else None)
        if not src_path:
            raise RuntimeError("tflm_quantize: ModelArtifact.model_path required when stub=False")
        converter = tf.lite.TFLiteConverter.from_saved_model(str(src_path))
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        if str(getattr(self.config, "quantization", "int8")) == "int8":
            converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        blob = converter.convert()
        out_file.write_bytes(blob)
        return {
            "output": TFLiteArtifact(
                tflite_path=str(out_file),
                labels=[],
                quantisation=str(getattr(self.config, "quantization", "int8")),
                file_size_bytes=out_file.stat().st_size,
            )
        }

