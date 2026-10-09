"""VideoCaptionNode — caption video frames with a vision-language model.

Inputs are frames (ImageSample from frame_sample) or videos/clips
(VideoSample; ``frames_per_video`` evenly spaced frames are grabbed with
ffmpeg). Each frame is sent as a base64 JPEG to an OpenAI-compatible
``/chat/completions`` endpoint through Graphyn's LLM client:

* ``ollama`` (default) — a local vision model such as ``moondream``,
  ``llava-phi3`` or ``llava``; no key needed (``OLLAMA_BASE_URL``).
* ``openai_compat`` — any hosted OpenAI-compatible vision model; needs a
  credential connection (kind openai_compat) or the named secret, else it
  fails with a needs-credentials error.

Outputs: ``output`` (list of caption strings) and ``captions``
(CaptionRecord with source video, frame path and timestamp).
"""
from __future__ import annotations

import base64
import importlib
import logging
import time
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

_pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
_types = importlib.import_module(f"{_pkg}.types")
_vio = importlib.import_module(f"{_pkg}._vio")
CaptionRecord = _types.CaptionRecord

log = logging.getLogger(__name__)
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class VideoCaptionNode(Node):
    """Caption frames with a local (Ollama) or hosted vision-language model."""

    node_type: ClassVar[str] = "video_caption"
    _siso: ClassVar[bool] = False

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="video_caption",
        label="Video Caption",
        description="Caption video frames with a vision-language model: local Ollama (moondream, llava) or an OpenAI-compatible endpoint.",
        category="Processing",
        version="1.0.0",
        tags=["video", "caption", "vlm", "ollama", "llm"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=False,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list, cardinality="single", required=True,
                           description="list[ImageSample] (frames) or list[VideoSample]"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[str], description="Caption text per frame"),
        "captions": OutputPort(name="captions", data_type=list[CaptionRecord], description="Captions with source/timestamp"),
    }

    class Config(NodeConfig):
        provider: Literal["ollama", "openai_compat"] = Field(default="ollama", title="Provider")
        model: str = Field(default="moondream", title="Model", description="Vision model id (e.g. moondream, llava-phi3, gpt-4o-mini).")
        base_url: str = Field(default="", title="Base URL", description="Empty = OLLAMA_BASE_URL / connection default.")
        connection_id: str = Field(default="", title="Connection", description="Credential connection id (openai_compat).")
        api_secret_name: str = Field(default="OPENAI_API_KEY", title="API secret name")
        prompt: str = Field(default="Describe what happens in this video frame in one sentence.", title="Prompt")
        frames_per_video: int = Field(default=3, ge=1, le=32, title="Frames per video", description="For VideoSample inputs.")
        max_frames: int = Field(default=32, ge=1, title="Max frames", description="Cap on frames captioned per run.")
        image_width: int = Field(default=512, ge=64, title="Image width (px)", description="Frames are downscaled to this width before sending.")
        temperature: float = Field(default=0.0, ge=0, le=2, title="Temperature")
        timeout_s: float = Field(default=180.0, gt=0, title="Timeout per frame (s)")

    def _frames(self, items: list) -> list[dict]:
        cfg = self.config
        frames: list[dict] = []
        for item in items:
            path = _vio.media_path(item)
            ts = _vio.get(item, "timestamp_s")
            if Path(path).suffix.lower() in _IMAGE_EXTS:
                frames.append({"jpeg": lambda p=path: _vio.jpeg_bytes_of_image(p, width=cfg.image_width),
                               "source": str(_vio.get(item, "source_path", "") or path), "image": path,
                               "t": float(ts or 0.0), "label": str(_vio.get(item, "label", "") or "")})
            else:
                start, end = _vio.span(item)
                if end is None:
                    end = start + _vio.probe(path)["duration_s"]
                offset = float((_vio.get(item, "metadata", {}) or {}).get("source_start_s", 0.0) or 0.0)
                source = str(_vio.get(item, "source_path", "") or path)
                for t in _vio.uniform_times(end - start, cfg.frames_per_video, start):
                    frames.append({"jpeg": lambda p=path, tt=t: _vio.jpeg_bytes_at(p, tt, width=cfg.image_width),
                                   "source": source, "image": "", "t": round(offset + t if source != path else t, 3),
                                   "label": str(_vio.get(item, "label", "") or "")})
            if len(frames) >= cfg.max_frames:
                break
        return frames[: cfg.max_frames]

    def process(self, inputs: dict) -> dict:
        from app.core.ml.llm_client import NeedsCredentialsError, chat_completion

        cfg = self.config
        frames = self._frames(_vio.as_list(inputs.get("input")))
        if not frames:
            raise ValueError("VideoCaptionNode: no frames or videos on the input")
        texts: list[str] = []
        records: list = []
        conn = cfg.connection_id or None
        for fr in frames:
            jpeg = fr["jpeg"]()
            messages = [{"role": "user", "content": [
                {"type": "text", "text": cfg.prompt},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
            ]}]
            req_hash = self.body_sha256(jpeg)
            t0 = time.monotonic()
            try:
                res = chat_completion(messages=messages, provider=cfg.provider, model=cfg.model,
                                      temperature=cfg.temperature, base_url=cfg.base_url or None,
                                      api_secret_name=cfg.api_secret_name, connection_id=conn,
                                      timeout_s=cfg.timeout_s)
            except NeedsCredentialsError:
                raise
            except Exception as exc:
                self.record_external_call("llm", "POST", cfg.base_url or f"llm://{cfg.provider}", None,
                                          request_sha256=req_hash, duration_ms=(time.monotonic() - t0) * 1000,
                                          connection_id=conn, error=type(exc).__name__)
                raise RuntimeError(f"VideoCaptionNode: {cfg.provider}/{cfg.model} failed: {exc}") from exc
            text = str(res.get("content") or "").strip()
            self.record_external_call("llm", "POST", str(res.get("base_url") or f"llm://{cfg.provider}"), 200,
                                      request_sha256=req_hash, response_sha256=text,
                                      duration_ms=(time.monotonic() - t0) * 1000, connection_id=conn)
            if not text:
                raise RuntimeError(f"VideoCaptionNode: {cfg.model} returned an empty caption for {fr['source']}@{fr['t']}s")
            texts.append(text)
            records.append(CaptionRecord(text=text, source_path=fr["source"], image_path=fr["image"],
                                         timestamp_s=fr["t"], model=str(res.get("model") or cfg.model),
                                         provider=str(res.get("provider") or cfg.provider), label=fr["label"]))
        return {"output": texts, "captions": records}
