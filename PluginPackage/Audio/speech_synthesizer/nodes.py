"""SpeechSynthesizerNode — text-to-speech.

Backends:
    mms    — Meta MMS-TTS (VITS) via Hugging Face transformers,
             ``facebook/mms-tts-<iso639-3>`` (1,100+ languages; weights
             download once from huggingface.co) [default]
    espeak — eSpeak NG formant synthesiser (needs the ``espeak-ng`` binary
             on the host/image; fails clearly when it is missing)
    auto   — mms

Each text yields one AudioSample, also written to
``{output_dir}/synth_{i:04d}.wav`` and published as a file tree.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)

_MODELS: dict[str, Any] = {}
_LOCK = threading.Lock()

# ISO 639-1 → 639-3 for the MMS checkpoint names (any 639-3 code also works).
_ISO3 = {
    "en": "eng", "de": "deu", "fr": "fra", "es": "spa", "hi": "hin", "ru": "rus",
    "it": "ita", "pt": "por", "nl": "nld", "pl": "pol", "tr": "tur", "vi": "vie",
    "bn": "ben", "ta": "tam", "te": "tel", "mr": "mar", "gu": "guj", "kn": "kan",
    "ml": "mal", "ur": "urd", "ar": "ara", "fa": "fas", "sw": "swh", "id": "ind",
    "ko": "kor", "uk": "ukr", "ro": "ron", "hu": "hun", "el": "ell", "th": "tha",
}


def _texts(inp: Any) -> list[str]:
    if inp is None:
        return []
    if isinstance(inp, str):
        return [inp]
    if isinstance(inp, dict):
        inp = [inp]
    out = []
    for t in inp:
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, dict):
            out.append(str(t.get("text") or t.get("content") or ""))
        else:
            out.append(str(getattr(t, "text", None) or getattr(t, "content", None) or ""))
    return [t.strip() for t in out if t and t.strip()]


def mms_model_id(language: str, model_name: str = "") -> str:
    if model_name.strip():
        return model_name.strip()
    lang = (language or "en").strip().lower().split("-")[0]
    return f"facebook/mms-tts-{_ISO3.get(lang, lang)}"


def _load_mms(model_id: str):
    try:
        import torch  # type: ignore  # noqa: F401
        from transformers import AutoTokenizer, VitsModel  # type: ignore
    except ImportError as exc:
        raise RuntimeError("SpeechSynthesizerNode: backend='mms' needs torch + transformers") from exc
    with _LOCK:
        if model_id not in _MODELS:
            log.info("SpeechSynthesizerNode: loading %s", model_id)
            _MODELS[model_id] = (AutoTokenizer.from_pretrained(model_id), VitsModel.from_pretrained(model_id).eval())
    return _MODELS[model_id]


def synthesize_mms(text: str, model_id: str, *, speed: float = 1.0, noise_scale: float = 0.667,
                   seed: int = 0) -> tuple[np.ndarray, int]:
    import torch  # type: ignore

    tok, model = _load_mms(model_id)
    inputs = tok(text, return_tensors="pt")
    if inputs["input_ids"].shape[-1] == 0:
        raise ValueError(f"SpeechSynthesizerNode: {model_id} cannot tokenize {text!r} (wrong language/script?)")
    with _LOCK:
        model.speaking_rate = float(speed)
        model.noise_scale = float(noise_scale)
        torch.manual_seed(int(seed))
        with torch.inference_mode():
            wav = model(**inputs).waveform[0].detach().cpu().numpy().astype(np.float32)
    return wav, int(model.config.sampling_rate)


class SpeechSynthesizerNode(Node):
    """Text-to-speech with MMS-TTS (VITS) or eSpeak NG."""

    node_type: ClassVar[str] = "speech_synthesizer"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="speech_synthesizer",
        label="Speech Synthesizer",
        description=(
            "Text-to-speech: Meta MMS-TTS (VITS, 1,100+ languages, via transformers) "
            "or eSpeak NG."
        ),
        category="Generation",
        version="2.0.0",
        tags=["audio", "tts", "speech", "synthesis", "mms", "espeak", "generation"],
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
            description="Text(s) to synthesize: str, list of str, or {text} dicts (optional — uses config.text)",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Synthesized AudioSample objects (also written as WAV files)",
        )
    }

    class Config(NodeConfig):
        backend: Literal["mms", "espeak", "auto"] = Field(default="mms", title="Backend", description="mms: Meta MMS-TTS via transformers; espeak: eSpeak NG binary; auto: mms.")
        text: str = Field(default="", title="Text", description="Text used when the input port is empty.")
        model_name: str = Field(default="", title="Model name", description="mms: HF model id override (empty → facebook/mms-tts-<language>).")
        language: str = Field(default="en", title="Language", description="ISO 639-1 or 639-3 code (mms checkpoint / espeak voice).")
        sample_rate: int = Field(default=16000, gt=0, title="Sample rate", description="Output sample rate in Hz (resampled from the model rate).")
        speed: float = Field(default=1.0, gt=0, title="Speed", description="Speaking rate multiplier (1.0 = normal).")
        noise_scale: float = Field(default=0.667, ge=0, title="Noise scale", description="mms: prosody variation (VITS noise scale).")
        output_dir: str = Field(default="workspace/datasets/output/tts", title="Output dir", description="Where synthesized WAV files are written.")

    def process(self, texts=None) -> list[AudioSample]:
        items = _texts(texts) or ([self.config.text.strip()] if self.config.text.strip() else [])
        if not items:
            raise ValueError("SpeechSynthesizerNode: no text — connect the input port or set config.text")
        backend = "mms" if self.config.backend in ("mms", "auto") else "espeak"
        model_id = mms_model_id(self.config.language, self.config.model_name) if backend == "mms" else "espeak-ng"
        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        import soundfile as sf  # type: ignore

        output: list[AudioSample] = []
        files = []
        for i, text in enumerate(items):
            if backend == "mms":
                y, sr = synthesize_mms(text, model_id, speed=self.config.speed,
                                       noise_scale=self.config.noise_scale, seed=int(getattr(self, "seed", 0) or 0) + i)
            else:
                y, sr = self._synthesize_espeak(text)
            if sr != self.config.sample_rate and len(y):
                from math import gcd

                from scipy.signal import resample_poly

                g = gcd(int(sr), int(self.config.sample_rate))
                y = resample_poly(y, int(self.config.sample_rate) // g, int(sr) // g).astype(np.float32)
                sr = int(self.config.sample_rate)
            path = out_dir / f"synth_{i:04d}.wav"
            sf.write(str(path), y, sr)
            files.append(path.name)
            output.append(AudioSample(
                path=str(path), sample_rate=sr, data=y.astype(np.float32), label="synthesized",
                metadata={"speech_synthesizer": {
                    "backend": backend, "model": model_id, "text": text[:200],
                    "language": self.config.language, "duration_s": round(len(y) / sr, 3),
                }, "transcript": text},
            ))
        try:
            self.publish_files(out_dir, files, total=len(files))
        except Exception:
            pass
        return output

    def _synthesize_espeak(self, text: str) -> tuple[np.ndarray, int]:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name
        cmd = ["espeak-ng", "-v", self.config.language, "-s", str(int(175 * self.config.speed)), "-w", out_path, text]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except FileNotFoundError as exc:
            Path(out_path).unlink(missing_ok=True)
            raise RuntimeError(
                "SpeechSynthesizerNode: backend='espeak' needs the 'espeak-ng' binary on this host "
                "(apt-get install espeak-ng). Use backend='mms' otherwise.") from exc
        except subprocess.TimeoutExpired as exc:
            Path(out_path).unlink(missing_ok=True)
            raise RuntimeError(f"SpeechSynthesizerNode: espeak-ng timed out for {text[:50]!r}") from exc
        try:
            if result.returncode != 0:
                raise RuntimeError(f"SpeechSynthesizerNode: espeak-ng failed: {result.stderr.strip()}")
            import soundfile as sf  # type: ignore

            y, sr = sf.read(out_path, dtype="float32", always_2d=True)
        finally:
            Path(out_path).unlink(missing_ok=True)
        return y[:, 0], int(sr)
