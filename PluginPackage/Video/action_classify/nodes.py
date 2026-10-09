"""ActionClassifyNode — human-action recognition on video clips.

Backends:
    torchvision — Kinetics-400 video ResNets from torchvision
                  (``r3d_18`` default, ``mc3_18``, ``r2plus1d_18``); weights
                  download once from download.pytorch.org.
    onnx        — your own ONNX model (input ``1×3×T×112×112``, Kinetics
                  normalisation) with ``labels`` given in config.

``num_frames`` evenly spaced frames per clip are decoded with ffmpeg,
resized/cropped with the weights' own transforms, and classified. Each
clip yields a PredictionResult with the top-k label probabilities.
"""
from __future__ import annotations

import importlib
import logging
import threading
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.prediction_result import PredictionResult

_pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
_vio = importlib.import_module(f"{_pkg}._vio")

log = logging.getLogger(__name__)
_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()
_MEAN = np.array([0.43216, 0.394666, 0.37645], dtype=np.float32)
_STD = np.array([0.22803, 0.22145, 0.216989], dtype=np.float32)


def load_torchvision(arch: str):
    try:
        import torchvision.models.video as tvv  # type: ignore
    except ImportError as exc:
        raise RuntimeError("ActionClassifyNode: backend='torchvision' needs torch + torchvision") from exc
    weights_cls = {"r3d_18": tvv.R3D_18_Weights, "mc3_18": tvv.MC3_18_Weights, "r2plus1d_18": tvv.R2Plus1D_18_Weights}[arch]
    with _LOCK:
        if arch not in _CACHE:
            w = weights_cls.KINETICS400_V1
            model = getattr(tvv, arch)(weights=w).eval()
            _CACHE[arch] = (model, w.transforms(), list(w.meta["categories"]))
    return _CACHE[arch]


def _manual_clip(frames: np.ndarray) -> np.ndarray:
    """(T,H,W,3) uint8 at 128x171 → (1,3,T,112,112) float32, Kinetics-normalised."""
    t, h, w, _ = frames.shape
    y0, x0 = (h - 112) // 2, (w - 112) // 2
    x = frames[:, y0 : y0 + 112, x0 : x0 + 112].astype(np.float32) / 255.0
    x = (x - _MEAN) / _STD
    return np.ascontiguousarray(x.transpose(3, 0, 1, 2)[None])


class ActionClassifyNode(Node):
    """Kinetics-400 action recognition (torchvision video ResNets) or a custom ONNX model."""

    node_type: ClassVar[str] = "action_classify"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="action_classify",
        label="Action Classify",
        description="Recognise human actions in clips: torchvision Kinetics-400 video ResNets (r3d_18, mc3_18, r2plus1d_18) or a custom ONNX model.",
        category="Inference",
        version="1.0.0",
        tags=["video", "action-recognition", "kinetics", "torchvision", "onnx"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list, cardinality="single", required=True,
                           description="list[VideoSample] (clips or videos)"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[PredictionResult], description="Top-k actions per clip"),
    }

    class Config(NodeConfig):
        backend: Literal["torchvision", "onnx"] = Field(default="torchvision", title="Backend")
        arch: Literal["r3d_18", "mc3_18", "r2plus1d_18"] = Field(default="r3d_18", title="Architecture (torchvision)")
        model_path: str = Field(default="", title="ONNX model path", description="backend=onnx: model file (input 1x3xTx112x112).")
        labels: list[str] = Field(default_factory=list, title="Labels (onnx)", description="Class names in model output order (backend=onnx).")
        num_frames: int = Field(default=16, ge=4, le=64, title="Frames per clip")
        top_k: int = Field(default=5, ge=1, le=50, title="Top-k")

    def _frames(self, item: Any) -> tuple[np.ndarray, float, float]:
        path = _vio.media_path(item)
        start, end = _vio.span(item)
        if end is None:
            end = start + _vio.probe(path)["duration_s"]
        times = _vio.uniform_times(end - start, self.config.num_frames, start)
        frames = _vio.frames_at(path, times, width=171, height=128)
        if len(frames) < 2:
            raise ValueError(f"ActionClassifyNode: could not decode frames from {path}")
        return np.stack(frames), start, end

    def _scores(self, frames: np.ndarray) -> tuple[np.ndarray, list[str]]:
        cfg = self.config
        if cfg.backend == "torchvision":
            import torch  # type: ignore

            model, tf, cats = load_torchvision(cfg.arch)
            clip = tf(torch.from_numpy(frames).permute(0, 3, 1, 2))  # (T,C,H,W) uint8 → (C,T,112,112)
            with torch.inference_mode():
                logits = model(clip.unsqueeze(0))[0].numpy()
            return logits, cats
        if not cfg.model_path or not Path(cfg.model_path).is_file():
            raise FileNotFoundError(f"ActionClassifyNode: backend='onnx' needs model_path (got {cfg.model_path!r})")
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError as exc:
            raise RuntimeError("ActionClassifyNode: backend='onnx' needs onnxruntime") from exc
        key = f"onnx:{cfg.model_path}"
        with _LOCK:
            if key not in _CACHE:
                _CACHE[key] = ort.InferenceSession(cfg.model_path, providers=["CPUExecutionProvider"])
        sess = _CACHE[key]
        logits = np.asarray(sess.run(None, {sess.get_inputs()[0].name: _manual_clip(frames)})[0]).reshape(-1)
        labels = list(cfg.labels) or [f"class_{i}" for i in range(logits.size)]
        if len(labels) != logits.size:
            raise ValueError(f"ActionClassifyNode: {len(labels)} labels but model outputs {logits.size} classes")
        return logits, labels

    def process(self, items: Any) -> list:
        out: list = []
        for item in _vio.as_list(items):
            frames, start, end = self._frames(item)
            logits, labels = self._scores(frames)
            p = np.exp(logits - logits.max())
            p = p / p.sum()
            top = np.argsort(-p)[: self.config.top_k]
            path = _vio.media_path(item)
            out.append(PredictionResult(
                source_path=str(_vio.get(item, "source_path", "") or path),
                predicted_label=labels[int(top[0])],
                probabilities={labels[int(i)]: round(float(p[i]), 5) for i in top},
                metadata={"video_path": path, "start_s": round(start, 3), "end_s": round(end, 3),
                          "score": round(float(p[top[0]]), 5), "label": str(_vio.get(item, "label", "") or ""),
                          "model": self.config.arch if self.config.backend == "torchvision" else self.config.model_path,
                          "n_frames": int(frames.shape[0])},
            ))
        return out
