"""SegmenterNode — semantic audio segmentation.

Supports fixed-window, silence-based, VAD, event, and speaker_turn modes.
Migrated and expanded from app/core/nodes/audio/segment.py.
"""
from __future__ import annotations

import copy
import logging
from typing import ClassVar

import librosa
import numpy as np
import pydantic

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)


class SegmenterNode(Node):
    """Semantic audio segmentation into meaningful chunks.

    Modes:
        "fixed"        — fixed-length windows with optional overlap
        "silence"      — split on silence gaps (librosa.effects.split)
        "vad"          — Voice Activity Detection via webrtcvad
        "event"        — energy-threshold event detection
        "speaker_turn" — placeholder (requires speaker_separator upstream)

    All modes:
    - Filter segments shorter than min_segment_ms or longer than max_segment_ms
    - Support overlap ratio [0, 1) for fixed mode
    - Enrich metadata: parent, start, end, segment_id, segmentation_mode

    Config:
        mode (str): segmentation mode (default "fixed")
        window_ms (int): window size in ms for fixed mode (default 1000)
        overlap (float): overlap ratio [0, 1) for fixed/silence/vad modes (default 0.0)
        vad_aggressiveness (int): webrtcvad aggressiveness 0-3 (default 2)
        silence_threshold_db (float): top_db for silence detection (default 40.0)
        event_threshold_db (float): energy threshold in dB for event mode (default -30.0)
        event_min_gap_ms (int): minimum gap between events in ms (default 200)
        min_segment_ms (int): discard segments shorter than this (default 100)
        max_segment_ms (int): discard segments longer than this (default 30000)
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="segmenter",
        label="Segmenter",
        description=(
            "Semantic audio segmentation: fixed windows, silence-based, "
            "VAD, energy-event detection, and speaker-turn placeholder."
        ),
        category="Processing",
        version="1.1.0",
        tags=["audio", "segmentation", "vad", "preprocessing", "event"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=True,
        realtime_support=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="List of AudioSample objects to segment",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Segmented AudioSample chunks",
        )
    }

    class Config(NodeConfig):
        mode: str = "fixed"              # "fixed" | "silence" | "vad" | "event" | "speaker_turn"
        window_ms: int = 1000
        overlap: float = 0.0            # [0, 1) — applies to fixed, silence, vad
        vad_aggressiveness: int = 2
        silence_threshold_db: float = 40.0
        event_threshold_db: float = -30.0   # dB below peak to consider as event onset
        event_min_gap_ms: int = 200          # minimum silence gap between events
        min_segment_ms: int = 100
        max_segment_ms: int = 30000

        @pydantic.field_validator("overlap")
        @classmethod
        def _overlap_in_range(cls, v: float) -> float:
            if not (0.0 <= v < 1.0):
                raise ValueError(
                    f"overlap must be in [0, 1) — got {v}. "
                    "A value of 1.0 or greater would produce infinite or zero-length steps."
                )
            return v

        @pydantic.field_validator("vad_aggressiveness")
        @classmethod
        def _vad_aggressiveness_range(cls, v: int) -> int:
            if v not in (0, 1, 2, 3):
                raise ValueError(
                    f"vad_aggressiveness must be 0, 1, 2, or 3 — got {v}."
                )
            return v

        @pydantic.field_validator("window_ms", "min_segment_ms", "max_segment_ms", "event_min_gap_ms")
        @classmethod
        def _positive_int(cls, v: int) -> int:
            if v <= 0:
                raise ValueError(f"Value must be > 0, got {v}.")
            return v

        @pydantic.model_validator(mode="after")
        def _min_max_segment_order(self) -> "SegmenterNode.Config":
            if self.min_segment_ms >= self.max_segment_ms:
                raise ValueError(
                    f"min_segment_ms ({self.min_segment_ms}) must be less than "
                    f"max_segment_ms ({self.max_segment_ms})."
                )
            return self

    # ── SISO shorthand ────────────────────────────────────────────────────────

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        mode = self.config.mode
        out: list[AudioSample] = []

        for s in samples:
            if s.data is None or len(s.data) == 0:
                log.warning(
                    "SegmenterNode: skipping zero-length sample %s", s.path
                )
                continue
            if mode == "fixed":
                segments = self._segment_fixed(s)
            elif mode == "silence":
                segments = self._segment_silence(s)
            elif mode == "vad":
                segments = self._segment_vad(s)
            elif mode == "event":
                segments = self._segment_event(s)
            elif mode == "speaker_turn":
                segments = self._segment_speaker_turn(s)
            else:
                raise ValueError(
                    f"SegmenterNode: unknown mode '{mode}'. "
                    "Choose from: fixed, silence, vad, event, speaker_turn"
                )
            out.extend(segments)

        return out

    # ── shared helpers ────────────────────────────────────────────────────────

    def _make_segment(
        self,
        source: AudioSample,
        chunk: np.ndarray,
        start_sample: int,
        end_sample: int,
        seg_id: int,
        extra_meta: dict | None = None,
    ) -> AudioSample:
        sr = source.sample_rate
        meta = {
            **source.metadata,
            "parent": str(source.path),
            "start": start_sample / sr,
            "end": end_sample / sr,
            "segment_id": seg_id,
            "segmentation_mode": self.config.mode,
        }
        if extra_meta:
            meta.update(extra_meta)
        return AudioSample(
            path=source.path,
            sample_rate=sr,
            data=chunk.copy(),
            label=source.label,
            metadata=meta,
        )

    def _within_bounds(self, n_samples: int, sr: int) -> bool:
        min_s = int(sr * self.config.min_segment_ms / 1000)
        max_s = int(sr * self.config.max_segment_ms / 1000)
        return min_s <= n_samples <= max_s

    def _apply_overlap_merge(
        self,
        intervals: list[tuple[int, int]],
        sr: int,
    ) -> list[tuple[int, int]]:
        """Extend each interval end by a fraction of the segment's own length.

        For silence/VAD modes the segment length is content-driven, so overlap
        is computed as a fraction of each segment's actual length rather than
        using the fixed window_ms (which is only meaningful in fixed mode).

        Note: adjacent intervals may overlap after extension, resulting in
        duplicate audio data in the extracted segments. This is intentional
        for overlap-add use cases. Callers clamp the extended end to len(y).
        """
        if self.config.overlap <= 0.0:
            return intervals
        result = []
        for start, end in intervals:
            seg_len = end - start
            overlap_samples = int(seg_len * self.config.overlap)
            result.append((start, end + overlap_samples))
        return result

    # ── fixed-window segmentation ─────────────────────────────────────────────

    def _segment_fixed(self, s: AudioSample) -> list[AudioSample]:
        y = s.data
        sr = s.sample_rate

        window_size = int(sr * self.config.window_ms / 1000)
        step = max(1, int(window_size * (1.0 - self.config.overlap)))

        if len(y) < window_size:
            log.warning(
                "SegmenterNode: sample %s (%d samples) shorter than window "
                "(%d samples) — no segments produced",
                s.path, len(y), window_size,
            )
            return []

        segments: list[AudioSample] = []
        seg_id = 0

        for i in range(0, len(y) - window_size + 1, step):
            chunk = y[i:i + window_size]
            if not self._within_bounds(len(chunk), sr):
                continue
            segments.append(self._make_segment(s, chunk, i, i + window_size, seg_id))
            seg_id += 1

        return segments

    # ── silence-based segmentation ────────────────────────────────────────────

    def _segment_silence(self, s: AudioSample) -> list[AudioSample]:
        y = s.data
        sr = s.sample_rate

        intervals = librosa.effects.split(y, top_db=self.config.silence_threshold_db)
        intervals = self._apply_overlap_merge(
            [(int(a), int(b)) for a, b in intervals], sr
        )

        segments: list[AudioSample] = []
        seg_id = 0

        for start_sample, end_sample in intervals:
            end_sample = min(end_sample, len(y))
            chunk = y[start_sample:end_sample]
            if not self._within_bounds(len(chunk), sr):
                continue
            segments.append(self._make_segment(s, chunk, start_sample, end_sample, seg_id))
            seg_id += 1

        return segments

    # ── VAD segmentation ──────────────────────────────────────────────────────

    def _segment_vad(self, s: AudioSample) -> list[AudioSample]:
        try:
            import webrtcvad  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "SegmenterNode: 'webrtcvad' package required for mode='vad'. "
                "Install with: pip install webrtcvad>=2.0"
            ) from exc

        y = s.data
        sr = s.sample_rate

        VAD_RATES = (8000, 16000, 32000, 48000)
        if sr not in VAD_RATES:
            target_sr = min(VAD_RATES, key=lambda r: abs(r - sr))
            log.info("SegmenterNode: resampling %d → %d Hz for VAD", sr, target_sr)
            y_vad = librosa.resample(y=y, orig_sr=sr, target_sr=target_sr)
            vad_sr = target_sr
        else:
            y_vad = y
            vad_sr = sr

        vad = webrtcvad.Vad(self.config.vad_aggressiveness)
        frame_ms = 30
        frame_samples = int(vad_sr * frame_ms / 1000)
        if y_vad.ndim > 1:
            y_vad = y_vad.mean(axis=1)  # mix stereo/multi-channel to mono for VAD
        y_int16 = np.clip(y_vad * 32767, -32768, 32767).astype(np.int16)
        pcm_bytes = y_int16.tobytes()
        frame_bytes = frame_samples * 2
        n_frames = len(pcm_bytes) // frame_bytes

        is_speech = []
        for i in range(n_frames):
            frame = pcm_bytes[i * frame_bytes:(i + 1) * frame_bytes]
            try:
                speech = vad.is_speech(frame, vad_sr)
            except Exception:
                speech = False
            is_speech.append(speech)

        # Collect speech intervals in original sample rate
        intervals: list[tuple[int, int]] = []
        in_speech = False
        seg_start_frame = 0

        for i, speech in enumerate(is_speech):
            if speech and not in_speech:
                in_speech = True
                seg_start_frame = i
            elif not speech and in_speech:
                in_speech = False
                # Use integer arithmetic to avoid float drift
                start_s = seg_start_frame * frame_samples * sr // vad_sr
                end_s = i * frame_samples * sr // vad_sr
                intervals.append((start_s, end_s))

        if in_speech:
            start_s = seg_start_frame * frame_samples * sr // vad_sr
            intervals.append((start_s, len(y)))

        # Apply overlap extension
        intervals = self._apply_overlap_merge(intervals, sr)

        segments: list[AudioSample] = []
        seg_id = 0
        for start_sample, end_sample in intervals:
            end_sample = min(end_sample, len(y))
            chunk = y[start_sample:end_sample]
            if not self._within_bounds(len(chunk), sr):
                continue
            segments.append(self._make_segment(s, chunk, start_sample, end_sample, seg_id))
            seg_id += 1

        return segments

    # ── event-based segmentation ──────────────────────────────────────────────

    def _segment_event(self, s: AudioSample) -> list[AudioSample]:
        """Energy-threshold event detection.

        Computes short-time RMS energy, finds frames above threshold_db,
        merges consecutive active frames into events, enforces min_gap_ms
        between events, then extracts the corresponding audio chunks.
        """
        y = s.data
        sr = s.sample_rate

        hop = int(sr * 0.010)   # 10ms analysis hop
        frame_len = int(sr * 0.025)  # 25ms analysis frame

        # RMS energy per frame
        rms = librosa.feature.rms(y=y, frame_length=frame_len, hop_length=hop)[0]

        if np.max(rms) < 1e-10:
            log.debug(
                "SegmenterNode: silence-only audio in event mode for %s — no events detected",
                s.path,
            )
            return []

        rms_db = librosa.amplitude_to_db(rms, ref=np.max)

        threshold_db = self.config.event_threshold_db
        min_gap_frames = int(self.config.event_min_gap_ms / 10)  # 10ms per frame

        active = rms_db >= threshold_db

        # Merge consecutive active frames, enforcing min_gap
        intervals: list[tuple[int, int]] = []
        in_event = False
        event_start = 0
        gap_count = 0

        for i, a in enumerate(active):
            if a:
                if not in_event:
                    in_event = True
                    event_start = i
                gap_count = 0
            else:
                if in_event:
                    gap_count += 1
                    if gap_count >= min_gap_frames:
                        intervals.append((event_start, i - gap_count))
                        in_event = False
                        gap_count = 0

        if in_event:
            intervals.append((event_start, len(active)))

        # Convert frame indices → sample indices
        segments: list[AudioSample] = []
        seg_id = 0
        for frame_start, frame_end in intervals:
            start_sample = frame_start * hop
            end_sample = min(frame_end * hop + frame_len, len(y))
            chunk = y[start_sample:end_sample]
            if not self._within_bounds(len(chunk), sr):
                continue
            segments.append(self._make_segment(
                s, chunk, start_sample, end_sample, seg_id,
                extra_meta={"event_threshold_db": threshold_db},
            ))
            seg_id += 1

        return segments

    # ── speaker_turn placeholder ──────────────────────────────────────────────

    def _segment_speaker_turn(self, s: AudioSample) -> list[AudioSample]:
        """Speaker-turn segmentation placeholder.

        Full implementation requires speaker_separator upstream (Phase 4).
        Reads pre-computed speaker segments from metadata["speaker_segments"]
        if available; otherwise falls back to silence-based segmentation with
        a warning.
        """
        speaker_segments = s.metadata.get("speaker_segments")

        if speaker_segments:
            # Use pre-computed diarization from speaker_separator
            y = s.data
            sr = s.sample_rate
            segments: list[AudioSample] = []
            seg_id = 0

            for seg in speaker_segments:
                start_s = float(seg.get("start", 0))
                end_s = float(seg.get("end", len(y) / sr))
                speaker_id = seg.get("speaker_id", "unknown")

                start_sample = int(start_s * sr)
                end_sample = min(int(end_s * sr), len(y))
                chunk = y[start_sample:end_sample]

                if not self._within_bounds(len(chunk), sr):
                    continue

                segments.append(self._make_segment(
                    s, chunk, start_sample, end_sample, seg_id,
                    extra_meta={"speaker_id": speaker_id},
                ))
                seg_id += 1

            return segments
        else:
            log.warning(
                "SegmenterNode: mode='speaker_turn' requires speaker_separator upstream "
                "(Phase 4). No 'speaker_segments' found in metadata — "
                "falling back to silence-based segmentation."
            )
            return self._segment_silence(s)
