# PluginPackage/Common/edge_optimizer/nodes.py
"""EdgeOptimizerNode — optimize models for edge deployment via TFLite or ONNX quantization.

Migrated from app/core/nodes/ml/tflite_exporter.py and expanded with:
  - ONNX export backend (via tf2onnx)
  - Auto backend selection (tflite if TF available, else onnx)
  - operator_fusion config flag (TFLite default optimizations)
  - prune config flag (reserved for future use)
  - Output is DeploymentArtifact instead of TFLiteArtifact (more general)

Supports three quantization modes for TFLite:
  - "float32": no quantization (full precision)
  - "float16": float16 weight quantization
  - "int8":    full integer quantization using representative dataset

Writes model.tflite (or model.onnx) and labels.txt to output_path.
"""
# NOTE: No `from __future__ import annotations` — avoids Pydantic forward-ref issues.

import logging
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.deployment_artifact import DeploymentArtifact
from app.models.model_artifact import ModelArtifact

log = logging.getLogger(__name__)


class EdgeOptimizerNode(Node):
    """Optimize a Keras SavedModel for edge deployment via TFLite or ONNX.

    SISO node: reads ModelArtifact, produces DeploymentArtifact.

    Config options:
        backend                (str):  "tflite" | "onnx" | "auto". Default: "tflite"
        quantization           (str):  "float32" | "float16" | "int8". Default: "int8"
        output_path            (str):  Directory for output model and labels.txt.
        representative_samples (int):  Number of calibration batches for INT8. Default: 100
        prune                  (bool): Reserved for future pruning support. Default: False
        operator_fusion        (bool): Enable TFLite default optimizations. Default: True
    """

    node_type: ClassVar[str] = "edge_optimizer"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="edge_optimizer",
        label="Edge Optimizer",
        description="Optimize models for edge deployment via TFLite or ONNX quantization.",
        category="Export",
        version="1.0.0",
        tags=["ml", "edge", "tflite", "onnx", "quantization", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
        memory_requirements="medium",
        batch_support=False,
    )

    input_ports: ClassVar[dict] = {
        "input": InputPort(
            name="input",
            data_type=ModelArtifact,
            cardinality="single",
            required=True,
            description="ModelArtifact from TrainerNode or EvaluatorNode.",
        )
    }

    output_ports: ClassVar[dict] = {
        "output": OutputPort(
            name="output",
            data_type=DeploymentArtifact,
            description="DeploymentArtifact with artifact_path, model_format, quantization, labels.",
        )
    }

    class Config(NodeConfig):
        backend: str = "tflite"          # "tflite" | "onnx" | "auto"
        quantization: str = "int8"       # "float32" | "float16" | "int8"
        output_path: str = "workspace/artifacts/optimized"
        representative_samples: int = 100
        prune: bool = False              # reserved for future — not yet implemented
        operator_fusion: bool = True     # TFLite: enable default optimizations

    def __init__(self, config=None, seed: int = 0, observer=None) -> None:
        super().__init__(config=config, seed=seed, observer=observer)
        allowed_backends = {"tflite", "onnx", "auto"}
        if self.config.backend not in allowed_backends:
            raise ValueError(
                f"EdgeOptimizerNode: backend must be one of {allowed_backends}, "
                f"got '{self.config.backend}'"
            )
        allowed_quant = {"float32", "float16", "int8"}
        if self.config.quantization not in allowed_quant:
            raise ValueError(
                f"EdgeOptimizerNode: quantization must be one of {allowed_quant}, "
                f"got '{self.config.quantization}'"
            )

    # ── backend detection ─────────────────────────────────────────────────────

    def _detect_backend(self) -> str:
        """Resolve the effective backend to use.

        Returns "tflite" or "onnx". Raises ImportError if neither is available
        and backend="auto".
        """
        if self.config.backend in ("tflite", "onnx"):
            return self.config.backend
        # auto: prefer tflite if tensorflow available, else onnx
        try:
            import tensorflow  # noqa: F401
            return "tflite"
        except ImportError:
            pass
        try:
            import onnx  # noqa: F401
            return "onnx"
        except ImportError:
            pass
        raise ImportError(
            "EdgeOptimizerNode: no export framework found. "
            "Install tensorflow (venv/bin/pip install tensorflow) or "
            "onnx+tf2onnx (venv/bin/pip install onnx tf2onnx)."
        )

    # ── TFLite export ─────────────────────────────────────────────────────────

    def _export_tflite(self, artifact: ModelArtifact, out_path: Path) -> DeploymentArtifact:
        """Convert SavedModel to TFLite with the configured quantization.

        Args:
            artifact: ModelArtifact with model_path and labels.
            out_path: Directory to write model.tflite and labels.txt.

        Returns:
            DeploymentArtifact describing the exported TFLite model.
        """
        try:
            import tensorflow as tf
        except ImportError:
            raise ImportError(
                "EdgeOptimizerNode: TFLite export requires TensorFlow. "
                "Install with: venv/bin/pip install tensorflow"
            )

        quantization = self.config.quantization
        log.info("EdgeOptimizerNode: converting SavedModel to TFLite (%s)...", quantization)

        converter = tf.lite.TFLiteConverter.from_saved_model(artifact.model_path)

        if self.config.operator_fusion:
            # DEFAULT optimization enables operator fusion and constant folding
            converter.optimizations = [tf.lite.Optimize.DEFAULT]

        if quantization == "float16":
            if not self.config.operator_fusion:
                converter.optimizations = [tf.lite.Optimize.DEFAULT]
            converter.target_spec.supported_types = [tf.float16]

        elif quantization == "int8":
            if not self.config.operator_fusion:
                converter.optimizations = [tf.lite.Optimize.DEFAULT]

            # Load representative dataset from saved X_train_repr.npy
            repr_path = Path(artifact.model_path) / "X_train_repr.npy"
            if repr_path.exists():
                X_repr = np.load(str(repr_path))
            else:
                # Fallback: create dummy data using the converter's expected input shape
                log.warning("EdgeOptimizerNode: X_train_repr.npy not found, using dummy calibration data")
                try:
                    # Infer shape from the converter's input signature
                    converter_tmp = tf.lite.TFLiteConverter.from_saved_model(artifact.model_path)
                    converter_tmp.optimizations = [tf.lite.Optimize.DEFAULT]
                    # Build a minimal model to get input shape
                    import tempfile as _tf_tmp
                    _dummy_tflite = converter_tmp.convert()
                    _interp = tf.lite.Interpreter(model_content=_dummy_tflite)
                    _interp.allocate_tensors()
                    _inp_shape = _interp.get_input_details()[0]["shape"]
                    X_repr = np.zeros((100, *_inp_shape[1:]), dtype=np.float32)
                except Exception:
                    # Last resort: use a generic shape and warn
                    log.warning(
                        "EdgeOptimizerNode: could not infer input shape for INT8 calibration. "
                        "Using generic shape (100, 101, 40, 1). "
                        "Provide X_train_repr.npy for accurate calibration."
                    )
                    X_repr = np.zeros((100, 101, 40, 1), dtype=np.float32)

            n_samples = min(self.config.representative_samples, len(X_repr))
            indices = np.linspace(0, len(X_repr) - 1, n_samples, dtype=int)
            repr_data = X_repr[indices]

            def representative_dataset():
                for i in range(len(repr_data)):
                    sample = repr_data[i : i + 1].astype(np.float32)
                    yield [sample]

            converter.representative_dataset = representative_dataset
            converter.inference_input_type = tf.uint8
            converter.inference_output_type = tf.uint8

        tflite_model = converter.convert()

        tflite_path = str(out_path / "model.tflite")
        with open(tflite_path, "wb") as f:
            f.write(tflite_model)

        labels_path = out_path / "labels.txt"
        with open(labels_path, "w") as f:
            f.write("\n".join(artifact.labels))

        file_size = len(tflite_model)
        log.info("EdgeOptimizerNode: TFLite model saved to: %s (%d KB)", tflite_path, file_size // 1024)
        log.info("EdgeOptimizerNode: labels saved to: %s", labels_path)

        return DeploymentArtifact(
            artifact_path=tflite_path,
            model_format="tflite",
            target_hardware="cpu",
            quantization=quantization,
            labels=list(artifact.labels),
            file_size_bytes=file_size,
        )

    # ── ONNX export ───────────────────────────────────────────────────────────

    def _export_onnx(self, artifact: ModelArtifact, out_path: Path) -> DeploymentArtifact:
        """Convert SavedModel or PyTorch model to ONNX.

        - TF SavedModel: uses tf2onnx subprocess
        - PyTorch .pt/.pth: uses torch.onnx.export
        """
        onnx_path = str(out_path / "model.onnx")
        model_path = artifact.model_path

        # Detect PyTorch model by extension
        if model_path.lower().endswith((".pt", ".pth")):
            try:
                import torch  # type: ignore
            except ImportError:
                raise ImportError(
                    "EdgeOptimizerNode: 'torch' required to export PyTorch model to ONNX. "
                    "Install with: pip install torch>=2.0 onnx>=1.14"
                )
            log.info("EdgeOptimizerNode: exporting PyTorch model to ONNX...")
            model = torch.jit.load(model_path, map_location="cpu")
            model.eval()
            # Use a dummy input — shape inferred from model if possible
            dummy_input = torch.zeros(1, 101, 40, 1)
            torch.onnx.export(
                model,
                dummy_input,
                onnx_path,
                opset_version=17,
                input_names=["input"],
                output_names=["output"],
            )
        else:
            # TF SavedModel path via tf2onnx
            try:
                import tf2onnx  # noqa: F401
                import tensorflow as tf  # noqa: F401
            except ImportError:
                raise ImportError(
                    "EdgeOptimizerNode: ONNX export requires tf2onnx. "
                    "Install with: pip install tf2onnx onnx"
                )
            log.info("EdgeOptimizerNode: converting SavedModel to ONNX...")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tf2onnx.convert",
                    "--saved-model",
                    model_path,
                    "--output",
                    onnx_path,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"tf2onnx conversion failed:\n{result.stderr}")

        file_size = Path(onnx_path).stat().st_size

        # Save labels.txt
        labels_path = out_path / "labels.txt"
        with open(labels_path, "w") as f:
            f.write("\n".join(artifact.labels))

        log.info("EdgeOptimizerNode: ONNX model saved to: %s (%d KB)", onnx_path, file_size // 1024)
        log.info("EdgeOptimizerNode: labels saved to: %s", labels_path)

        return DeploymentArtifact(
            artifact_path=onnx_path,
            model_format="onnx",
            target_hardware="cpu",
            quantization="float32",
            labels=list(artifact.labels),
            file_size_bytes=file_size,
        )

    # ── main process ─────────────────────────────────────────────────────────

    def process(self, artifact) -> DeploymentArtifact:
        """Optimize a SavedModel for edge deployment.

        Args:
            artifact: ModelArtifact with model_path and labels.

        Returns:
            DeploymentArtifact with artifact_path, model_format, quantization,
            labels, and file_size_bytes.
        """
        if self.config.prune:
            log.warning(
                "EdgeOptimizerNode: prune=True is set but pruning is not yet "
                "implemented. Proceeding without pruning."
            )

        out_path = Path(self.config.output_path)
        out_path.mkdir(parents=True, exist_ok=True)

        backend = self._detect_backend()
        log.info("EdgeOptimizerNode: using backend: %s", backend)

        if backend == "tflite":
            return self._export_tflite(artifact, out_path)
        else:
            return self._export_onnx(artifact, out_path)
