"""WakewordInferNode — detect a trained wake word in audio (ONNX).

Uses livekit-wakeword's stateless ``WakeWordModel``: each ``window_s``
window (default 2 s, the classifier's 16-embedding span) runs through the
bundled ONNX mel-spectrogram + speech-embedding front end and the exported
classifier head. Windows slide by ``hop_s``; consecutive windows above the
threshold are merged into one detection, and a ``refractory_s`` gap
suppresses re-triggers — the same behaviour as the upstream live listener,
applied offline to files.

Model: the ``model`` port (a run from wakeword_export_onnx; its tuned
threshold is used when ``threshold`` is 0) or ``model_path`` (.onnx).
Output: one PredictionResult per input — ``predicted_label`` is the model
name when the wake word was detected, else ``"none"``; ``probabilities``
holds the max score; ``metadata.detections`` the time spans.
"""
from __future__ import annotations

import importlib
import logging
import threading
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.prediction_result import PredictionResult

_pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
_types = importlib.import_module(f"{_pkg}.types")
_ww = importlib.import_module(f"{_pkg}._ww")
WakeWordRun = _types.WakeWordRun
_pcm = _ww._pcm  # shared decoder (AudioSample / dict / WAV bytes / path → mono float)

log = logging.getLogger(__name__)
_MODELS: dict[str, Any] = {}
_LOCK = threading.Lock()


def load_detector(onnx_path: str) -> Any:
    model_cls = _ww.lib("inference.model").WakeWordModel
    with _LOCK:
        if onnx_path not in _MODELS:
            _MODELS[onnx_path] = model_cls(models=[onnx_path])
    return _MODELS[onnx_path]


def score_timeline(detector: Any, audio: np.ndarray, *, window_s: float, hop_s: float,
                   sr: int = 16000, min_level_db: float = -60.0) -> list[tuple[float, float]]:
    """``[(window_end_s, score), ...]`` over the clip (short clips are left-padded to one window).

    Windows whose RMS is below ``min_level_db`` dBFS score 0: digital silence
    cannot contain a wake word and lies outside the classifier's training data."""
    win = int(round(window_s * sr))
    hop = max(1, int(round(hop_s * sr)))
    if audio.size < win:
        audio = np.concatenate([np.zeros(win - audio.size, dtype=np.float32), audio])
    out: list[tuple[float, float]] = []
    ends = list(range(win, audio.size + 1, hop))
    if not ends or ends[-1] != audio.size:
        ends.append(audio.size)
    floor = 10.0 ** (min_level_db / 20.0)
    for end in ends:
        chunk = audio[end - win:end]
        if float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2))) < floor:
            out.append((end / sr, 0.0))
            continue
        scores = detector.predict(chunk)
        out.append((end / sr, float(max(scores.values())) if scores else 0.0))
    return out


def detections_from(timeline: list[tuple[float, float]], *, threshold: float, window_s: float,
                    refractory_s: float) -> list[dict[str, float]]:
    events: list[dict[str, float]] = []
    for t_end, score in timeline:
        if score < threshold:
            continue
        if events and t_end - events[-1]["last_end_s"] <= refractory_s:
            ev = events[-1]
            ev["last_end_s"] = t_end
            if score > ev["score"]:
                ev["score"] = score
                ev["peak_end_s"] = t_end
            continue
        events.append({"start_s": max(0.0, t_end - window_s), "last_end_s": t_end, "peak_end_s": t_end, "score": score})
    return [{"start_s": round(e["start_s"], 3), "end_s": round(e["last_end_s"], 3),
             "peak_end_s": round(e["peak_end_s"], 3), "score": round(e["score"], 4)} for e in events]


