"""VideoEmbedNode — CLIP embeddings for videos, clips or frames.

Videos/clips: ``num_frames`` evenly spaced frames are decoded with ffmpeg,
embedded with a CLIP image encoder (transformers, default
``openai/clip-vit-base-patch32``) and mean-pooled (``pooling=mean``) or
emitted per frame (``pooling=none``). Frames (ImageSample) are embedded
directly. Embeddings are L2-normalised, so they live in CLIP's joint
image–text space; with ``zero_shot_labels`` each item also gets a
softmax over those text prompts in ``metadata["zero_shot"]``.
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

_pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
_types = importlib.import_module(f"{_pkg}.types")
_vio = importlib.import_module(f"{_pkg}._vio")
EmbeddingVector = _types.EmbeddingVector

log = logging.getLogger(__name__)
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()


def load_clip(model_id: str):
    try:
        import torch  # type: ignore  # noqa: F401
        from transformers import CLIPModel, CLIPProcessor  # type: ignore
    except ImportError as exc:
        raise RuntimeError("VideoEmbedNode: needs torch + transformers") from exc
    with _LOCK:
        if model_id not in _CACHE:
            _CACHE[model_id] = (CLIPProcessor.from_pretrained(model_id), CLIPModel.from_pretrained(model_id).eval())
    return _CACHE[model_id]


def _feats(out: Any) -> Any:
    import torch  # type: ignore

    if torch.is_tensor(out):
        return out
    for attr in ("image_embeds", "text_embeds", "pooler_output"):
        v = getattr(out, attr, None)
        if v is not None:
            return v
    return out[0]


class VideoEmbedNode(Node):
    """CLIP image-encoder embeddings for videos (pooled frames) or frames."""

    node_type: ClassVar[str] = "video_embed"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="video_embed",
        label="Video Embed",
        description="CLIP embeddings for videos/clips (mean over sampled frames) or frames, with optional zero-shot labels.",
        category="Features",
        version="1.0.0",
        tags=["video", "embedding", "clip", "transformers", "zero-shot"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list, cardinality="single", required=True,
                           description="list[VideoSample] or list[ImageSample]"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[EmbeddingVector], description="One embedding per video (or per frame)"),
    }

    class Config(NodeConfig):
        model: str = Field(default="openai/clip-vit-base-patch32", title="CLIP model", description="Hugging Face CLIP checkpoint id or local path.")
        num_frames: int = Field(default=8, ge=1, le=64, title="Frames per video")
        pooling: Literal["mean", "none"] = Field(default="mean", title="Pooling", description="mean = one vector per video; none = one per frame.")
        zero_shot_labels: list[str] = Field(default_factory=list, title="Zero-shot labels",
                                            description="Optional text labels; each result gets a probability per label (zero-shot).")
        batch_size: int = Field(default=16, ge=1, title="Batch size")

    def _embed_images(self, images: list[np.ndarray]) -> np.ndarray:
        import torch  # type: ignore

        proc, model = load_clip(self.config.model)
        chunks = []
        for i in range(0, len(images), self.config.batch_size):
            batch = proc(images=images[i : i + self.config.batch_size], return_tensors="pt")
            with torch.inference_mode():
                chunks.append(_feats(model.get_image_features(pixel_values=batch["pixel_values"])).detach().cpu().numpy())
        e = np.concatenate(chunks, 0).astype(np.float32)
        return e / np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-8)

    def _text(self) -> np.ndarray | None:
        labels = [l for l in self.config.zero_shot_labels if str(l).strip()]
        if not labels:
            return None
        import torch  # type: ignore

        proc, model = load_clip(self.config.model)
        tok = proc(text=[f"a photo of {l}" for l in labels], return_tensors="pt", padding=True)
        with torch.inference_mode():
            t = _feats(model.get_text_features(input_ids=tok["input_ids"], attention_mask=tok["attention_mask"])).detach().cpu().numpy()
        t = t.astype(np.float32)
        return t / np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-8)

    def process(self, items: Any) -> list:
        cfg = self.config
        text = self._text()
        _, model = load_clip(cfg.model)
        scale = float(model.logit_scale.exp().item()) if hasattr(model, "logit_scale") else 100.0
        out: list = []
        for item in _vio.as_list(items):
            path = _vio.media_path(item)
            label = str(_vio.get(item, "label", "") or "")
            if Path(path).suffix.lower() in _IMAGE_EXTS:
                info = _vio.probe(path)
                imgs = _vio.frames_at(path, [0.0], width=info["width"], height=info["height"])
                times = [float(_vio.get(item, "timestamp_s", 0.0) or 0.0)]
                source = str(_vio.get(item, "source_path", "") or path)
            else:
                start, end = _vio.span(item)
                if end is None:
                    end = start + _vio.probe(path)["duration_s"]
                times = _vio.uniform_times(end - start, cfg.num_frames, start)
                imgs = _vio.frames_at(path, times)
                source = str(_vio.get(item, "source_path", "") or path)
            if not imgs:
                raise ValueError(f"VideoEmbedNode: could not decode frames from {path}")
            emb = self._embed_images(imgs)
            vecs = [emb.mean(0)] if cfg.pooling == "mean" else list(emb)
            for k, v in enumerate(vecs):
                v = v / max(float(np.linalg.norm(v)), 1e-8)
                meta: dict[str, Any] = {"video_path": path, "n_frames": len(imgs),
                                        "timestamps_s": [round(t, 3) for t in times] if cfg.pooling == "mean" else [round(times[k], 3)]}
                if text is not None:
                    logits = scale * (text @ v)
                    p = np.exp(logits - logits.max())
                    p = p / p.sum()
                    meta["zero_shot"] = {l: round(float(x), 4) for l, x in zip(cfg.zero_shot_labels, p)}
                    meta["zero_shot_top"] = cfg.zero_shot_labels[int(np.argmax(p))]
                out.append(EmbeddingVector(embedding=v.astype(np.float32), source_path=source, label=label,
                                           embedding_model=cfg.model, pooling=cfg.pooling, metadata=meta))
        return out
