"""SegmenterNode — semantic audio segmentation.

Supports fixed-window, silence-based, VAD, event, and speaker_turn modes.
Migrated and expanded from app/core/nodes/audio/segment.py.
"""
from __future__ import annotations

import copy
import logging
from typing import ClassVar, Literal
from pydantic import Field

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
        "speaker_turn" — offline diarization (or upstream speaker_segments)

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
            "VAD, energy-event detection, and speaker turns (offline diarization)."
        ),
        category="Processing",
        version="1.2.0",
        tags=["audio", "segmentation", "vad", "preprocessing", "event", "diarization"],
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
        mode: Literal["fixed", "silence", "vad", "event", "speaker_turn"] = Field(default='fixed', title="Mode", description="How clips are cut. fixed = sliding windows; silence = split on silent gaps (a clip can yield several segments); vad = voice-activity detection (falls back to silence when unavailable); event = energy onsets; speaker_turn = who-spoke-when: uses upstream speaker segments when present, otherwise runs offline diarization (speaker embeddings + clustering).")
        window_ms: int = Field(default=1000, title="Window (ms)", description="Window length in milliseconds (fixed mode). Clips shorter than one window are emitted whole.")
        overlap: float = Field(default=0.0, title="Overlap", description="Fractional overlap in [0, 1). fixed: window overlap; silence/vad: each segment end is extended by this fraction of its length.")
        vad_aggressiveness: int = Field(default=2, title="VAD aggressiveness", description="Voice-activity detector strictness 0-3 (higher = filters out more non-speech).")
        silence_threshold_db: float = Field(default=40.0, gt=0, le=120, title="Silence threshold (dB below peak)", description="Frames quieter than (clip peak minus this many dB) count as silence. Higher = less audio treated as silence. Used by silence mode and the vad / speaker-turn fallbacks.")
        event_threshold_db: float = Field(default=-30.0, le=0, title="Event threshold (dB re peak)", description="Event mode: frames whose RMS is at least this many dB relative to the loudest frame (<= 0) are active.")
        event_min_gap_ms: int = Field(default=200, title="Event min gap (ms)", description="Event mode: an event ends after this much continuous inactivity (milliseconds).")
        min_segment_ms: int = Field(default=100, title="Min segment (ms)", description="Discard segments shorter than this (milliseconds). Must be < max_segment_ms.")
        num_speakers: int = Field(default=0, ge=0, le=16, title="Speakers", description="speaker_turn: number of speakers in the recording. Set it when known (most accurate); 0 = estimate automatically, which can over-split a single voice.")
        max_speakers: int = Field(default=4, ge=1, le=16, title="Max speakers", description="speaker_turn: upper bound when detecting the number of speakers automatically.")
        diarization_window_ms: int = Field(default=1500, ge=250, le=10000, title="Speaker window (ms)", description="speaker_turn: analysis window per speaker decision (milliseconds).")
        diarization_hop_ms: int = Field(default=750, ge=100, le=10000, title="Speaker hop (ms)", description="speaker_turn: step between analysis windows (milliseconds).")
        max_segment_ms: int = Field(default=30000, title="Max segment (ms)", description="Hard cap on segment length (milliseconds); longer spans are split into max-length chunks.")

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

    def _bounded_spans(self, start: int, end: int, sr: int) -> list[tuple[int, int]]:
        """Split [start, end) into chunks <= max_segment_ms; drop chunks < min_segment_ms."""
        min_s = int(sr * self.config.min_segment_ms / 1000)
        max_s = max(1, int(sr * self.config.max_segment_ms / 1000))
        spans: list[tuple[int, int]] = []
        pos = start
        while pos < end:
            stop = min(pos + max_s, end)
            if stop - pos >= min_s:
                spans.append((pos, stop))
            pos = stop
        return spans

    def _emit_intervals(
        self,
        s: AudioSample,
        intervals: list[tuple[int, int]],
        extra_meta: dict | None = None,
    ) -> list[AudioSample]:
        y = s.data
        sr = s.sample_rate
        segments: list[AudioSample] = []
        seg_id = 0
        for start_sample, end_sample in intervals:
            end_sample = min(int(end_sample), len(y))
            for a, b in self._bounded_spans(int(start_sample), end_sample, sr):
                segments.append(self._make_segment(s, y[a:b], a, b, seg_id, extra_meta))
                seg_id += 1
        return segments

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
            # Short clips (e.g. speech-commands ~0.6s) should still flow
            # downstream rather than emptying the pipeline.
            log.warning(
                "SegmenterNode: sample %s (%d samples) shorter than window "
                "(%d samples) — emitting whole clip as one segment",
                s.path, len(y), window_size,
            )
            if len(y) == 0:
                return []
            return self._emit_intervals(s, [(0, len(y))])

        intervals = [
            (i, i + window_size)
            for i in range(0, len(y) - window_size + 1, step)
        ]
        return self._emit_intervals(s, intervals)

    # ── silence-based segmentation ────────────────────────────────────────────

    def _segment_silence(self, s: AudioSample) -> list[AudioSample]:
        y = s.data
        sr = s.sample_rate

        intervals = librosa.effects.split(y, top_db=self.config.silence_threshold_db)
        intervals = self._apply_overlap_merge(
            [(int(a), int(b)) for a, b in intervals], sr
        )
        return self._emit_intervals(s, intervals)

    # ── VAD segmentation ──────────────────────────────────────────────────────

    def _segment_vad(self, s: AudioSample) -> list[AudioSample]:
        try:
            import webrtcvad  # type: ignore
        except ImportError:
            log.warning(
                "SegmenterNode: webrtcvad not installed — falling back to silence mode. "
                "Install with: pip install webrtcvad>=2.0"
            )
            return self._segment_silence(s)

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
        return self._emit_intervals(s, intervals)

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
        sample_intervals = [
            (frame_start * hop, min(frame_end * hop + frame_len, len(y)))
            for frame_start, frame_end in intervals
        ]
        return self._emit_intervals(
            s, sample_intervals, extra_meta={"event_threshold_db": threshold_db}
        )

    # ── speaker_turn: offline diarization ─────────────────────────────────────

    def _segment_speaker_turn(self, s: AudioSample) -> list[AudioSample]:
        """Speaker-turn segmentation (F19 / F-17).

        * Upstream diarization wins: ``metadata["speaker_segments"]`` (e.g. from
          speaker_separator) is used as-is.
        * Otherwise a real offline diarizer runs on the clip:
          speech regions (silence split) → overlapping windows → per-window
          speaker embedding (MFCC c1..c19 mean/std + delta std + YIN pitch stats,
          CMVN-normalised)
          → agglomerative clustering (cosine, average linkage; number of
          speakers fixed by ``num_speakers`` or picked by silhouette up to
          ``max_speakers``) → per-frame majority vote → contiguous turns.
        """
        speaker_segments = s.metadata.get("speaker_segments")
        if speaker_segments:
            return self._emit_speaker_segments(s, speaker_segments, source="upstream")
        turns, info = diarize_turns(
            np.asarray(s.data, dtype=np.float32),
            int(s.sample_rate),
            top_db=float(self.config.silence_threshold_db),
            window_s=self.config.diarization_window_ms / 1000.0,
            hop_s=self.config.diarization_hop_ms / 1000.0,
            num_speakers=int(self.config.num_speakers),
            max_speakers=int(self.config.max_speakers),
        )
        return self._emit_speaker_segments(s, turns, source="offline", info=info)

    def _emit_speaker_segments(
        self, s: AudioSample, speaker_segments: list, *, source: str, info: dict | None = None
    ) -> list[AudioSample]:
        y = s.data
        sr = s.sample_rate
        segments: list[AudioSample] = []
        seg_id = 0
        for turn_idx, seg in enumerate(speaker_segments):
            start_s = float(seg.get("start", 0))
            end_s = float(seg.get("end", len(y) / sr))
            speaker_id = seg.get("speaker_id", "unknown")
            start_sample = int(start_s * sr)
            end_sample = min(int(end_s * sr), len(y))
            extra = {"speaker_id": speaker_id, "turn_index": turn_idx, "diarization": source}
            if info:
                extra["diarization_info"] = info
            for a, b in self._bounded_spans(start_sample, end_sample, sr):
                segments.append(self._make_segment(s, y[a:b], a, b, seg_id, extra_meta=extra))
                seg_id += 1
        return segments


