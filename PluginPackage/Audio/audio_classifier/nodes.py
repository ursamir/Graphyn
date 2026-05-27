"""AudioClassifierNode — general-purpose audio classification.

Backends:
    yamnet   — YAMNet 521-class scene classification (tensorflow_hub)
    tflite   — custom TFLite model
    pytorch  — custom PyTorch/ONNX model
    auto     — yamnet if no model_path, else detect from extension

Accepts list[AudioSample] or list[FeatureArray] as input.
Produces list[PredictionResult].
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample
from app.models.feature_array import FeatureArray
from app.models.prediction_result import PredictionResult

log = logging.getLogger(__name__)


class AudioClassifierNode(Node):
    """General-purpose audio classification.

    Accepts AudioSample or FeatureArray inputs. When given AudioSamples,
    extracts a log-mel spectrogram internally before inference.

    Config:
        model_path (str): path to TFLite or PyTorch model; empty = built-in YAMNet
        backend (str): "yamnet" | "tflite" | "pytorch" | "auto"
        top_k (int): number of top predictions to return (default 1)
        sample_rate (int): expected sample rate for AudioSample inputs (default 16000)
    """

    node_type: ClassVar[str] = "audio_classifier"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="audio_classifier",
        label="Audio Classifier",
        description=(
            "General-purpose audio classification. "
            "Built-in YAMNet (521 classes) or custom TFLite/PyTorch model. "
            "Accepts AudioSample or FeatureArray inputs."
        ),
        category="Inference",
        version="1.0.0",
        tags=["audio", "classification", "yamnet", "tflite", "pytorch", "inference"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
        streaming_support=False,
        realtime_support=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list,
            cardinality="single",
            required=True,
            description="list[AudioSample] or list[FeatureArray]",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[PredictionResult],
            description="Classification results",
        )
    }

    class Config(NodeConfig):
        model_path: str = ""            # empty = built-in YAMNet
        backend: str = "auto"           # "yamnet" | "tflite" | "pytorch" | "auto"
        top_k: int = 1
        sample_rate: int = 16000

        from pydantic import field_validator

        @field_validator("top_k")
        @classmethod
        def _top_k_positive(cls, v: int) -> int:
            if v < 1:
                raise ValueError("top_k must be >= 1")
            return v

        @field_validator("sample_rate")
        @classmethod
        def _sample_rate_positive(cls, v: int) -> int:
            if v <= 0:
                raise ValueError("sample_rate must be > 0")
            return v

        @field_validator("backend")
        @classmethod
        def _backend_valid(cls, v: str) -> str:
            allowed = {"yamnet", "tflite", "pytorch", "auto"}
            if v not in allowed:
                raise ValueError(f"backend must be one of {sorted(allowed)}, got {v!r}")
            return v

    # ── setup ─────────────────────────────────────────────────────────────────

    def setup(self) -> None:
        self._resolved_backend = self._resolve_backend()
        self._labels: list[str] = []
        self._model_obj = None
        # Serialise TFLite set_tensor/invoke/get_tensor — Interpreter is not thread-safe.
        self._tflite_lock = threading.Lock()
        log.debug("AudioClassifierNode: backend='%s'", self._resolved_backend)

    def teardown(self) -> None:
        """Release model resources held on this instance."""
        if self._resolved_backend == "yamnet" and self._model_obj is not None:
            try:
                import tensorflow as tf  # type: ignore
                tf.keras.backend.clear_session()
            except Exception:
                pass
        self._model_obj = None
        self._labels = []

    def _resolve_backend(self) -> str:
        if self.config.backend != "auto":
            return self.config.backend
        if not self.config.model_path:
            return "yamnet"
        ext = self.config.model_path.lower()
        if ext.endswith(".tflite"):
            return "tflite"
        if ext.endswith((".pt", ".pth", ".onnx")):
            return "pytorch"
        return "yamnet"

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, inputs: list) -> list[PredictionResult]:
        if not hasattr(self, "_resolved_backend"):
            raise RuntimeError(
                "AudioClassifierNode.setup() must be called before process(). "
                "The NodeExecutor calls setup() automatically — do not call process() directly."
            )
        # Finding 1: guard None / empty input
        if not inputs:
            return []

        backend = self._resolved_backend
        results: list[PredictionResult] = []

        for item in inputs:
            if isinstance(item, AudioSample):
                probs, labels = self._classify_audio(item, backend)
                source_path = str(item.path)
                meta = dict(item.metadata)
            elif isinstance(item, FeatureArray):
                probs, labels = self._classify_feature(item, backend)
                source_path = str(item.source_path)
                meta = dict(item.metadata)
            else:
                # Finding 2: raise instead of silently skipping so callers detect type mismatches
                raise TypeError(
                    f"AudioClassifierNode: expected AudioSample or FeatureArray, "
                    f"got {type(item).__name__!r}"
                )

            top_k = min(self.config.top_k, len(probs))
            top_indices = np.argsort(probs)[::-1][:top_k]
            # Finding 7: bounds-check label index against actual label list length
            if labels and top_indices[0] < len(labels):
                predicted_label = labels[top_indices[0]]
            else:
                predicted_label = f"class_{top_indices[0]}"
            # Only include top-k entries in probabilities dict to avoid 521-entry dicts
            probabilities = {labels[i]: float(probs[i]) for i in top_indices if i < len(labels)} if labels else {}

            results.append(PredictionResult(
                source_path=source_path,
                predicted_label=predicted_label,
                probabilities=probabilities,
                metadata={**meta, "top_k": top_k, "backend": backend},
            ))

        return results

    # ── AudioSample → classify ────────────────────────────────────────────────

    def _classify_audio(self, sample: AudioSample, backend: str) -> tuple[np.ndarray, list[str]]:
        y = sample.data.astype(np.float32)
        sr = sample.sample_rate

        if backend == "yamnet":
            return self._yamnet_classify(y, sr)

        # For tflite/pytorch: extract log-mel features first
        import librosa  # type: ignore
        if sr != self.config.sample_rate:
            y = librosa.resample(y=y, orig_sr=sr, target_sr=self.config.sample_rate)
            sr = self.config.sample_rate

        mel = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=512, hop_length=160, n_mels=40)
        # Finding 3: guard against all-zeros mel (silent audio) which makes np.max(mel)=0
        # and causes power_to_db to produce -inf/nan values fed to the model.
        ref_val = max(float(np.max(mel)), 1e-10)
        features = librosa.power_to_db(mel, ref=ref_val).astype(np.float32)

        if backend == "tflite":
            return self._tflite_classify(features)
        return self._pytorch_classify(features)

    # ── FeatureArray → classify ───────────────────────────────────────────────

    def _classify_feature(self, feat: FeatureArray, backend: str) -> tuple[np.ndarray, list[str]]:
        if backend == "yamnet":
            # YAMNet requires a raw 16kHz waveform — FeatureArray data is not a waveform.
            # Passing feature data to YAMNet produces meaningless results.
            raise ValueError(
                "AudioClassifierNode: backend='yamnet' requires AudioSample input "
                "(raw waveform). FeatureArray input is not supported with YAMNet. "
                "Use backend='tflite' or backend='pytorch' with a FeatureArray, "
                "or pass AudioSample objects instead."
            )
        if backend == "tflite":
            return self._tflite_classify(feat.data)
        return self._pytorch_classify(feat.data)

    # ── YAMNet backend ────────────────────────────────────────────────────────

    def _yamnet_classify(self, y: np.ndarray, sr: int) -> tuple[np.ndarray, list[str]]:
        try:
            import tensorflow_hub as hub  # type: ignore
            import tensorflow as tf  # type: ignore
        except ImportError:
            raise ImportError(
                "AudioClassifierNode: 'tensorflow' and 'tensorflow_hub' required for backend='yamnet'. "
                "Install with: pip install tensorflow>=2.12 tensorflow-hub>=0.14"
            )

        if self._model_obj is None:
            self._model_obj = hub.load("https://tfhub.dev/google/yamnet/1")
            self._labels = self._load_yamnet_labels()

        if sr != 16000:
            import librosa  # type: ignore
            y = librosa.resample(y=y, orig_sr=sr, target_sr=16000)

        waveform = tf.constant(y, dtype=tf.float32)
        scores, _, _ = self._model_obj(waveform)
        # Mean over frames → single prediction
        mean_scores = scores.numpy().mean(axis=0)
        return mean_scores, self._labels

    def _load_yamnet_labels(self) -> list[str]:
        """Load YAMNet class names. Tries disk cache first, then network, then fallback."""
        import csv
        import io
        from pathlib import Path

        # Check for a bundled class map next to this file
        bundled = Path(__file__).parent / "yamnet_class_map.csv"
        if bundled.exists():
            with open(bundled, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                return [row["display_name"] for row in reader]

        # Check disk cache
        import tempfile
        cache_path = Path(tempfile.gettempdir()) / "yamnet_class_map.csv"
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    classes = [row["display_name"] for row in reader]
                if len(classes) == 521:
                    return classes
            except Exception:
                pass

        # Fetch from network and cache to disk
        try:
            import urllib.request
            url = "https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv"
            with urllib.request.urlopen(url, timeout=10) as r:
                content = r.read().decode("utf-8")
            try:
                cache_path.write_text(content, encoding="utf-8")
            except OSError:
                pass
            reader = csv.DictReader(io.StringIO(content))
            return [row["display_name"] for row in reader]
        except Exception:
            log.warning(
                "AudioClassifierNode: could not load YAMNet class map "
                "(network unavailable). Using generic class names."
            )
            return [f"class_{i}" for i in range(521)]

    # ── TFLite backend ────────────────────────────────────────────────────────

    def _tflite_classify(self, features: np.ndarray) -> tuple[np.ndarray, list[str]]:
        try:
            import tflite_runtime.interpreter as tflite  # type: ignore
        except ImportError:
            try:
                import tensorflow.lite as tflite  # type: ignore
            except ImportError:
                raise ImportError(
                    "AudioClassifierNode: TFLite runtime required for backend='tflite'. "
                    "Install with: pip install tflite-runtime>=2.14"
                )

        if self._model_obj is None:
            self._model_obj = tflite.Interpreter(model_path=self.config.model_path)
            self._model_obj.allocate_tensors()
            labels_path = Path(self.config.model_path).parent / "labels.txt"
            self._labels = labels_path.read_text().strip().splitlines() if labels_path.exists() else []

        # Finding 4: TFLite Interpreter is not thread-safe — serialise all tensor ops.
        with self._tflite_lock:
            inp_detail = self._model_obj.get_input_details()[0]
            out_detail = self._model_obj.get_output_details()[0]

            # Finding 5: validate and reshape features to match the model's expected input shape.
            expected_shape = tuple(inp_detail["shape"])  # e.g. (1, 40, T, 1) or (1, 40*T)
            # Build candidate: add batch + channel dims (common 4-D case)
            inp_4d = features[np.newaxis, ..., np.newaxis].astype(inp_detail["dtype"])
            if inp_4d.shape == expected_shape:
                inp = inp_4d
            else:
                # Try flat reshape (e.g. model expects [1, N])
                flat = features.flatten()
                inp_flat = flat[np.newaxis, :].astype(inp_detail["dtype"])
                if inp_flat.shape == expected_shape:
                    inp = inp_flat
                else:
                    raise ValueError(
                        f"AudioClassifierNode: TFLite model expects input shape {expected_shape} "
                        f"but features shape {features.shape} cannot be reshaped to match. "
                        f"Tried {inp_4d.shape} (4-D) and {inp_flat.shape} (flat)."
                    )

            self._model_obj.set_tensor(inp_detail["index"], inp)
            self._model_obj.invoke()
            probs = self._model_obj.get_tensor(out_detail["index"])[0].astype(np.float32)
        return probs, self._labels

    # ── PyTorch/ONNX backend ──────────────────────────────────────────────────

    def _pytorch_classify(self, features: np.ndarray) -> tuple[np.ndarray, list[str]]:
        model_path = self.config.model_path
        ext = model_path.lower()

        if ext.endswith(".onnx"):
            return self._onnx_classify(features)

        try:
            import torch  # type: ignore
        except ImportError:
            raise ImportError(
                "AudioClassifierNode: 'torch' required for backend='pytorch'. "
                "Install with: pip install torch>=2.0"
            )

        if self._model_obj is None:
            self._model_obj = torch.jit.load(model_path, map_location="cpu")
            self._model_obj.eval()
            labels_path = Path(model_path).parent / "labels.txt"
            self._labels = labels_path.read_text().strip().splitlines() if labels_path.exists() else []

        inp = torch.from_numpy(features[np.newaxis, ..., np.newaxis].astype(np.float32))
        with torch.no_grad():
            probs = torch.softmax(self._model_obj(inp), dim=-1)[0].numpy()
        return probs, self._labels

    def _onnx_classify(self, features: np.ndarray) -> tuple[np.ndarray, list[str]]:
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError:
            raise ImportError(
                "AudioClassifierNode: 'onnxruntime' required for ONNX models. "
                "Install with: pip install onnxruntime>=1.16"
            )

        if self._model_obj is None:
            self._model_obj = ort.InferenceSession(self.config.model_path)
            labels_path = Path(self.config.model_path).parent / "labels.txt"
            self._labels = labels_path.read_text().strip().splitlines() if labels_path.exists() else []

        inp_name = self._model_obj.get_inputs()[0].name
        inp = features[np.newaxis, ..., np.newaxis].astype(np.float32)
        probs = self._model_obj.run(None, {inp_name: inp})[0][0].astype(np.float32)
        return probs, self._labels
