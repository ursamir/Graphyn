"""AudioGeneratorNode — text-to-music generation with MusicGen (transformers).

Backend ``musicgen``: Meta MusicGen via Hugging Face ``transformers``
(``facebook/musicgen-{small,medium,large}``; ``facebook/musicgen-melody`` when
``conditioning_audio`` is set, which conditions on that clip's melody).
Weights download once from huggingface.co. CPU works (small: roughly
real-time to a few × real-time); a GPU is faster.

Each prompt yields one AudioSample (mono float32 at the model rate, 32 kHz),
also written as ``{output_dir}/generated_{i}.wav`` and published as a file tree.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import Field, field_validator

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)

_MODELS: dict[str, Any] = {}
_LOCK = threading.Lock()
_FRAME_RATE = 50  # MusicGen EnCodec tokens per second


def _prompt_texts(prompts: Any) -> list[str]:
    if prompts is None:
        return []
    if isinstance(prompts, str):
        return [prompts] if prompts.strip() else []
    if isinstance(prompts, dict):
        prompts = [prompts]
    out = []
    for p in prompts:
        if isinstance(p, str):
            text = p
        elif isinstance(p, dict):
            text = str(p.get("text") or p.get("prompt") or p.get("content") or "")
        else:
            text = str(getattr(p, "text", None) or getattr(p, "content", None) or "")
            if not text:
                raise TypeError(f"AudioGeneratorNode: cannot read a prompt from {type(p).__name__}")
        if text.strip():
            out.append(text.strip())
    return out


class AudioGeneratorNode(Node):
    """Generate music from text prompts with MusicGen."""

    node_type: ClassVar[str] = "audio_generator"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="audio_generator",
        label="Audio Generator",
        description=(
            "Generate music from text prompts with Meta MusicGen (Hugging Face transformers); "
            "optional melody conditioning from an audio clip."
        ),
        category="Generation",
        version="2.0.0",
        tags=["audio", "generation", "musicgen", "generative"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=False,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object | None,
            cardinality="single",
            required=False,
            description="Text prompt(s): str, list of str, or {text}/{prompt} dicts (optional — uses config.prompt)",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Generated AudioSample objects (also written as WAV files)",
        )
    }

    class Config(NodeConfig):
        model_size: Literal["small", "medium", "large"] = Field(default="small", title="Model size", description="facebook/musicgen-<size> (ignored when conditioning audio selects musicgen-melody).")
        duration_s: float = Field(default=5.0, title="Duration (s)", description="Length of generated audio in seconds (max 30).")
        prompt: str = Field(default="", title="Prompt", description="Text prompt used when the input port is empty.")
        conditioning_audio: str = Field(default="", title="Conditioning audio", description="Optional audio file whose melody conditions generation (uses facebook/musicgen-melody).")
        temperature: float = Field(default=1.0, title="Temperature", description="Sampling temperature (higher = more random).")
        top_k: int = Field(default=250, title="Top-K", description="Top-k sampling over audio tokens.")
        guidance_scale: float = Field(default=3.0, title="Guidance scale", description="Classifier-free guidance scale.")
        output_dir: str = Field(default="workspace/datasets/output/generated_audio", title="Output dir", description="Where generated WAV files are written.")

        @field_validator("duration_s")
        @classmethod
        def _validate_duration_s(cls, v: float) -> float:
            if not 0 < v <= 30:
                raise ValueError("duration_s must be in (0, 30]")
            return v

        @field_validator("temperature")
        @classmethod
        def _validate_temperature(cls, v: float) -> float:
            if v <= 0:
                raise ValueError("temperature must be > 0")
            return v

        @field_validator("top_k")
        @classmethod
        def _validate_top_k(cls, v: int) -> int:
            if v < 1:
                raise ValueError("top_k must be >= 1")
            return v

        @field_validator("guidance_scale")
        @classmethod
        def _validate_guidance_scale(cls, v: float) -> float:
            if v < 0:
                raise ValueError("guidance_scale must be >= 0")
            return v

    def _load(self, model_id: str, melody: bool):
        try:
            import torch  # type: ignore  # noqa: F401
            from transformers import AutoProcessor  # type: ignore
        except ImportError as exc:
            raise RuntimeError("AudioGeneratorNode: needs torch + transformers in this plugin's venv") from exc
        with _LOCK:
            if model_id not in _MODELS:
                if melody:
                    from transformers import MusicgenMelodyForConditionalGeneration as M  # type: ignore
                else:
                    from transformers import MusicgenForConditionalGeneration as M  # type: ignore
                log.info("AudioGeneratorNode: loading %s", model_id)
                model = M.from_pretrained(model_id).eval()
                _MODELS[model_id] = (AutoProcessor.from_pretrained(model_id), model)
        return _MODELS[model_id]

    def process(self, prompts=None) -> list[AudioSample]:
        import torch  # type: ignore

        texts = _prompt_texts(prompts) or ([self.config.prompt.strip()] if self.config.prompt.strip() else [])
        if not texts:
            raise ValueError("AudioGeneratorNode: no prompt — connect prompts to the input port or set config.prompt")
        melody_path = (self.config.conditioning_audio or "").strip()
        model_id = "facebook/musicgen-melody" if melody_path else f"facebook/musicgen-{self.config.model_size}"
        processor, model = self._load(model_id, bool(melody_path))
        sr = int(model.config.audio_encoder.sampling_rate)

        kwargs: dict[str, Any] = {"text": texts, "padding": True, "return_tensors": "pt"}
        if melody_path:
            p = Path(melody_path)
            if not p.is_file():
                raise FileNotFoundError(f"AudioGeneratorNode: conditioning_audio not found: {melody_path}")
            import soundfile as sf  # type: ignore

            mel, mel_sr = sf.read(str(p), dtype="float32", always_2d=True)
            mel = mel.mean(axis=1)
            if mel_sr != sr:
                from math import gcd

                from scipy.signal import resample_poly

                g = gcd(int(mel_sr), sr)
                mel = resample_poly(mel, sr // g, int(mel_sr) // g).astype(np.float32)
            kwargs.update(audio=[mel] * len(texts), sampling_rate=sr)
        inputs = processor(**kwargs)
        max_new = max(int(self.config.duration_s * _FRAME_RATE), 1)
        torch.manual_seed(int(getattr(self, "seed", 0) or 0))
        with torch.inference_mode():
            audio = model.generate(
                **inputs, do_sample=True, temperature=float(self.config.temperature),
                top_k=int(self.config.top_k), guidance_scale=float(self.config.guidance_scale),
                max_new_tokens=max_new,
            )
        return self._to_samples(audio, sr, texts, model_id)

    def _to_samples(self, audio, sr: int, texts: list[str], model_id: str) -> list[AudioSample]:
        import soundfile as sf  # type: ignore

        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        results: list[AudioSample] = []
        files = []
        for i, wav in enumerate(audio):
            y = wav.detach().cpu().numpy().astype(np.float32)
            if y.ndim > 1:
                y = y.mean(axis=0)
            path = out_dir / f"generated_{i}.wav"
            sf.write(str(path), y, sr)
            files.append(path.name)
            results.append(AudioSample(
                path=str(path), sample_rate=sr, data=y, label="generated",
                metadata={"audio_generator": {
                    "backend": "musicgen", "model": model_id, "prompt": texts[i][:200],
                    "duration_s": round(len(y) / sr, 3), "temperature": self.config.temperature,
                }},
            ))
        self.publish_files(out_dir, files, total=len(files))
        return results
