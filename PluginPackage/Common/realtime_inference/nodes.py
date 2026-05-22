# PluginPackage/Common/realtime_inference/nodes.py
"""RealtimeInferenceNode — low-latency inference for TFLite, PyTorch, and ONNX models.

Migrated from app/core/nodes/ml/inference_node.py and expanded with:
  - PyTorch backend (TorchScript .pt/.pth models via torch.jit.load)
  - ONNX backend (onnxruntime.InferenceSession)
  - Auto backend detection from file extension or available frameworks
  - Wake word mode: binary threshold on top-1 probability
  - INT8 dequantization migrated from original inference_node.py

Supports three backends:
  - "tflite":  TFLite Interpreter (float32 and INT8 quantised models)
  - "pytorch": TorchScript model via torch.jit.load (falls back to torch.load)
  - "onnx":    onnxruntime.InferenceSession
  - "auto":    detected from file extension, then available framework

Labels are loaded from {model_path_dir}/labels.txt (same as original).
"""
# NOTE: No `from __future__ import annotations` — avoids Pydantic forward-ref issues.

import logging
import warnings
from pathlib import Path
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.feature_array import FeatureArray
from app.models.prediction_result import PredictionResult

log = logging.getLogger(__name__)


class RealtimeInferenceNode(Node):
    """Low-latency inference for TFLite, PyTorch, and ONNX models.

    SISO node: reads list[FeatureArray], produces list[PredictionResult].

    Loads the model and labels once in setup(). Reuses the interpreter/session
    across all process() calls for minimal latency.

    Config options:
        model_path          (str):   Required. Path to the model file.
        backend             (str):   "tflite" | "pytorch" | "onnx" | "auto". Default: "auto"
        mode                (str):   "classification" | "wake_word". Default: "classification"
        wake_word_threshold (float): Top-1 probability threshold for wake word mode. Default: 0.8
        batch_size          (int):   Batch size hint (currently informational). Default: 1
        adaptive            (bool):  Reserved — skip frames under CPU load (future). Default: False
    """

    node_type: ClassVar[str] = "realtime_inference"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="realtime_inference",
        label="Realtime Inference",
        description=(
            "Low-latency inference for TFLite, PyTorch, and ONNX models. "
            "Supports classification, wake word, streaming ASR, and adaptive frame-skipping."
        ),
        category="Inference",
        version="1.1.0",
        tags=["ml", "inference", "tflite", "pytorch", "onnx", "realtime", "streaming", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
        streaming_support=True,
        realtime_support=True,
        batch_support=True,
    )

    input_ports: ClassVar[dict] = {
        "input": InputPort(
            name="input",
            data_type=list,
            cardinality="single",
            required=True,
            description="List of FeatureArray objects.",
        )
    }

    output_ports: ClassVar[dict] = {
        "output": OutputPort(
            name="output",
            data_type=list,
            description="List of PredictionResult objects.",
        )
    }

    class Config(NodeConfig):
        model_path: str               # required — no default
        backend: str = "auto"         # "tflite" | "pytorch" | "onnx" | "auto"
        mode: str = "classification"  # "classification" | "wake_word" | "streaming_asr"
        wake_word_threshold: float = 0.8
        batch_size: int = 1
        adaptive: bool = False        # skip frames under CPU load
        adaptive_skip_ratio: float = 0.5   # fraction of frames to skip when adaptive=True
        streaming_buffer_size: int = 10    # frames to buffer before emitting in streaming_asr mode

    # ── backend detection ─────────────────────────────────────────────────────

    def _detect_backend(self) -> str:
        """Resolve the effective backend from config or file extension.

        Returns one of "tflite", "pytorch", "onnx".
        Raises ImportError if no framework is available (auto mode).
        """
        path = self.config.model_path.lower()

        if self.config.backend != "auto":
            return self.config.backend

        # Detect from file extension
        if path.endswith(".tflite"):
            return "tflite"
        if path.endswith(".pt") or path.endswith(".pth"):
            return "pytorch"
        if path.endswith(".onnx"):
            return "onnx"

        # Fallback: try each framework in order
        try:
            import tensorflow  # noqa: F401
            return "tflite"
        except ImportError:
            pass
        try:
            import torch  # noqa: F401
            return "pytorch"
        except ImportError:
            pass
        try:
            import onnxruntime  # noqa: F401
            return "onnx"
        except ImportError:
            pass

        raise ImportError(
            "RealtimeInferenceNode: no inference framework found. "
            "Install one of: tensorflow, torch, onnxruntime."
        )

    # ── setup ─────────────────────────────────────────────────────────────────

    def setup(self) -> None:
        """Load model and labels once before the first process() call."""
        self._asr_buffer: list = []   # streaming ASR frame buffer — reset on setup
        model_path = Path(self.config.model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"RealtimeInferenceNode: model not found: {model_path}"
            )

        labels_path = model_path.parent / "labels.txt"
        if not labels_path.exists():
            raise FileNotFoundError(
                f"RealtimeInferenceNode: labels.txt not found at: {labels_path}"
            )

        with open(labels_path) as f:
            self._labels = [line.strip() for line in f if line.strip()]

        self._backend = self._detect_backend()
        log.info("RealtimeInferenceNode: using backend '%s'", self._backend)

        if self._backend == "tflite":
            self._setup_tflite(model_path)
        elif self._backend == "pytorch":
            self._setup_pytorch(model_path)
        elif self._backend == "onnx":
            self._setup_onnx(model_path)
        else:
            raise ValueError(
                f"RealtimeInferenceNode: unknown backend '{self._backend}'. "
                "Must be 'tflite', 'pytorch', or 'onnx'."
            )

        log.info("RealtimeInferenceNode: loaded model from %s", model_path)
        log.info("RealtimeInferenceNode: backend=%s labels=%s", self._backend, self._labels)

    def _setup_tflite(self, model_path: Path) -> None:
        """Load TFLite interpreter and allocate tensors."""
        try:
            import tensorflow as tf
        except ImportError:
            raise ImportError(
                "RealtimeInferenceNode: TFLite backend requires TensorFlow. "
                "Install with: venv/bin/pip install tensorflow"
            )

        self._interpreter = tf.lite.Interpreter(model_path=str(model_path))
        self._interpreter.allocate_tensors()
        self._input_details = self._interpreter.get_input_details()
        self._output_details = self._interpreter.get_output_details()
        log.debug("RealtimeInferenceNode: TFLite input dtype: %s", self._input_details[0]["dtype"])

    def _setup_pytorch(self, model_path: Path) -> None:
        """Load PyTorch model — TorchScript first, fall back to state dict."""
        try:
            import torch
        except ImportError:
            raise ImportError(
                "RealtimeInferenceNode: PyTorch backend requires torch. "
                "Install with: venv/bin/pip install torch"
            )

        try:
            self._model = torch.jit.load(str(model_path), map_location="cpu")
            self._pytorch_mode = "torchscript"
        except Exception as e:
            warnings.warn(
                f"RealtimeInferenceNode: torch.jit.load failed ({e}). "
                "Falling back to torch.load (state dict). "
                "Note: state dict loading requires knowing the model architecture — "
                "the model object will be the raw state dict.",
                stacklevel=2,
            )
            self._model = torch.load(str(model_path), map_location="cpu")
            self._pytorch_mode = "state_dict"

        if self._pytorch_mode == "torchscript":
            self._model.eval()

    def _setup_onnx(self, model_path: Path) -> None:
        """Load ONNX InferenceSession."""
        try:
            import onnxruntime as ort
        except ImportError:
            raise ImportError(
                "RealtimeInferenceNode: ONNX backend requires onnxruntime. "
                "Install with: venv/bin/pip install onnxruntime"
            )

        self._session = ort.InferenceSession(str(model_path))
        self._onnx_input_name = self._session.get_inputs()[0].name

    # ── teardown ──────────────────────────────────────────────────────────────

    def teardown(self) -> None:
        """Release interpreter/model resources."""
        if hasattr(self, "_interpreter"):
            del self._interpreter
        if hasattr(self, "_model"):
            del self._model
        if hasattr(self, "_session"):
            del self._session

    # ── inference helpers ─────────────────────────────────────────────────────

    def _infer_tflite(self, inp: np.ndarray) -> list:
        """Run TFLite inference on a single [1, T, F, 1] float32 array.

        Handles INT8 quantization (input quantize, output dequantize).
        Returns list of float probabilities.
        """
        input_detail = self._input_details[0]
        output_detail = self._output_details[0]
        is_int8 = input_detail["dtype"] == np.uint8

        if is_int8:
            scale, zero_point = input_detail["quantization"]
            if scale == 0:
                scale = 1.0
            inp = np.clip(
                np.round(inp / scale + zero_point), 0, 255
            ).astype(np.uint8)

        self._interpreter.set_tensor(input_detail["index"], inp)
        self._interpreter.invoke()
        output = self._interpreter.get_tensor(output_detail["index"])

        if output_detail["dtype"] == np.uint8:
            scale, zero_point = output_detail["quantization"]
            if scale == 0:
                scale = 1.0
            output = (output.astype(np.float32) - zero_point) * scale

        return output[0].tolist()

    def _infer_pytorch(self, inp: np.ndarray) -> list:
        """Run PyTorch inference on a single [1, T, F, 1] float32 array.

        Returns list of float probabilities via softmax.
        """
        import torch

        if self._pytorch_mode == "state_dict":
            raise RuntimeError(
                "RealtimeInferenceNode: PyTorch model was loaded as a state dict "
                "(torch.jit.load failed). Cannot run inference without the model "
                "architecture. Please provide a TorchScript (.pt) model."
            )

        tensor = torch.from_numpy(inp)
        with torch.no_grad():
            logits = self._model(tensor)
            probs = torch.softmax(logits, dim=1)
        return probs[0].tolist()

    def _infer_onnx(self, inp: np.ndarray) -> list:
        """Run ONNX inference on a single [1, T, F, 1] float32 array.

        Returns list of float probabilities.
        """
        output = self._session.run(None, {self._onnx_input_name: inp})[0]
        return output[0].tolist()

    # ── process ───────────────────────────────────────────────────────────────

    def process(self, features: list) -> list:
        """Run inference on a list of FeatureArray objects.

        Modes:
            classification  — PredictionResult per input (default)
            wake_word       — binary threshold on top-1 probability
            streaming_asr   — buffer frames, emit when buffer full (CTC-style)

        Adaptive frame-skipping:
            When adaptive=True, skips every Nth frame based on adaptive_skip_ratio
            to reduce CPU load in real-time scenarios.
        """
        import time

        results = []
        frame_count = 0
        skip_interval = max(2, int(1.0 / max(0.01, 1.0 - self.config.adaptive_skip_ratio)))

        # Streaming ASR buffer (initialised in setup())
        if not hasattr(self, "_asr_buffer"):
            self._asr_buffer = []

        for f in features:
            frame_count += 1

            # Adaptive frame-skipping: skip every Nth frame under load
            if self.config.adaptive and frame_count % skip_interval == 0:
                log.debug("RealtimeInferenceNode: adaptive skip frame %d", frame_count)
                continue

            # Reshape to [1, T, F, 1]
            inp = f.data[np.newaxis, ..., np.newaxis].astype(np.float32)

            t0 = time.monotonic()
            if self._backend == "tflite":
                probs = self._infer_tflite(inp)
            elif self._backend == "pytorch":
                probs = self._infer_pytorch(inp)
            else:  # onnx
                probs = self._infer_onnx(inp)
            elapsed_ms = (time.monotonic() - t0) * 1000
            log.debug("RealtimeInferenceNode: inference %.1f ms", elapsed_ms)

            predicted_idx = int(np.argmax(probs))
            top1_prob = float(probs[predicted_idx])

            # ── streaming_asr mode ────────────────────────────────────────────
            if self.config.mode == "streaming_asr":
                self._asr_buffer.append((f, probs))
                if len(self._asr_buffer) >= self.config.streaming_buffer_size:
                    # Aggregate: mean probabilities over buffered frames
                    all_probs = np.mean([p for _, p in self._asr_buffer], axis=0)
                    best_idx = int(np.argmax(all_probs))
                    best_label = self._labels[best_idx] if best_idx < len(self._labels) else f"class_{best_idx}"
                    results.append(PredictionResult(
                        source_path=self._asr_buffer[0][0].source_path,
                        predicted_label=best_label,
                        probabilities={self._labels[i]: float(all_probs[i]) for i in range(len(self._labels))},
                        metadata={"mode": "streaming_asr", "frames_aggregated": len(self._asr_buffer)},
                    ))
                    self._asr_buffer.clear()
                continue

            # ── wake_word mode ────────────────────────────────────────────────
            if self.config.mode == "wake_word":
                if top1_prob >= self.config.wake_word_threshold:
                    predicted_label = "wake_word_detected"
                else:
                    predicted_label = "no_wake_word"
            else:
                # classification mode
                predicted_label = self._labels[predicted_idx] if predicted_idx < len(self._labels) else f"class_{predicted_idx}"

            confidence = top1_prob * 100.0
            filename = Path(f.source_path).name
            log.debug("  %s → %s (%.1f%%)", filename, predicted_label, confidence)

            results.append(PredictionResult(
                source_path=f.source_path,
                predicted_label=predicted_label,
                probabilities={
                    self._labels[i]: float(probs[i])
                    for i in range(len(self._labels))
                },
                metadata=dict(f.metadata),
            ))

        # Emit any remaining partial ASR buffer so no frames are dropped at end of stream
        if self.config.mode == "streaming_asr" and self._asr_buffer:
            all_probs = np.mean([p for _, p in self._asr_buffer], axis=0)
            best_idx = int(np.argmax(all_probs))
            best_label = self._labels[best_idx] if best_idx < len(self._labels) else f"class_{best_idx}"
            results.append(PredictionResult(
                source_path=self._asr_buffer[0][0].source_path,
                predicted_label=best_label,
                probabilities={self._labels[i]: float(all_probs[i]) for i in range(len(self._labels))},
                metadata={"mode": "streaming_asr", "frames_aggregated": len(self._asr_buffer), "partial": True},
            ))
            self._asr_buffer.clear()

        return results