class WakewordInferNode(Node):
    """Offline wake-word detection over audio with an exported ONNX head."""

    node_type: ClassVar[str] = "wakeword_infer"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="wakeword_infer",
        label="Wake Word Detect",
        description="Detect a trained wake word in audio: sliding 2 s windows through mel + speech-embedding ONNX and the exported head; merged detections with times.",
        category="Inference",
        version="2.0.0",
        tags=["wakeword", "inference", "onnx", "detection", "livekit-wakeword"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "audio": InputPort(name="audio", data_type=list, required=True,
                           description="AudioSample list (any rate / channels; decoded to 16 kHz mono)."),
        "model": InputPort(name="model", data_type=WakeWordRun | None, required=False,
                           description="Run from wakeword_export_onnx (or set config.model_path)."),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[PredictionResult],
                             description="One PredictionResult per input with detections in metadata."),
    }

    class Config(NodeConfig):
        model_path: str = Field(default="", title="Model (.onnx)", description="Exported classifier; overrides the model port.")
        use_int8: bool = Field(default=False, title="Use INT8", description="Use the run's .int8.onnx when present.")
        threshold: float = Field(default=0.0, ge=0.0, le=1.0, title="Threshold", description="0 = the run's tuned threshold (else 0.5).")
        window_s: float = Field(default=2.0, ge=1.3, le=5.0, title="Window (s)")
        hop_s: float = Field(default=0.1, ge=0.08, le=2.0, title="Hop (s)")
        min_level_db: float = Field(default=-60.0, ge=-120.0, le=0.0, title="Silence floor (dBFS)", description="Windows quieter than this score 0 (digital silence).")
        refractory_s: float = Field(default=1.0, ge=0.0, le=10.0, title="Refractory (s)", description="Windows above threshold within this gap merge into one detection.")

    def _model(self, run: Any) -> tuple[str, float, str]:
        cfg = self.config
        tuned = None
        name = ""
        if cfg.model_path.strip():
            path = cfg.model_path.strip()
        else:
            if run is None:
                raise ValueError("wakeword_infer: no model — connect wakeword_export_onnx or set config.model_path")
            info = _ww.as_run(run)
            path = (info.get("onnx_int8_path") if cfg.use_int8 else "") or info.get("onnx_path") or ""
            tuned = info.get("threshold")
            name = info.get("model_name", "")
            if not path:
                raise ValueError(f"wakeword_infer: run {info['model_dir']} has no ONNX export — run wakeword_export_onnx first")
        if not Path(path).is_file():
            raise FileNotFoundError(f"wakeword_infer: model {path} not found")
        threshold = cfg.threshold if cfg.threshold > 0 else float(tuned if tuned is not None else 0.5)
        return path, threshold, name or Path(path).stem.replace(".int8", "")

    def process(self, inputs: dict) -> dict:
        cfg = self.config
        inputs = inputs or {}
        path, threshold, name = self._model(inputs.get("model"))
        detector = load_detector(path)
        items = inputs.get("audio") or []
        if not isinstance(items, list):
            items = [items]
        out: list[PredictionResult] = []
        for item in items:
            audio = _ww.pcm16k(item)
            src = _ww.source_of(item)
            if audio.size == 0:
                raise ValueError(f"wakeword_infer: empty audio for {src or 'input'}")
            timeline = score_timeline(detector, audio, window_s=cfg.window_s, hop_s=cfg.hop_s,
                                      min_level_db=cfg.min_level_db)
            dets = detections_from(timeline, threshold=threshold, window_s=cfg.window_s, refractory_s=cfg.refractory_s)
            max_score = max(s for _, s in timeline)
            meta = dict(getattr(item, "metadata", None) or (item.get("metadata") if isinstance(item, dict) else None) or {})
            meta["wakeword"] = {
                "model": path, "threshold": threshold, "detected": bool(dets), "n_detections": len(dets),
                "detections": dets, "max_score": round(max_score, 4), "duration_s": round(audio.size / 16000, 3),
                "window_s": cfg.window_s, "hop_s": cfg.hop_s,
                "timeline": [[round(t, 3), round(s, 4)] for t, s in timeline][:2000],
            }
            label = getattr(item, "label", None) or (item.get("label") if isinstance(item, dict) else None)
            if label:
                meta.setdefault("true_label", label)
            out.append(PredictionResult(source_path=src, predicted_label=name if dets else "none",
                                        probabilities={name: round(max_score, 4)}, metadata=meta))
        return {"output": out}
