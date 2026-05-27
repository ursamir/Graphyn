from __future__ import annotations

import logging
from typing import ClassVar

import librosa
import numpy as np
from pydantic import field_validator

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample
from app.models.feature_array import FeatureArray

log = logging.getLogger(__name__)


class FeatureFrontendNode(Node):
    """
    Unified audio feature extraction frontend.

    Supported feature types:
    - log_mel       — log-mel spectrogram
    - mfcc          — Mel-frequency cepstral coefficients (+ optional delta/delta-delta)
    - spectrogram   — magnitude spectrogram (linear or log scale)
    - chroma        — chroma STFT
    - zcr           — zero-crossing rate (1-D time series)
    - spectral_centroid  — spectral centroid (1-D time series)
    - spectral_rolloff   — spectral rolloff (1-D time series)
    - raw           — waveform passthrough as FeatureArray (for SSL models)
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="feature_frontend",
        label="Feature Frontend",
        description=(
            "Unified audio feature extraction frontend for ML pipelines. "
            "Supports log-mel, MFCC (+ delta), ZCR, spectral features, "
            "chroma, and raw waveform passthrough."
        ),
        category="Features",
        version="1.1.0",
        tags=[
            "audio",
            "features",
            "spectrogram",
            "mfcc",
            "ml",
            "frontend",
            "ssl",
            "delta",
        ],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
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
            description="Input audio samples",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[FeatureArray],
            description="Extracted feature arrays",
        )
    }

    _VALID_FEATURE_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "log_mel",
            "mfcc",
            "spectrogram",
            "chroma",
            "zcr",
            "spectral_centroid",
            "spectral_rolloff",
            "raw",
        }
    )

    class Config(NodeConfig):
        feature_type: str = "log_mel"
        # Supported: "log_mel" | "mfcc" | "spectrogram" | "chroma"
        #            | "zcr" | "spectral_centroid" | "spectral_rolloff" | "raw"

        @field_validator("feature_type")
        @classmethod
        def _check_feature_type(cls, v: str) -> str:
            normalized = v.lower()
            valid = {
                "log_mel",
                "mfcc",
                "spectrogram",
                "chroma",
                "zcr",
                "spectral_centroid",
                "spectral_rolloff",
                "raw",
            }
            if normalized not in valid:
                raise ValueError(
                    f"feature_type must be one of {sorted(valid)}, got '{v}'"
                )
            return normalized

        sample_rate: int = 16000

        fixed_length: int = 0
        # 0 = variable length (default); N = pad/truncate time axis to exactly N frames.
        # Use this in inference pipelines to match the fixed input shape the model was
        # trained with (e.g. fixed_length=101 for a 1-second clip at 16kHz/hop=160).

        n_fft: int = 512
        hop_length: int = 160
        win_length: int = 400

        n_mels: int = 80
        n_mfcc: int = 13

        fmin: float = 0.0
        fmax: float | None = None

        log_scale: bool = True

        normalize: bool = True

        center: bool = True

        # Delta / delta-delta (applies to mfcc; also stacked onto log_mel if set)
        delta: bool = False
        delta_delta: bool = False

    # ── normalization ─────────────────────────────────────────────────────────

    def _normalize(self, x: np.ndarray) -> np.ndarray:
        mean = np.mean(x)
        std = np.std(x)
        if std <= 1e-8:
            return x
        return (x - mean) / std

    # ── feature extractors ────────────────────────────────────────────────────

    def _extract_log_mel(self, y: np.ndarray, sr: int) -> np.ndarray:
        mel = librosa.feature.melspectrogram(
            y=y,
            sr=sr,
            n_fft=self.config.n_fft,
            hop_length=self.config.hop_length,
            win_length=self.config.win_length,
            n_mels=self.config.n_mels,
            fmin=self.config.fmin,
            fmax=self.config.fmax,
            center=self.config.center,
        )
        features = librosa.power_to_db(mel, ref=np.max).astype(np.float32)

        if self.config.delta or self.config.delta_delta:
            features = self._append_deltas(features)

        return features

    def _extract_mfcc(self, y: np.ndarray, sr: int) -> np.ndarray:
        mfcc = librosa.feature.mfcc(
            y=y,
            sr=sr,
            n_mfcc=self.config.n_mfcc,
            n_fft=self.config.n_fft,
            hop_length=self.config.hop_length,
            win_length=self.config.win_length,
            n_mels=self.config.n_mels,
        ).astype(np.float32)

        if self.config.delta or self.config.delta_delta:
            mfcc = self._append_deltas(mfcc)

        return mfcc

    def _append_deltas(self, features: np.ndarray) -> np.ndarray:
        """Stack delta and/or delta-delta onto the feature matrix (axis 0).

        delta=True  only       → appends delta1
        delta_delta=True only  → appends delta2 (without delta1)
        both True              → appends delta1 then delta2

        delta2 is always computed as delta(delta1), i.e. the standard
        delta-delta definition, NOT librosa.feature.delta(features, order=2).
        """
        parts = [features]
        # Always compute d1 when delta_delta is requested (needed as input to d2)
        d1 = librosa.feature.delta(features).astype(np.float32)
        if self.config.delta:
            parts.append(d1)
        if self.config.delta_delta:
            # Standard delta-delta: delta of delta (not second-order of original)
            d2 = librosa.feature.delta(d1).astype(np.float32)
            parts.append(d2)
        return np.concatenate(parts, axis=0)

    def _extract_spectrogram(self, y: np.ndarray) -> np.ndarray:
        spec = np.abs(
            librosa.stft(
                y,
                n_fft=self.config.n_fft,
                hop_length=self.config.hop_length,
                win_length=self.config.win_length,
                center=self.config.center,
            )
        )
        if self.config.log_scale:
            spec = librosa.amplitude_to_db(spec, ref=np.max)
        return spec.astype(np.float32)

    def _extract_chroma(self, y: np.ndarray, sr: int) -> np.ndarray:
        return librosa.feature.chroma_stft(
            y=y,
            sr=sr,
            n_fft=self.config.n_fft,
            hop_length=self.config.hop_length,
        ).astype(np.float32)

    def _extract_zcr(self, y: np.ndarray) -> np.ndarray:
        """Zero-crossing rate — shape (1, T)."""
        zcr = librosa.feature.zero_crossing_rate(
            y,
            frame_length=self.config.win_length,
            hop_length=self.config.hop_length,
            center=self.config.center,
        )
        return zcr.astype(np.float32)  # shape (1, T)

    def _extract_spectral_centroid(self, y: np.ndarray, sr: int) -> np.ndarray:
        """Spectral centroid — shape (1, T)."""
        centroid = librosa.feature.spectral_centroid(
            y=y,
            sr=sr,
            n_fft=self.config.n_fft,
            hop_length=self.config.hop_length,
            win_length=self.config.win_length,
            center=self.config.center,
        )
        return centroid.astype(np.float32)  # shape (1, T)

    def _extract_spectral_rolloff(self, y: np.ndarray, sr: int) -> np.ndarray:
        """Spectral rolloff — shape (1, T)."""
        rolloff = librosa.feature.spectral_rolloff(
            y=y,
            sr=sr,
            n_fft=self.config.n_fft,
            hop_length=self.config.hop_length,
            win_length=self.config.win_length,
            center=self.config.center,
        )
        return rolloff.astype(np.float32)  # shape (1, T)

    def _extract_raw(self, y: np.ndarray) -> np.ndarray:
        """Raw waveform passthrough — shape (1, N) for SSL model compatibility."""
        return y[np.newaxis, :].astype(np.float32)

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, samples: list[AudioSample]) -> list[FeatureArray]:
        outputs: list[FeatureArray] = []

        for sample in samples:
            # Finding 1: guard against None or empty data
            if sample.data is None or len(sample.data) == 0:
                log.warning(
                    "FeatureFrontendNode: skipping sample with empty/None data: %s",
                    sample.path,
                )
                continue

            y = sample.data.astype(np.float32)
            sr = sample.sample_rate

            # Finding 2: guard against invalid sample_rate before librosa.resample
            if not sr or sr <= 0:
                raise ValueError(
                    f"FeatureFrontendNode: invalid sample_rate={sr} for sample '{sample.path}'"
                )

            if sr != self.config.sample_rate:
                y = librosa.resample(
                    y=y,
                    orig_sr=sr,
                    target_sr=self.config.sample_rate,
                )
                sr = self.config.sample_rate

            feature_type = self.config.feature_type.lower()

            if feature_type == "log_mel":
                features = self._extract_log_mel(y, sr)
            elif feature_type == "mfcc":
                features = self._extract_mfcc(y, sr)
            elif feature_type == "spectrogram":
                features = self._extract_spectrogram(y)
            elif feature_type == "chroma":
                features = self._extract_chroma(y, sr)
            elif feature_type == "zcr":
                features = self._extract_zcr(y)
            elif feature_type == "spectral_centroid":
                features = self._extract_spectral_centroid(y, sr)
            elif feature_type == "spectral_rolloff":
                features = self._extract_spectral_rolloff(y, sr)
            elif feature_type == "raw":
                features = self._extract_raw(y)
            else:
                raise ValueError(
                    f"FeatureFrontendNode: unsupported feature_type '{self.config.feature_type}'. "
                    "Choose from: log_mel, mfcc, spectrogram, chroma, "
                    "zcr, spectral_centroid, spectral_rolloff, raw"
                )

            if self.config.normalize and feature_type != "raw":
                features = self._normalize(features)

            # Track whether normalization was actually applied (std > 1e-8)
            actually_normalized = (
                self.config.normalize
                and feature_type != "raw"
                and np.std(features) > 1e-8
            )

            # Transpose from (F, T) → (T, F) for downstream compatibility
            # librosa returns (n_features, T); dataset_builder expects (T, n_features)
            if features.ndim == 2:
                features = features.T

            # Pad or truncate time axis to fixed_length if specified
            if self.config.fixed_length > 0 and features.ndim == 2:
                T, F = features.shape
                target = self.config.fixed_length
                if T > target:
                    features = features[:target, :]
                elif T < target:
                    pad = np.zeros((target - T, F), dtype=np.float32)
                    features = np.concatenate([features, pad], axis=0)

            # Build delta suffix for metadata
            delta_suffix = ""
            if self.config.delta and self.config.delta_delta:
                delta_suffix = "+delta+delta2"
            elif self.config.delta:
                delta_suffix = "+delta"
            elif self.config.delta_delta:
                delta_suffix = "+delta2"

            feature_array = FeatureArray(
                data=features,
                feature_type=feature_type + delta_suffix,
                sample_rate=sr,
                source_path=str(sample.path),
                label=sample.label,
                metadata={
                    **sample.metadata,
                    "feature_type": feature_type + delta_suffix,
                    "shape": list(features.shape),
                    "n_fft": self.config.n_fft,
                    "hop_length": self.config.hop_length,
                    "win_length": self.config.win_length,
                    "normalized": actually_normalized,
                    "delta": self.config.delta,
                    "delta_delta": self.config.delta_delta,
                },
            )

            outputs.append(feature_array)

        return outputs
