"""SpeechEnhancerNode — speech cleanup: denoising, dereverberation, vocal isolation.

Backends:
    spectral    — noisereduce (CPU, no GPU required)
    deepfilter  — deepfilternet (GPU recommended, CPU fallback)
    auto        — try deepfilter, fall back to spectral

Optional telephony_mode applies a 300 Hz–3400 Hz bandpass after enhancement.
"""
from __future__ import annotations

import copy
import logging
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)


class SpeechEnhancerNode(Node):
    """Speech cleanup: denoising, dereverberation, and vocal isolation.

    Config:
        backend (str): "spectral" | "deepfilter" | "auto"
            spectral   — noisereduce spectral subtraction (CPU only)
            deepfilter — DeepFilterNet neural enhancement (GPU recommended)
            auto       — try deepfilter, fall back to spectral
        denoise (bool): apply noise reduction (default True)
        dereverb (bool): apply dereverberation (default False)
            spectral backend: Wiener-filter-based dereverberation via scipy
            deepfilter backend: uses DF model's built-in dereverberation
        vocal_isolation (bool): isolate vocals by suppressing non-speech
            frequencies (spectral masking, default False)
        telephony_mode (bool): apply 300 Hz–3400 Hz bandpass after enhancement
            to simulate telephony channel (default False)
        stationary_noise (bool): assume stationary noise for spectral backend
            (default True — faster; False = non-stationary, slower but better)
        prop_decrease (float): noise reduction strength for spectral backend
            0.0 = no reduction, 1.0 = full reduction (default 0.75)

    Note on ``dereverb``:
        spectral backend: applies a 5-sample Wiener smoothing filter — this is
        a noise-smoothing approximation, not a full WPE dereverberation algorithm.
        For production-grade dereverberation consider: pip install nara-wpe
        deepfilter backend: same Wiener post-processing step (DeepFilterNet's
        enhance() does not perform dereverberation natively).
    """

    node_type: ClassVar[str] = "speech_enhancer"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="speech_enhancer",
        label="Speech Enhancer",
        description=(
            "Speech cleanup: denoising (spectral subtraction or DeepFilterNet), "
            "dereverberation, vocal isolation, and telephony bandpass."
        ),
        category="Enhancement",
        version="1.0.0",
        tags=["audio", "enhancement", "denoising", "speech", "deepfilter"],
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
        backend: str = "auto"           # "spectral" | "deepfilter" | "auto"
        denoise: bool = True
        dereverb: bool = False
        vocal_isolation: bool = False
        telephony_mode: bool = False    # 300 Hz–3400 Hz bandpass
        stationary_noise: bool = True   # spectral backend: stationary vs non-stationary
        prop_decrease: float = 0.75     # spectral backend: noise reduction strength [0,1]

    # ── setup: resolve backend once ──────────────────────────────────────────

    def setup(self) -> None:
        self._resolved_backend = self._resolve_backend()
        log.debug("SpeechEnhancerNode: using backend '%s'", self._resolved_backend)
        # Pre-load DeepFilterNet model once to avoid reloading on every process() call
        self._df_model = None
        self._df_state = None
        if self._resolved_backend == "deepfilter":
            try:
                from df import init_df  # type: ignore
                self._df_model, self._df_state, _ = init_df()
                log.info("SpeechEnhancerNode: DeepFilterNet model loaded")
            except ImportError:
                pass  # already handled by _resolve_backend

    def _resolve_backend(self) -> str:
        if self.config.backend == "deepfilter":
            try:
                import df  # type: ignore  # noqa: F401
                return "deepfilter"
            except ImportError:
                raise ImportError(
                    "SpeechEnhancerNode: 'deepfilternet' required for backend='deepfilter'. "
                    "Install with: pip install deepfilternet>=0.5"
                )
        if self.config.backend == "spectral":
            try:
                import noisereduce  # type: ignore  # noqa: F401
                return "spectral"
            except ImportError:
                raise ImportError(
                    "SpeechEnhancerNode: 'noisereduce' required for backend='spectral'. "
                    "Install with: pip install noisereduce>=3.0"
                )
        # auto: try deepfilter first, fall back to spectral
        try:
            import df  # type: ignore  # noqa: F401
            return "deepfilter"
        except ImportError:
            pass
        try:
            import noisereduce  # type: ignore  # noqa: F401
            return "spectral"
        except ImportError:
            raise ImportError(
                "SpeechEnhancerNode: no enhancement backend available. "
                "Install at least one: pip install noisereduce>=3.0  "
                "or pip install deepfilternet>=0.5"
            )

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
                if backend == "deepfilter":
                    y = self._denoise_deepfilter(y, sr)
                else:
                    y = self._denoise_spectral(y, sr)
                ops_applied.append("denoise")

            if self.config.dereverb:
                if backend == "deepfilter":
                    # DeepFilterNet's enhance() is primarily a denoising function and
                    # does not perform dereverberation. Apply spectral dereverberation
                    # as a post-processing step instead.
                    y = self._dereverb_spectral(y, sr)
                else:
                    y = self._dereverb_spectral(y, sr)
                ops_applied.append("dereverb")

            if self.config.vocal_isolation:
                y = self._vocal_isolation(y, sr)
                ops_applied.append("vocal_isolation")

            if self.config.telephony_mode:
                y = self._telephony_bandpass(y, sr)
                ops_applied.append("telephony_bandpass")

            new_sample.data = y.astype(np.float32)
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

    # ── DeepFilterNet denoising ───────────────────────────────────────────────

    def _denoise_deepfilter(self, y: np.ndarray, sr: int) -> np.ndarray:
        """Denoise using DeepFilterNet (df package). Uses cached model from setup()."""
        import torch  # type: ignore
        from df import enhance, init_df  # type: ignore

        # Use cached model if available, otherwise load now (fallback for direct calls)
        if getattr(self, "_df_model", None) is not None:
            model = self._df_model
            df_state = self._df_state
        else:
            model, df_state, _ = init_df()

        # DeepFilterNet expects 48 kHz; resample if needed
        target_sr = df_state.sr()
        if sr != target_sr:
            import librosa  # type: ignore
            y_in = librosa.resample(y=y, orig_sr=sr, target_sr=target_sr)
        else:
            y_in = y

        audio_tensor = torch.from_numpy(y_in).unsqueeze(0)  # (1, N)
        enhanced = enhance(model, df_state, audio_tensor)
        y_out = enhanced.squeeze(0).detach().cpu().numpy()

        # Resample back to original sr if needed
        if sr != target_sr:
            import librosa  # type: ignore
            y_out = librosa.resample(y=y_out, orig_sr=target_sr, target_sr=sr)

        return y_out.astype(np.float32)

    # ── spectral dereverberation ──────────────────────────────────────────────

    def _dereverb_spectral(self, y: np.ndarray, sr: int) -> np.ndarray:
        """Simplified dereverberation via Wiener filter smoothing.

        NOTE: This is a spectral smoothing approximation (5-sample Wiener filter),
        not a full WPE (Weighted Prediction Error) dereverberation algorithm.
        It suppresses some late-reverb energy but will not fully remove room
        reverberation. For production-grade dereverberation, consider using
        the nara-wpe library: pip install nara-wpe
        """
        from scipy.signal import wiener  # type: ignore
        return wiener(y, mysize=5).astype(np.float32)

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