# ── offline diarization (no network, no model download) ──────────────────────


def _speaker_embeddings(y: np.ndarray, sr: int, spans: list[tuple[int, int]]) -> np.ndarray:
    feats = []
    for a, b in spans:
        chunk = y[a:b]
        mfcc = librosa.feature.mfcc(y=chunk, sr=sr, n_mfcc=20, n_fft=512, hop_length=160)
        mfcc = mfcc[1:]  # drop c0 (loudness)
        delta = librosa.feature.delta(mfcc, width=3) if mfcc.shape[1] >= 3 else np.zeros_like(mfcc)
        try:
            f0 = librosa.yin(chunk, fmin=60, fmax=400, sr=sr, frame_length=1024, hop_length=160)
            voiced = f0[(f0 > 61) & (f0 < 399)]
            pitch = np.array([np.log(np.median(voiced)) if voiced.size else 0.0,
                              np.std(np.log(voiced)) if voiced.size > 1 else 0.0])
        except Exception:
            pitch = np.zeros(2)
        feats.append(np.concatenate([mfcc.mean(axis=1), mfcc.std(axis=1), delta.std(axis=1), pitch * 3.0]))
    return np.asarray(feats, dtype=np.float64)


def _normalise(raw: np.ndarray) -> np.ndarray:
    if len(raw) < 2:
        return raw
    return (raw - raw.mean(axis=0)) / (raw.std(axis=0) + 1e-8)


