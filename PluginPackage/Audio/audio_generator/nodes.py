"""AudioGeneratorNode — generate audio content from text prompts or conditions.

Backends:
    musicgen  — Meta AudioCraft MusicGen (music generation from text)
    audiogen  — Meta AudioCraft AudioGen (general audio/sound effects)
    auto      — musicgen if available, else audiogen
"""
from __future__ import annotations

import logging
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)


class AudioGeneratorNode(Node):
    """Generate audio content from text prompts using AudioCraft models.

    Accepts a list of text prompts (or an empty list for unconditional generation)
    and produces a list of AudioSample objects.

    Config:
        backend (str): "musicgen" | "audiogen" | "auto"
        model_size (str): "small" | "medium" | "large" (default "small")
        duration_s (float): output duration in seconds (default 5.0)
        prompt (str): default prompt when input list is empty
        conditioning_audio (str): path to conditioning audio (melody/style)
        temperature (float): sampling temperature (default 1.0)
        top_k (int): top-k sampling (default 250)
        guidance_scale (float): classifier-free guidance scale (default 3.0)
    """

    node_type: ClassVar[str] = "audio_generator"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="audio_generator",
        label="Audio Generator",
        description=(
            "Generate audio from text prompts using Meta AudioCraft: "
            "MusicGen (music) or AudioGen (sound effects)."
        ),
        category="Generation",
        version="1.0.0",
        tags=["audio", "generation", "musicgen", "audiogen", "audiocraft", "generative"],
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
            data_type=list,
            cardinality="single",
            required=False,
            description="List of text prompts (optional — uses config.prompt if empty)",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Generated AudioSample objects",
        )
    }

    class Config(NodeConfig):
        backend: str = "auto"           # "musicgen" | "audiogen" | "auto"
        model_size: str = "small"       # "small" | "medium" | "large"
        duration_s: float = 5.0
        prompt: str = ""                # default prompt when input is empty
        conditioning_audio: str = ""    # path to melody/style conditioning audio
        temperature: float = 1.0
        top_k: int = 250
        guidance_scale: float = 3.0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def setup(self) -> None:
        """Warn if no GPU is available — AudioCraft is very slow on CPU."""
        try:
            import torch  # type: ignore
            if not torch.cuda.is_available():
                log.warning(
                    "AudioGeneratorNode: no GPU detected. AudioCraft MusicGen/AudioGen "
                    "models are extremely slow on CPU (5s audio may take 10+ minutes). "
                    "A CUDA-capable GPU is strongly recommended."
                )
        except ImportError:
            pass  # torch not installed yet — will raise at generation time

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, prompts: list) -> list[AudioSample]:
        backend = self._resolve_backend()

        # Resolve prompts
        text_prompts = [str(p) for p in prompts if str(p).strip()] if prompts else []
        if not text_prompts:
            if self.config.prompt.strip():
                text_prompts = [self.config.prompt]
            else:
                text_prompts = [""]  # unconditional generation

        if backend == "musicgen":
            return self._generate_musicgen(text_prompts)
        elif backend == "audiogen":
            return self._generate_audiogen(text_prompts)
        else:
            raise ImportError(
                "AudioGeneratorNode: no generation backend available. "
                "Install AudioCraft: pip install audiocraft>=1.0"
            )

    def _resolve_backend(self) -> str:
        if self.config.backend == "musicgen":
            return "musicgen"
        if self.config.backend == "audiogen":
            return "audiogen"
        # auto
        try:
            from audiocraft.models import MusicGen  # type: ignore  # noqa: F401
            return "musicgen"
        except ImportError:
            pass
        try:
            from audiocraft.models import AudioGen  # type: ignore  # noqa: F401
            return "audiogen"
        except ImportError:
            pass
        raise ImportError(
            "AudioGeneratorNode: AudioCraft not installed. "
            "Install with: pip install audiocraft>=1.0"
        )

    # ── MusicGen backend ──────────────────────────────────────────────────────

    def _generate_musicgen(self, prompts: list[str]) -> list[AudioSample]:
        try:
            import torch  # type: ignore
            from audiocraft.models import MusicGen  # type: ignore
        except ImportError:
            raise ImportError(
                "AudioGeneratorNode: 'audiocraft' required for backend='musicgen'. "
                "Install with: pip install audiocraft>=1.0"
            )

        if not hasattr(self, "_musicgen_model"):
            model_name = f"facebook/musicgen-{self.config.model_size}"
            self._musicgen_model = MusicGen.get_pretrained(model_name)

        model = self._musicgen_model
        model.set_generation_params(
            duration=self.config.duration_s,
            temperature=self.config.temperature,
            top_k=self.config.top_k,
            cfg_coef=self.config.guidance_scale,
        )

        # Melody conditioning
        melody_wavs = None
        if self.config.conditioning_audio:
            from pathlib import Path
            if Path(self.config.conditioning_audio).exists():
                try:
                    import soundfile as sf  # type: ignore
                except ImportError:
                    raise ImportError(
                        "AudioGeneratorNode: 'soundfile' required for conditioning_audio. "
                        "Install with: pip install soundfile>=0.12"
                    )
                mel_data, mel_sr = sf.read(self.config.conditioning_audio, dtype="float32")
                melody_wavs = torch.from_numpy(mel_data).unsqueeze(0).unsqueeze(0)

        with torch.no_grad():
            if melody_wavs is not None:
                wav = model.generate_with_chroma(prompts, melody_wavs, mel_sr)
            else:
                wav = model.generate(prompts)

        sr = model.sample_rate
        return self._tensors_to_samples(wav, sr, prompts)

    # ── AudioGen backend ──────────────────────────────────────────────────────

    def _generate_audiogen(self, prompts: list[str]) -> list[AudioSample]:
        try:
            import torch  # type: ignore
            from audiocraft.models import AudioGen  # type: ignore
        except ImportError:
            raise ImportError(
                "AudioGeneratorNode: 'audiocraft' required for backend='audiogen'. "
                "Install with: pip install audiocraft>=1.0"
            )

        if not hasattr(self, "_audiogen_model"):
            model_name = f"facebook/audiogen-{self.config.model_size}"
            self._audiogen_model = AudioGen.get_pretrained(model_name)

        model = self._audiogen_model
        model.set_generation_params(
            duration=self.config.duration_s,
            temperature=self.config.temperature,
            top_k=self.config.top_k,
            cfg_coef=self.config.guidance_scale,
        )

        with torch.no_grad():
            wav = model.generate(prompts)

        sr = model.sample_rate
        return self._tensors_to_samples(wav, sr, prompts)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _tensors_to_samples(self, wav, sr: int, prompts: list[str]) -> list[AudioSample]:
        """Convert AudioCraft output tensors to AudioSample list."""
        results: list[AudioSample] = []
        for i, audio in enumerate(wav):
            y = audio.squeeze().cpu().numpy().astype(np.float32)
            prompt_text = prompts[i] if i < len(prompts) else ""
            results.append(AudioSample(
                path=f"generated_{i}.wav",
                sample_rate=sr,
                data=y,
                label="generated",
                metadata={
                    "audio_generator": {
                        "backend": self.config.backend,
                        "model_size": self.config.model_size,
                        "prompt": prompt_text[:100],
                        "duration_s": self.config.duration_s,
                        "temperature": self.config.temperature,
                    }
                },
            ))
        return results
