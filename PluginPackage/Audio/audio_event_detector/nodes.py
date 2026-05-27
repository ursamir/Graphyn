"""AudioEventDetectorNode — temporal acoustic event detection with onset/offset timestamps.

Backends:
    yamnet   — YAMNet 521-class detection (tensorflow_hub, no custom model needed)
    tflite   — custom TFLite model (clip-level only — no temporal windowing)
    pytorch  — custom PyTorch model (clip-level only — no temporal windowing)
    auto     — yamnet if TF available, else tflite if model_path set, else error

Temporal resolution note:
    Only the ``yamnet`` backend provides true frame-level onset/offset timestamps.
    The ``tflite`` and ``pytorch`` backends treat the entire audio clip as a single
    frame and report ``start=0.0, end=<clip_duration>`` for every detected event.
    If per-event timestamps are required, use ``backend="yamnet"`` or implement
    frame-level windowing in a custom subclass.
"""
from __future__ import annotations

import copy
import logging
import threading
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)

# YAMNet class names (top-20 for built-in detection; full list loaded at runtime)
_YAMNET_COMMON_EVENTS = [
    "Speech", "Music", "Noise", "Silence", "Dog", "Cat",
    "Gunshot", "Cough", "Baby cry", "Alarm", "Laughter",
    "Applause", "Crowd", "Vehicle", "Engine", "Siren",
    "Telephone", "Doorbell", "Knock", "Typing",
]


