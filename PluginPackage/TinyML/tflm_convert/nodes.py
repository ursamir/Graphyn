"""TflmConvertNode — Convert→.tflite micro + CMSIS-NN metadata

Default config.stub=True writes a placeholder DeploymentArtifact.
When stub=False, converts SavedModel/Keras/.tflite via TensorFlow Lite.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import ClassVar, Any
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.deployment_artifact import DeploymentArtifact
from app.models.model_artifact import ModelArtifact
from app.models.tflite_artifact import TFLiteArtifact

log = logging.getLogger(__name__)


class TflmConvertNode(Node):
    """Convert→.tflite micro + CMSIS-NN metadata"""

    node_type: ClassVar[str] = "tflm_convert"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="tflm_convert",
        label="Tflm Convert",
        description="Convert→.tflite micro + CMSIS-NN metadata",
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
        "input": InputPort(name="input", data_type=object, required=True, description="ModelArtifact|TFLiteArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="DeploymentArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        cmsis_nn: bool = Field(default=True, title="Cmsis nn", description="Cmsis nn.")
        optimize_for: str = Field(default="cortex_m55", title="Optimize for", description="Optimize for.")
        output_path: str = Field(default="workspace/artifacts/optimized/tflite_micro", title="Output path", description="Output path.")

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, "stub", True))
        out_dir = Path(getattr(self.config, "output_path", None) or "workspace/artifacts/optimized/tflite_micro")
        out_dir.mkdir(parents=True, exist_ok=True)
        if stub:
            _out = out_dir / "stub"
            _out.mkdir(parents=True, exist_ok=True)
            return {
                "output": DeploymentArtifact(
                    package_path=str(_out),
                    target="stub",
                    metadata={"stub": True},
                )
            }
        try:
            return self._process_real(inputs, out_dir)
        except ImportError as exc:
            from app.core.plugins.wave1_runtime import install_hint

            raise ImportError(install_hint("tinyml", ["tensorflow>=2.13"])) from exc

    def _process_real(self, inputs: dict, out_dir: Path):
        import tensorflow as tf  # type: ignore

        src = inputs.get("input") or inputs.get("model")
        src_path = None
        labels: list = []
        if isinstance(src, TFLiteArtifact) or hasattr(src, "tflite_path"):
            src_path = getattr(src, "tflite_path", None)
            labels = list(getattr(src, "labels", None) or [])
        elif isinstance(src, ModelArtifact) or hasattr(src, "model_path"):
            src_path = getattr(src, "model_path", None)
            labels = list(getattr(src, "labels", None) or [])
        elif isinstance(src, str):
            src_path = src
        elif isinstance(src, dict):
            src_path = src.get("tflite_path") or src.get("model_path") or src.get("path")

        if not src_path:
            raise RuntimeError("tflm_convert: ModelArtifact/TFLiteArtifact path required when stub=False")

        src_p = Path(str(src_path))
        out_tflite = out_dir / "model_micro.tflite"
        if src_p.suffix == ".tflite" and src_p.is_file():
            shutil.copy2(src_p, out_tflite)
            blob_size = out_tflite.stat().st_size
        elif src_p.is_dir():
            converter = tf.lite.TFLiteConverter.from_saved_model(str(src_p))
            converter.optimizations = [tf.lite.Optimize.DEFAULT]
            blob = converter.convert()
            out_tflite.write_bytes(blob)
            blob_size = len(blob)
        elif src_p.suffix in {".keras", ".h5"} and src_p.is_file():
            model = tf.keras.models.load_model(str(src_p))
            converter = tf.lite.TFLiteConverter.from_keras_model(model)
            converter.optimizations = [tf.lite.Optimize.DEFAULT]
            blob = converter.convert()
            out_tflite.write_bytes(blob)
            blob_size = len(blob)
        else:
            raise RuntimeError(f"tflm_convert: unsupported source {src_p}")

        meta = {
            "backend": "tensorflow.lite",
            "stub": False,
            "cmsis_nn": bool(getattr(self.config, "cmsis_nn", True)),
            "optimize_for": str(getattr(self.config, "optimize_for", "cortex_m55")),
            "tflite_path": str(out_tflite),
            "file_size_bytes": blob_size,
            "labels": labels,
        }
        (out_dir / "tflm_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        log.info("tflm_convert wrote %s (%d bytes)", out_tflite, blob_size)
        return {
            "output": DeploymentArtifact(
                package_path=str(out_dir),
                target=str(getattr(self.config, "optimize_for", "cortex_m55")),
                metadata=meta,
            )
        }
