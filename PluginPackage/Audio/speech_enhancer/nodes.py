"""SpeechEnhancerNode — speech cleanup: denoising, dereverberation, vocal isolation.

Backends (denoise):
    spectral    — noisereduce spectral gating (CPU) [default]
    speechbrain — SpeechBrain SepFormer trained for enhancement on WHAM! (16 kHz)
    auto        — speechbrain when installed, else spectral

Dereverberation uses single-channel WPE (nara-wpe) in the STFT domain.

Optional telephony_mode applies a 300 Hz–3400 Hz bandpass after enhancement.
"""
from __future__ import annotations

import copy
import logging
from typing import ClassVar, Literal
from pydantic import Field

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)


_SB_MODELS: dict = {}


def _resample(y: np.ndarray, sr: int, target: int) -> np.ndarray:
    if int(sr) == int(target):
        return y.astype(np.float32, copy=False)
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(int(sr), int(target))
    return resample_poly(y, int(target) // g, int(sr) // g).astype(np.float32)


def _load_sepformer_enh():
    if "sepformer" not in _SB_MODELS:
        import os
        from pathlib import Path

        from speechbrain.inference.separation import SepformerSeparation  # type: ignore

        base = os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
        _SB_MODELS["sepformer"] = SepformerSeparation.from_hparams(
            source="speechbrain/sepformer-wham16k-enhancement",
            savedir=str(Path(base) / "speechbrain" / "sepformer-wham16k-enhancement"))
    return _SB_MODELS["sepformer"]


class SpeechEnhancerNode(Node):
    """Speech cleanup: denoising, dereverberation, and vocal isolation.

    Config:
        backend (str): "spectral" | "speechbrain" | "auto" (denoising engine)
        denoise (bool): apply noise reduction (default True)
        dereverb (bool): WPE dereverberation (nara-wpe; default False)
        vocal_isolation (bool): keep the harmonic part (librosa HPSS)
        telephony_mode (bool): 300–3400 Hz bandpass after enhancement
        stationary_noise (bool): stationary noise model for spectral gating
        prop_decrease (float): spectral gating strength (0–1)
    """

    node_type: ClassVar[str] = "speech_enhancer"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="speech_enhancer",
        label="Speech Enhancer",
        description=(
            "Speech cleanup: denoising (noisereduce spectral gating or SpeechBrain "
            "SepFormer-WHAM), WPE dereverberation, vocal isolation, telephony bandpass."
        ),
        category="Enhancement",
        version="2.0.0",
        tags=["audio", "enhancement", "denoising", "dereverberation", "speech"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=False,
        cacheable=True,
        streaming_support=False,
        realtime_support=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="Audio samples to enhance",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Enhanced audio samples",
        )
    }

    class Config(NodeConfig):
        backend: Literal["spectral", "speechbrain", "auto"] = Field(default='spectral', title="Backend", description="Denoiser: spectral (noisereduce gating), speechbrain (SepFormer-WHAM neural, 16 kHz), auto (speechbrain when installed, else spectral).")
        denoise: bool = Field(default=True, title="Denoise", description="Apply noise reduction / spectral gating (On/Off).")
        dereverb: bool = Field(default=False, title="Dereverb", description="Apply dereverberation when the backend supports it (On/Off).")
        vocal_isolation: bool = Field(default=False, title="Vocal Isolation", description="Enable vocal isolation.")
        telephony_mode: bool = Field(default=False, title="Telephony Mode", description="Enable telephony mode.")
        stationary_noise: bool = Field(default=True, title="Stationary Noise", description="Enable stationary noise.")
        prop_decrease: float = Field(default=0.75, title="Prop decrease", description="Noise reduction strength for spectral gating (0–1).")

    # ── setup: resolve backend once ──────────────────────────────────────────

    def setup(self) -> None:
        self._resolved_backend = self._resolve_backend()
        log.debug("SpeechEnhancerNode: using backend '%s'", self._resolved_backend)
        # Pre-load DeepFilterNet model once to avoid reloading on every process() call
        self._sb_model = None
        if self._resolved_backend == "speechbrain" and self.config.denoise:
            self._sb_model = _load_sepformer_enh()

    def _resolve_backend(self) -> str:
        if self.config.backend == "speechbrain":
            try:
                import speechbrain  # type: ignore  # noqa: F401
            except ImportError as exc:
                raise ImportError(
                    "SpeechEnhancerNode: backend='speechbrain' needs speechbrain + torch in this plugin's venv"
                ) from exc
            return "speechbrain"
        if self.config.backend == "auto":
            try:
                import speechbrain  # type: ignore  # noqa: F401
                return "speechbrain"
            except ImportError:
                pass
        try:
            import noisereduce  # type: ignore  # noqa: F401
        except ImportError as exc:
            raise ImportError("SpeechEnhancerNode: 'noisereduce' required for backend='spectral'") from exc
        return "spectral"

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        if not hasattr(self, "_resolved_backend"):
            raise RuntimeError(
                "SpeechEnhancerNode.setup() must be called before process(). "
                "The NodeExecutor calls setup() automatically — do not call process() directly."
            )
        backend = self._resolved_backend
        output: list[AudioSample] = []

        for sample in samples:
            if sample.data is None or sample.data.size == 0:
                log.warning(
                    "SpeechEnhancerNode: skipping zero-length sample %s",
                    getattr(sample, "path", "<unknown>"),
                )
                output.append(sample)
                continue

            new_sample = copy.deepcopy(sample)
            y = new_sample.data.astype(np.float32)
            # Mix stereo/multi-channel to mono — all backends expect 1-D input
            if y.ndim > 1:
                y = y.mean(axis=1)
            sr = new_sample.sample_rate

            ops_applied: list[str] = []

            if self.config.denoise:
                if backend == "speechbrain":
                    y = self._denoise_speechbrain(y, sr)
                else:
                    y = self._denoise_spectral(y, sr)
                ops_applied.append("denoise")

            if self.config.dereverb:
                y = self._dereverb_wpe(y, sr)
                ops_applied.append("dereverb")

            if self.config.vocal_isolation:
                y = self._vocal_isolation(y, sr)
                ops_applied.append("vocal_isolation")

            if self.config.telephony_mode:
                y = self._telephony_bandpass(y, sr)
                ops_applied.append("telephony_bandpass")

            # np.array (not astype) so subclasses such as numpy.memmap — which
            # the spectral denoiser returns for chunked signals — become plain
            # arrays that can cross the isolated-runtime boundary.
            new_sample.data = np.array(y, dtype=np.float32)
            new_sample.metadata.update({
                "speech_enhancer": {
                    "backend": backend,
                    "ops": ops_applied,
                    "prop_decrease": self.config.prop_decrease,
                }
            })
            output.append(new_sample)

        return output

    # ── spectral denoising ────────────────────────────────────────────────────

    def _denoise_spectral(self, y: np.ndarray, sr: int) -> np.ndarray:
        import noisereduce as nr  # type: ignore
        return nr.reduce_noise(
            y=y,
            sr=sr,
            stationary=self.config.stationary_noise,
            prop_decrease=self.config.prop_decrease,
        ).astype(np.float32)

    # ── SpeechBrain SepFormer (WHAM!) enhancement ─────────────────────────────

    def _denoise_speechbrain(self, y: np.ndarray, sr: int) -> np.ndarray:
        import torch  # type: ignore

        model = getattr(self, "_sb_model", None) or _load_sepformer_enh()
        self._sb_model = model
        y_in = _resample(y, sr, 16000)
        with torch.inference_mode():
            est = model.separate_batch(torch.from_numpy(y_in).unsqueeze(0))[0, :, 0]
        out = est.detach().cpu().numpy().astype(np.float32)[: len(y_in)]
        # The separator's output gain/polarity is arbitrary: match the input's
        # polarity and loudness so downstream levels stay comparable.
        n = min(len(out), len(y_in))
        if np.dot(out[:n], y_in[:n]) < 0:
            out = -out
        rms_in, rms_out = float(np.sqrt(np.mean(y_in ** 2))), float(np.sqrt(np.mean(out ** 2)))
        if rms_out > 1e-9:
            out = out * (rms_in / rms_out)
        return _resample(out, 16000, sr)[: len(y)]

    # ── WPE dereverberation ───────────────────────────────────────────────────

    def _dereverb_wpe(self, y: np.ndarray, sr: int) -> np.ndarray:
        """Single-channel Weighted Prediction Error dereverberation (nara-wpe).

        STFT 512/128 (at 16 kHz-equivalent scale), 10 taps, delay 3,
        3 iterations — the nara-wpe reference settings."""
        try:
            from nara_wpe.utils import istft, stft  # type: ignore
            from nara_wpe.wpe import wpe  # type: ignore
        except ImportError as exc:
            raise ImportError("SpeechEnhancerNode: dereverb needs 'nara-wpe' in this plugin's venv") from exc
        size, shift = 512, 128
        Y = stft(y[np.newaxis, :], size=size, shift=shift)  # (D=1, T, F)
        Y = Y.transpose(2, 0, 1)  # (F, D, T)
        Z = wpe(Y, taps=10, delay=3, iterations=3, statistics_mode="full")
        z = istft(Z.transpose(1, 2, 0), size=size, shift=shift)[0]
        out = np.zeros_like(y)
        n = min(len(y), len(z))
        out[:n] = z[:n]
        return out.astype(np.float32)

    # ── vocal isolation ───────────────────────────────────────────────────────

    def _vocal_isolation(self, y: np.ndarray, sr: int) -> np.ndarray:
        """Suppress non-speech frequencies via harmonic-percussive separation.

        Keeps the harmonic component (speech/vocals) and discards the
        percussive component (noise, transients).
        """
        import librosa  # type: ignore
        y_harmonic, _ = librosa.effects.hpss(y)
        return y_harmonic.astype(np.float32)

    # ── telephony bandpass ────────────────────────────────────────────────────

    def _telephony_bandpass(self, y: np.ndarray, sr: int) -> np.ndarray:
        """Apply 300 Hz–3400 Hz bandpass filter (ITU-T G.712 telephony band)."""
        from scipy.signal import butter, sosfilt  # type: ignore
        nyq = sr / 2.0
        low = 300.0 / nyq
        high = min(3400.0 / nyq, 0.999)
        if low >= 1.0 or low >= high:
            log.warning(
                "SpeechEnhancerNode: sample rate %d Hz too low for telephony "
                "bandpass (300–3400 Hz) — skipping filter",
                sr,
            )
            return y
        sos = butter(4, [low, high], btype="band", output="sos")
        return sosfilt(sos, y).astype(np.float32)