class AudioEventDetectorNode(Node):
    """Temporal acoustic event detection with onset/offset timestamps.

    Config:
        model_path (str): path to TFLite or PyTorch model; empty = use built-in YAMNet
        backend (str): "yamnet" | "tflite" | "pytorch" | "auto"
        threshold (float): minimum confidence to report an event (default 0.5)
        event_types (list): filter to these event types; empty = all events
        min_event_duration_ms (float): merge events shorter than this (default 100)
        frame_hop_ms (float): analysis frame hop in ms (default 480 = YAMNet default)
    """

    node_type: ClassVar[str] = "audio_event_detector"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="audio_event_detector",
        label="Audio Event Detector",
        description=(
            "Temporal acoustic event detection with onset/offset timestamps. "
            "Built-in YAMNet (521 classes) or custom TFLite/PyTorch model."
        ),
        category="Detection",
        version="1.0.0",
        tags=["audio", "detection", "events", "yamnet", "tflite", "classification"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
        streaming_support=True,
        realtime_support=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="Audio samples to detect events in",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Audio samples with metadata['events'] populated",
        ),
        "events": OutputPort(
            name="events",
            data_type=list[dict],
            description="Flat list of event dicts: {event, start, end, confidence}",
        ),
    }

    class Config(NodeConfig):
        model_path: str = ""            # empty = built-in YAMNet
        backend: str = "auto"           # "yamnet" | "tflite" | "pytorch" | "auto"
        threshold: float = 0.5
        event_types: list = []          # empty = all events
        min_event_duration_ms: float = 100.0
        frame_hop_ms: float = 480.0     # YAMNet default: 0.48s hop
        merge_tolerance_ms: float = 10.0  # consecutive-event merge gap tolerance

    # ── multi-port process ────────────────────────────────────────────────────

    def process(self, inputs: dict) -> dict:
        if isinstance(inputs, list):
            samples: list[AudioSample] = inputs
        elif isinstance(inputs, dict):
            samples = inputs.get("input") or []
        else:
            samples = []
        backend = self._resolve_backend()

        output_samples: list[AudioSample] = []
        all_events: list[dict] = []

        for sample in samples:
            new_sample = copy.deepcopy(sample)
            events = self._detect(new_sample, backend)
            new_sample.metadata["events"] = events
            output_samples.append(new_sample)
            all_events.extend(events)

        return {"output": output_samples, "events": all_events}

    # ── backend resolution ────────────────────────────────────────────────────

    def _resolve_backend(self) -> str:
        b = self.config.backend
        if b == "yamnet":
            return "yamnet"
        if b == "tflite":
            return "tflite"
        if b == "pytorch":
            return "pytorch"
        # auto
        if not self.config.model_path:
            return "yamnet"
        ext = self.config.model_path.lower()
        if ext.endswith(".tflite"):
            return "tflite"
        if ext.endswith((".pt", ".pth", ".onnx")):
            return "pytorch"
        return "yamnet"

    # ── detection dispatch ────────────────────────────────────────────────────

    def _detect(self, sample: AudioSample, backend: str) -> list[dict]:
        if backend == "yamnet":
            return self._detect_yamnet(sample)
        elif backend == "tflite":
            return self._detect_tflite(sample)
        elif backend == "pytorch":
            return self._detect_pytorch(sample)
        return []

    # ── YAMNet detection ──────────────────────────────────────────────────────

    def _detect_yamnet(self, sample: AudioSample) -> list[dict]:
        try:
            import tensorflow as tf  # type: ignore
            import tensorflow_hub as hub  # type: ignore
        except ImportError:
            raise ImportError(
                "AudioEventDetectorNode: 'tensorflow' and 'tensorflow_hub' required for backend='yamnet'. "
                "Install with: pip install tensorflow>=2.12 tensorflow-hub>=0.14"
            )

        if not hasattr(self, "_yamnet_model"):
            # NOTE: each node instance loads its own copy of YAMNet.
            # In multi-instance pipelines this multiplies GPU/CPU memory usage.
            # Consider reusing a single shared instance if memory is constrained.
            self._yamnet_model = hub.load("https://tfhub.dev/google/yamnet/1")
            self._yamnet_classes = self._load_yamnet_classes()

        y = sample.data.astype(np.float32)
        sr = sample.sample_rate
        if sr != 16000:
            import librosa  # type: ignore
            y = librosa.resample(y=y, orig_sr=sr, target_sr=16000)
            sr = 16000

        if len(y) == 0:
            return []

        scores, embeddings, spectrogram = self._yamnet_model(y)
        scores_np = scores.numpy()  # (N_frames, 521)

        hop_s = self.config.frame_hop_ms / 1000.0
        threshold = self.config.threshold
        filter_types = set(t.lower() for t in self.config.event_types)
        min_dur_s = self.config.min_event_duration_ms / 1000.0

        events: list[dict] = []
        for frame_idx, frame_scores in enumerate(scores_np):
            top_class = int(np.argmax(frame_scores))
            confidence = float(frame_scores[top_class])
            if confidence < threshold:
                continue
            class_name = self._yamnet_classes[top_class] if top_class < len(self._yamnet_classes) else f"class_{top_class}"
            if filter_types and class_name.lower() not in filter_types:
                continue
            start_s = frame_idx * hop_s
            end_s = start_s + hop_s
            events.append({
                "event": class_name,
                "start": round(start_s, 3),
                "end": round(end_s, 3),
                "confidence": round(confidence, 4),
            })

        return self._merge_events(events, min_dur_s)

    # ── TFLite detection ──────────────────────────────────────────────────────

    def _detect_tflite(self, sample: AudioSample) -> list[dict]:
        """Run TFLite inference on an audio sample.

        Note: This backend performs clip-level classification only.
        All detected events are assigned ``start=0.0`` and
        ``end=<clip_duration>`` — no temporal windowing is performed.
        Use ``backend="yamnet"`` for frame-level onset/offset timestamps.
        """
        try:
            import tflite_runtime.interpreter as tflite  # type: ignore
        except ImportError:
            try:
                import tensorflow.lite as tflite  # type: ignore
            except ImportError:
                raise ImportError(
                    "AudioEventDetectorNode: TFLite runtime required for backend='tflite'. "
                    "Install with: pip install tflite-runtime>=2.14"
                )

        # Cache interpreter — load model once per node instance, not per sample.
        if not hasattr(self, "_tflite_interp"):
            self._tflite_interp = tflite.Interpreter(model_path=self.config.model_path)
            self._tflite_interp.allocate_tensors()
            self._tflite_lock = threading.Lock()

        from pathlib import Path
        with self._tflite_lock:
            interp = self._tflite_interp
            inp_detail = interp.get_input_details()[0]
            out_detail = interp.get_output_details()[0]

            y = sample.data.astype(np.float32)
            expected_len = int(np.prod(inp_detail["shape"]))

            # Pad or truncate to match the model's expected input length
            if len(y) < expected_len:
                log.warning(
                    "AudioEventDetectorNode: audio length %d < model input %d — zero-padding",
                    len(y), expected_len,
                )
                y = np.pad(y, (0, expected_len - len(y)))
            elif len(y) > expected_len:
                log.warning(
                    "AudioEventDetectorNode: audio length %d > model input %d — truncating",
                    len(y), expected_len,
                )
                y = y[:expected_len]

            input_data = y.reshape(inp_detail["shape"]).astype(inp_detail["dtype"])
            interp.set_tensor(inp_detail["index"], input_data)
            interp.invoke()
            probs = interp.get_tensor(out_detail["index"])[0]

        # Load labels
        labels_path = Path(self.config.model_path).parent / "labels.txt"
        labels = labels_path.read_text().strip().splitlines() if labels_path.exists() else [f"class_{i}" for i in range(len(probs))]

        clip_duration = float(len(sample.data) / sample.sample_rate)
        log.debug(
            "AudioEventDetectorNode (tflite): clip-level detection only — "
            "all events will have start=0.0, end=%.3f", clip_duration,
        )
        events: list[dict] = []
        for i, conf in enumerate(probs):
            if float(conf) >= self.config.threshold:
                label = labels[i] if i < len(labels) else f"class_{i}"
                events.append({
                    "event": label,
                    "start": 0.0,
                    "end": round(clip_duration, 3),
                    "confidence": round(float(conf), 4),
                })
        return events

    # ── PyTorch detection ─────────────────────────────────────────────────────

    def _detect_pytorch(self, sample: AudioSample) -> list[dict]:
        """Run PyTorch inference on an audio sample.

        Note: This backend performs clip-level classification only.
        All detected events are assigned ``start=0.0`` and
        ``end=<clip_duration>`` — no temporal windowing is performed.
        Use ``backend="yamnet"`` for frame-level onset/offset timestamps.
        """
        try:
            import torch  # type: ignore
        except ImportError:
            raise ImportError(
                "AudioEventDetectorNode: 'torch' required for backend='pytorch'. "
                "Install with: pip install torch>=2.0"
            )

        # Cache model — load once per node instance, not per sample.
        if not hasattr(self, "_pytorch_model"):
            self._pytorch_model = torch.jit.load(self.config.model_path, map_location="cpu")
            self._pytorch_model.eval()
            self._pytorch_lock = threading.Lock()

        from pathlib import Path
        with self._pytorch_lock:
            y = torch.from_numpy(sample.data.astype(np.float32)).unsqueeze(0)
            with torch.no_grad():
                probs = torch.softmax(self._pytorch_model(y), dim=-1)[0].numpy()

        labels_path = Path(self.config.model_path).parent / "labels.txt"
        labels = labels_path.read_text().strip().splitlines() if labels_path.exists() else [f"class_{i}" for i in range(len(probs))]

        clip_duration = float(len(sample.data) / sample.sample_rate)
        log.debug(
            "AudioEventDetectorNode (pytorch): clip-level detection only — "
            "all events will have start=0.0, end=%.3f", clip_duration,
        )
        events: list[dict] = []
        for i, conf in enumerate(probs):
            if float(conf) >= self.config.threshold:
                label = labels[i] if i < len(labels) else f"class_{i}"
                events.append({
                    "event": label,
                    "start": 0.0,
                    "end": round(clip_duration, 3),
                    "confidence": round(float(conf), 4),
                })
        return events

    def _load_yamnet_classes(self) -> list[str]:
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

        # Check disk cache in temp dir
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
            # Cache to disk for future offline use
            try:
                cache_path.write_text(content, encoding="utf-8")
            except OSError:
                pass
            reader = csv.DictReader(io.StringIO(content))
            return [row["display_name"] for row in reader]
        except Exception:
            log.warning(
                "AudioEventDetectorNode: could not load YAMNet class map "
                "(network unavailable). Using generic class names."
            )
            return [f"class_{i}" for i in range(521)]

    # ── event merging ─────────────────────────────────────────────────────────

    def _merge_events(self, events: list[dict], min_dur_s: float) -> list[dict]:
        """Merge consecutive same-class events and filter by min duration."""
        if not events:
            return []

        merge_tol_s = self.config.merge_tolerance_ms / 1000.0
        merged: list[dict] = []
        current = dict(events[0])

        for ev in events[1:]:
            if ev["event"] == current["event"] and ev["start"] <= current["end"] + merge_tol_s:
                current["end"] = max(current["end"], ev["end"])
                current["confidence"] = max(current["confidence"], ev["confidence"])
            else:
                if current["end"] - current["start"] >= min_dur_s:
                    merged.append(current)
                current = dict(ev)

        if current["end"] - current["start"] >= min_dur_s:
            merged.append(current)

        return merged
