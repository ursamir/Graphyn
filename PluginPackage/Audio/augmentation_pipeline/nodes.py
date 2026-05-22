"""AugmentationPipelineNode — orchestrated probabilistic audio augmentation.

Consolidates all 5 augmentation nodes from augment.py into a single
configurable pipeline: gain, pitch_shift, time_stretch, speed_perturb,
reverb, noise_inject, codec_degrade, eq, and audiomentations passthrough.

Phase 6 additions:
    codec_degrade  — simulate MP3/Opus codec degradation via soundfile + io
    eq             — parametric EQ via scipy IIR peaking filters
    audiomentations — any audiomentations transform via config dict
"""
from __future__ import annotations

import copy
import io
import logging
import os
from typing import Any, ClassVar

import librosa
import numpy as np
import scipy.signal

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)


class AugmentationPipelineNode(Node):
    """Orchestrated probabilistic audio augmentation pipeline.

    For each input sample the original is always preserved. Then for each
    copy (1..copies_per_sample) each augmentation in the list is applied
    independently with probability apply_prob.

    Supported augmentation types:
        "gain"         — random gain in gain_db range
        "pitch_shift"  — librosa pitch shift in semitones range
        "time_stretch" — librosa time stretch in rate range
        "speed_perturb"— resample to sr*factor then back to sr
        "reverb"       — convolve with random IR from impulse_response_path dir
        "noise_inject" — add Gaussian noise at target SNR

    Config:
        copies_per_sample (int): augmented copies per input sample (default 1)
        augmentations (list): list of augmentation dicts, each with:
            type (str): augmentation type
            apply_prob (float): probability of applying this augmentation [0,1]
            ... type-specific params (see above)
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="augmentation_pipeline",
        label="Augmentation Pipeline",
        description="Orchestrated probabilistic audio augmentation pipeline: gain, pitch, stretch, reverb, noise, codec, EQ, audiomentations.",
        category="Augmentation",
        version="1.1.0",
        tags=["audio", "augmentation", "training", "data", "codec", "eq", "audiomentations"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=False,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="List of AudioSample objects to augment",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Original + augmented AudioSample objects",
        )
    }

    class Config(NodeConfig):
        copies_per_sample: int = 1
        augmentations: list = [
            {"type": "gain", "apply_prob": 0.5, "gain_db": [-6, 6]},
            {"type": "pitch_shift", "apply_prob": 0.3, "semitones": [-2, 2]},
            {"type": "time_stretch", "apply_prob": 0.3, "rate": [0.9, 1.1]},
            {"type": "speed_perturb", "apply_prob": 0.3, "speed_factor": [0.9, 1.1]},
            {"type": "codec_degrade", "apply_prob": 0.2, "codec": "mp3", "bitrate": 32},
            {"type": "eq", "apply_prob": 0.2, "bands": [{"freq": 1000, "gain_db": 3, "q": 1.0}]},
        ]

    def __init__(self, config=None, seed: int = 0, observer=None):
        super().__init__(config=config, seed=seed, observer=observer)
        # seed=0 by default → reproducible augmentation sequence.
        # Pass a different seed per node instance to get independent sequences.
        self.rng = np.random.default_rng(seed)

    # ── SISO shorthand ────────────────────────────────────────────────────────

    def process(self, samples):
        """Augment each input sample; always include the original."""
        out: list[AudioSample] = []

        for s in samples:
            # Always include the original
            out.append(copy.deepcopy(s))

            # Generate copies_per_sample augmented versions
            for copy_idx in range(self.config.copies_per_sample):
                augmented = copy.deepcopy(s)
                applied: list[str] = []

                for aug_cfg in self.config.augmentations:
                    aug_type = aug_cfg.get("type", "")
                    apply_prob = float(aug_cfg.get("apply_prob", 0.5))

                    if self.rng.random() >= apply_prob:
                        continue  # skip this augmentation

                    try:
                        augmented, aug_name = self._apply_augmentation(
                            augmented, aug_cfg
                        )
                        applied.append(aug_name)
                    except Exception as exc:
                        log.warning(
                            "AugmentationPipelineNode: augmentation '%s' failed: %s",
                            aug_type, exc,
                        )

                augmented.metadata = {
                    **augmented.metadata,
                    "augmented": True,
                    "augmentations_applied": applied,
                    "augmentation_copy": copy_idx,
                }
                out.append(augmented)

        return out

    # ── augmentation dispatch ─────────────────────────────────────────────────

    def _apply_augmentation(
        self,
        s: AudioSample,
        aug_cfg: dict[str, Any],
    ) -> tuple[AudioSample, str]:
        """Apply a single augmentation; return (modified_sample, aug_name)."""
        aug_type = aug_cfg.get("type", "")

        if aug_type == "gain":
            return self._aug_gain(s, aug_cfg), "gain"
        elif aug_type == "pitch_shift":
            return self._aug_pitch_shift(s, aug_cfg), "pitch_shift"
        elif aug_type == "time_stretch":
            return self._aug_time_stretch(s, aug_cfg), "time_stretch"
        elif aug_type == "speed_perturb":
            return self._aug_speed_perturb(s, aug_cfg), "speed_perturb"
        elif aug_type == "reverb":
            return self._aug_reverb(s, aug_cfg), "reverb"
        elif aug_type == "noise_inject":
            return self._aug_noise_inject(s, aug_cfg), "noise_inject"
        elif aug_type == "codec_degrade":
            return self._aug_codec_degrade(s, aug_cfg), "codec_degrade"
        elif aug_type == "eq":
            return self._aug_eq(s, aug_cfg), "eq"
        elif aug_type == "audiomentations":
            return self._aug_audiomentations(s, aug_cfg), "audiomentations"
        else:
            log.warning(
                "AugmentationPipelineNode: unknown augmentation type '%s', skipping",
                aug_type,
            )
            return s, aug_type

    # ── gain ──────────────────────────────────────────────────────────────────

    def _aug_gain(self, s: AudioSample, cfg: dict) -> AudioSample:
        """Random gain in gain_db range → 10^(gain/20) * y."""
        gain_range = cfg.get("gain_db", [-6, 6])
        gain_db = float(self.rng.uniform(gain_range[0], gain_range[1]))
        factor = 10 ** (gain_db / 20.0)
        s.data = (s.data * factor).astype(np.float32)
        s.metadata["gain_db"] = gain_db
        return s

    # ── pitch shift ───────────────────────────────────────────────────────────

    def _aug_pitch_shift(self, s: AudioSample, cfg: dict) -> AudioSample:
        """librosa.effects.pitch_shift with random semitones."""
        semitones_range = cfg.get("semitones", [-2, 2])
        n_steps = float(self.rng.uniform(semitones_range[0], semitones_range[1]))
        s.data = librosa.effects.pitch_shift(
            y=s.data, sr=s.sample_rate, n_steps=n_steps
        ).astype(np.float32)
        s.metadata["pitch_shift_semitones"] = n_steps
        return s

    # ── time stretch ──────────────────────────────────────────────────────────

    def _aug_time_stretch(self, s: AudioSample, cfg: dict) -> AudioSample:
        """librosa.effects.time_stretch with random rate.

        NOTE: time_stretch changes the audio length (rate < 1 → longer,
        rate > 1 → shorter). Use dataset_builder.fixed_length downstream
        to normalise lengths before building ML datasets.
        """
        rate_range = cfg.get("rate", [0.9, 1.1])
        rate = float(self.rng.uniform(rate_range[0], rate_range[1]))
        s.data = librosa.effects.time_stretch(y=s.data, rate=rate).astype(np.float32)
        s.metadata["time_stretch_rate"] = rate
        return s

    # ── speed perturbation ────────────────────────────────────────────────────

    def _aug_speed_perturb(self, s: AudioSample, cfg: dict) -> AudioSample:
        """Resample to sr*factor then back to sr (changes duration and pitch)."""
        speed_range = cfg.get("speed_factor", [0.9, 1.1])
        factor = float(self.rng.uniform(speed_range[0], speed_range[1]))
        orig_sr = s.sample_rate
        target_sr = int(orig_sr * factor)

        resampled = librosa.resample(y=s.data, orig_sr=orig_sr, target_sr=target_sr)
        perturbed = librosa.resample(y=resampled, orig_sr=target_sr, target_sr=orig_sr)

        s.data = perturbed.astype(np.float32)
        s.metadata["speed_factor"] = factor
        return s

    # ── reverb ────────────────────────────────────────────────────────────────

    def _aug_reverb(self, s: AudioSample, cfg: dict) -> AudioSample:
        """Convolve with a random IR from impulse_response_path dir.

        Skips silently if impulse_response_path is empty or not found.
        """
        ir_dir = cfg.get("impulse_response_path", "")
        if not ir_dir or not os.path.isdir(ir_dir):
            log.debug(
                "AugmentationPipelineNode: reverb skipped — "
                "impulse_response_path '%s' not found or empty", ir_dir
            )
            return s

        wav_files = sorted(
            os.path.join(ir_dir, f)
            for f in os.listdir(ir_dir)
            if f.lower().endswith(".wav")
        )
        if not wav_files:
            log.debug(
                "AugmentationPipelineNode: reverb skipped — no .wav files in '%s'", ir_dir
            )
            return s

        ir_path = wav_files[int(self.rng.integers(0, len(wav_files)))]
        ir_data, _ = librosa.load(ir_path, sr=s.sample_rate, mono=True)

        convolved = scipy.signal.fftconvolve(s.data, ir_data, mode="full")
        convolved = convolved[: len(s.data)]
        peak = float(np.abs(convolved).max())
        if peak > 1e-6:
            convolved = convolved / peak

        s.data = convolved.astype(np.float32)
        s.metadata["impulse_response"] = os.path.basename(ir_path)
        return s

    # ── noise injection ───────────────────────────────────────────────────────

    def _aug_noise_inject(self, s: AudioSample, cfg: dict) -> AudioSample:
        """Add Gaussian noise at a target SNR (dB)."""
        snr_range = cfg.get("snr_db", [5, 20])
        snr_db = float(self.rng.uniform(snr_range[0], snr_range[1]))

        signal_power = float(np.mean(s.data ** 2))
        if signal_power < 1e-10:
            return s  # silent signal — skip

        snr_linear = 10 ** (snr_db / 10.0)
        noise_power = signal_power / snr_linear
        noise = self.rng.normal(0.0, np.sqrt(noise_power), size=s.data.shape).astype(np.float32)

        s.data = (s.data + noise).astype(np.float32)
        s.metadata["noise_snr_db"] = snr_db
        return s

    # ── codec degradation ─────────────────────────────────────────────────────

    def _aug_codec_degrade(self, s: AudioSample, cfg: dict) -> AudioSample:
        """Simulate codec degradation by encoding to MP3/Ogg and decoding back.

        Uses soundfile for encoding (requires libsndfile with codec support)
        or falls back to a simple low-pass filter approximation.
        """
        codec = cfg.get("codec", "mp3").lower()
        bitrate = int(cfg.get("bitrate", 32))

        # soundfile supports OGG/Vorbis natively; true MP3 encoding requires
        # libsndfile with MPEG support (rarely available). We use OGG as a proxy
        # for all lossy codec simulation and warn the user when mp3 is requested.
        if codec == "mp3":
            log.warning(
                "AugmentationPipelineNode: codec_degrade codec='mp3' — "
                "soundfile does not support MP3 encoding natively. "
                "Using OGG/Vorbis as a lossy codec proxy. "
                "For true MP3 simulation install pydub+ffmpeg."
            )

        try:
            import soundfile as sf  # type: ignore

            buf = io.BytesIO()
            # soundfile supports OGG/Vorbis natively; MP3 requires libsndfile with MPEG
            fmt = "OGG" if codec in ("mp3", "ogg", "opus") else "WAV"
            subtype = "VORBIS" if fmt == "OGG" else "PCM_16"

            sf.write(buf, s.data, s.sample_rate, format=fmt, subtype=subtype)
            buf.seek(0)
            y_decoded, _ = sf.read(buf, dtype="float32")

            if y_decoded.ndim > 1:
                y_decoded = y_decoded[:, 0]

            # Trim/pad to original length
            if len(y_decoded) > len(s.data):
                y_decoded = y_decoded[:len(s.data)]
            elif len(y_decoded) < len(s.data):
                y_decoded = np.pad(y_decoded, (0, len(s.data) - len(y_decoded)))

            s.data = y_decoded.astype(np.float32)

        except Exception:
            # Fallback: low-pass filter to simulate bandwidth reduction
            # Lower bitrate → lower cutoff frequency
            cutoff_hz = max(1000.0, bitrate * 40.0)  # rough approximation
            nyq = s.sample_rate / 2.0
            cutoff_norm = min(cutoff_hz / nyq, 0.99)
            sos = scipy.signal.butter(4, cutoff_norm, btype="low", output="sos")
            s.data = scipy.signal.sosfilt(sos, s.data).astype(np.float32)

        s.metadata["codec_degrade"] = {"codec": codec, "bitrate": bitrate}
        return s

    # ── parametric EQ ─────────────────────────────────────────────────────────

    def _aug_eq(self, s: AudioSample, cfg: dict) -> AudioSample:
        """Apply parametric EQ via IIR peaking filters.

        bands: list of {"freq": Hz, "gain_db": dB, "q": Q-factor}
        """
        bands = cfg.get("bands", [])
        y = s.data.copy()
        sr = s.sample_rate
        applied_bands = []

        for band in bands:
            freq = float(band.get("freq", 1000.0))
            gain_db = float(band.get("gain_db", 0.0))
            q = float(band.get("q", 1.0))

            if abs(gain_db) < 0.01:
                continue

            # Design IIR peaking filter (Audio EQ Cookbook)
            w0 = 2 * np.pi * freq / sr
            A = 10 ** (gain_db / 40.0)
            alpha = np.sin(w0) / (2 * q)

            b0 = 1 + alpha * A
            b1 = -2 * np.cos(w0)
            b2 = 1 - alpha * A
            a0 = 1 + alpha / A
            a1 = -2 * np.cos(w0)
            a2 = 1 - alpha / A

            b = np.array([b0 / a0, b1 / a0, b2 / a0])
            a = np.array([1.0, a1 / a0, a2 / a0])

            y = scipy.signal.lfilter(b, a, y).astype(np.float32)
            applied_bands.append({"freq": freq, "gain_db": gain_db, "q": q})

        s.data = y
        s.metadata["eq_bands"] = applied_bands
        return s

    # ── audiomentations passthrough ───────────────────────────────────────────

    def _aug_audiomentations(self, s: AudioSample, cfg: dict) -> AudioSample:
        """Apply an audiomentations transform.

        cfg must include a "transform" key with the transform class name and
        its parameters, e.g.:
            {"type": "audiomentations", "apply_prob": 0.5,
             "transform": "AddGaussianNoise", "min_amplitude": 0.001, "max_amplitude": 0.015}

        Requires: pip install audiomentations>=0.30
        """
        try:
            import audiomentations  # type: ignore
        except ImportError:
            raise ImportError(
                "AugmentationPipelineNode: 'audiomentations' required for type='audiomentations'. "
                "Install with: pip install audiomentations>=0.30"
            )

        transform_name = cfg.get("transform", "")
        if not transform_name:
            log.warning("AugmentationPipelineNode: audiomentations type missing 'transform' key")
            return s

        transform_cls = getattr(audiomentations, transform_name, None)
        if transform_cls is None:
            raise ValueError(
                f"AugmentationPipelineNode: unknown audiomentations transform '{transform_name}'"
            )

        # Build kwargs from cfg, excluding known non-param keys
        skip_keys = {"type", "apply_prob", "transform"}
        kwargs = {k: v for k, v in cfg.items() if k not in skip_keys}
        kwargs["p"] = 1.0  # always apply (probability already handled by pipeline)

        transform = transform_cls(**kwargs)
        y_aug = transform(samples=s.data, sample_rate=s.sample_rate)
        s.data = y_aug.astype(np.float32)
        s.metadata["audiomentations_transform"] = transform_name
        return s