def _fisher_separation(raw: np.ndarray, labels: np.ndarray) -> float:
    """Mean per-dimension Fisher ratio between the two largest clusters (raw,
    un-normalised MFCC means + pitch) — an absolute 'are these different
    voices' check that per-file normalisation cannot inflate."""
    ids, counts = np.unique(labels, return_counts=True)
    if len(ids) < 2:
        return 0.0
    a_id, b_id = ids[np.argsort(-counts)[:2]]
    cols = list(range(0, 19)) + [raw.shape[1] - 2]  # MFCC means + log-f0
    a, b = raw[labels == a_id][:, cols], raw[labels == b_id][:, cols]
    if len(a) < 2 or len(b) < 2:
        return float("inf")  # cannot test; keep the split
    scale = np.ones(len(cols))
    scale[-1] = 20.0 / 3.0  # pitch column was pre-scaled ×3; weight like one MFCC band
    diff = ((a.mean(axis=0) - b.mean(axis=0)) * scale) ** 2
    var = (a.var(axis=0) + b.var(axis=0)) * scale**2 + 1e-6
    return float(np.mean(diff / var))


def _cluster(raw: np.ndarray, num_speakers: int, max_speakers: int) -> tuple[np.ndarray, dict]:
    X = _normalise(raw)
    from scipy.cluster.hierarchy import fcluster, linkage

    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    n = len(X)
    if n < 2 or np.allclose(X, X[0]) or np.any(np.linalg.norm(X, axis=1) < 1e-9):
        return np.zeros(n, dtype=int), {"k": 1, "selection": "single_window"}
    Z = linkage(X, method="average", metric="cosine")
    if num_speakers > 0:
        k = min(num_speakers, n)
        return fcluster(Z, k, criterion="maxclust") - 1, {"k": k, "selection": "num_speakers"}
    from sklearn.metrics import silhouette_score  # sklearn is in the base image

    scored: list[tuple[int, float, np.ndarray]] = []
    for k in range(2, min(max_speakers, n - 1) + 1):
        labels = fcluster(Z, k, criterion="maxclust") - 1
        if len(set(labels)) < 2:
            continue
        scored.append((k, float(silhouette_score(X, labels, metric="cosine")), labels))
    best_k, best_score, best_labels = 1, -1.0, np.zeros(n, dtype=int)
    if scored:
        top = max(sc for _, sc, _ in scored)
        # Parsimony: the fewest speakers whose separation is within 0.05 of the best.
        best_k, best_score, best_labels = next(t for t in scored if t[1] >= top - 0.05)
    two = next((lab for k, _, lab in scored if k == 2), None)
    fisher = _fisher_separation(raw, two) if two is not None else 0.0
    info = {"selection": "silhouette+fisher", "best_silhouette": round(best_score, 3),
            "fisher_separation": round(fisher, 3) if np.isfinite(fisher) else None}
    # Weak separation → a single speaker (do not invent turns).
    if best_score < 0.12 or fisher < 1.0:
        return np.zeros(n, dtype=int), {"k": 1, **info}
    return best_labels, {"k": best_k, **info}


def diarize_turns(
    y: np.ndarray,
    sr: int,
    *,
    top_db: float = 40.0,
    window_s: float = 1.5,
    hop_s: float = 0.75,
    num_speakers: int = 0,
    max_speakers: int = 4,
) -> tuple[list[dict], dict]:
    """Offline speaker diarization → ``([{start, end, speaker_id}], info)``."""
    if y.ndim > 1:
        y = y.mean(axis=0) if y.shape[0] < y.shape[-1] else y.mean(axis=1)
    if len(y) == 0 or float(np.max(np.abs(y))) < 1e-4:
        return [], {"k": 0, "windows": 0, "reason": "no audible signal"}
    speech = [(int(a), int(b)) for a, b in librosa.effects.split(y, top_db=top_db)]
    win, hop = max(1, int(window_s * sr)), max(1, int(hop_s * sr))
    spans: list[tuple[int, int]] = []
    for a, b in speech:
        if b - a <= win:
            if b - a >= int(0.25 * sr):
                spans.append((a, b))
            continue
        pos = a
        while pos + win <= b:
            spans.append((pos, pos + win))
            pos += hop
        if b - (pos - hop + win) > int(0.25 * sr):
            spans.append((max(a, b - win), b))
    if not spans:
        return [], {"k": 0, "windows": 0, "speech_regions": len(speech)}
    labels, info = _cluster(_speaker_embeddings(y, sr, spans), num_speakers, max_speakers)
    # Relabel by first appearance → spk0, spk1, …
    order: dict[int, int] = {}
    for lab in labels:
        order.setdefault(int(lab), len(order))
    # Frame-level (10 ms) majority vote across overlapping windows, speech only.
    step = max(1, sr // 100)
    n_frames = len(y) // step + 1
    votes = np.zeros((n_frames, max(1, len(order))), dtype=np.int32)
    for (a, b), lab in zip(spans, labels):
        votes[a // step : b // step + 1, order[int(lab)]] += 1
    in_speech = np.zeros(n_frames, dtype=bool)
    for a, b in speech:
        in_speech[a // step : b // step + 1] = True
    frame_lab = np.where((votes.sum(axis=1) > 0) & in_speech, votes.argmax(axis=1), -1)
    turns: list[dict] = []
    cur, start = -1, 0
    for f in range(n_frames + 1):
        lab = int(frame_lab[f]) if f < n_frames else -1
        if lab != cur:
            if cur >= 0:
                turns.append({"start": start * step / sr, "end": min(f * step, len(y)) / sr,
                              "speaker_id": f"spk{cur}"})
            cur, start = lab, f
    info.update({"windows": len(spans), "speech_regions": len(speech),
                 "method": "mfcc_pitch_stats+agglomerative_cosine"})
    return turns, info
