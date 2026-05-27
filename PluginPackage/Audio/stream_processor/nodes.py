"""StreamProcessorNode — rolling window buffering for streaming audio pipelines.

Manages a rolling window with configurable size and hop, overlap-add
reconstruction, latency monitoring, and buffer health management.
"""
from __future__ import annotations

import collections
import logging
import time
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)


class StreamProcessorNode(Node):
    """Rolling window processor for streaming audio pipelines.

    Accepts a stream of AudioSample chunks, buffers them into a rolling
    window of configurable size and hop, and emits windowed chunks for
    downstream processing.

    Config:
        window_ms (int): window size in milliseconds (default 1000)
        hop_ms (int): hop size in milliseconds; overlap = window - hop (default 500)
        target_latency_ms (int): warn if actual latency exceeds this (default 200)
        max_buffer_size (int): max queued chunks; oldest dropped when full (default 100)
        sample_rate (int): expected sample rate of incoming chunks (default 16000)
        overlap_add (bool): apply overlap-add reconstruction (default False)
    """

    node_type: ClassVar[str] = "stream_processor"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="stream_processor",
        label="Stream Processor",
        description=(
            "Rolling window buffering for streaming audio: configurable window/hop, "
            "overlap-add reconstruction, latency monitoring, buffer health."
        ),
        category="Streaming",
        version="1.0.0",
        tags=["audio", "streaming", "realtime", "windowing", "buffer"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
        streaming_support=True,
        realtime_support=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="Streaming audio chunks",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Windowed audio chunks",
        )
    }

    class Config(NodeConfig):
        window_ms: int = 1000
        hop_ms: int = 500
        target_latency_ms: int = 200
        max_buffer_size: int = 100
        sample_rate: int = 16000
        overlap_add: bool = False

    def __init__(self, config=None, seed: int = 0, observer=None):
        super().__init__(config=config, seed=seed, observer=observer)

    def setup(self) -> None:
        """Initialise streaming state so it is reset between pipeline runs."""
        self._buffer: collections.deque = collections.deque()
        self._sample_buffer: np.ndarray = np.array([], dtype=np.float32)
        self._last_process_time: float = 0.0

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, chunks: list[AudioSample]) -> list[AudioSample]:
        # Guard: setup() may not have been called when instantiated directly
        if not hasattr(self, "_buffer"):
            self.setup()

        sr = self.config.sample_rate
        window_samples = int(sr * self.config.window_ms / 1000)
        hop_samples = int(sr * self.config.hop_ms / 1000)

        # Buffer health: drop oldest if over limit
        for chunk in chunks:
            if len(self._buffer) >= self.config.max_buffer_size:
                dropped = self._buffer.popleft()
                log.warning(
                    "StreamProcessorNode: buffer full (%d) — dropped chunk from %s",
                    self.config.max_buffer_size, dropped.path,
                )
            self._buffer.append(chunk)

        t_start = time.monotonic()

        # Concatenate buffered samples; mono-mix stereo to avoid 2D window slices
        def _to_mono(arr: np.ndarray) -> np.ndarray:
            a = arr.astype(np.float32)
            return a.mean(axis=1) if a.ndim > 1 else a

        all_data = np.concatenate(
            [_to_mono(c.data) for c in self._buffer]
        ) if self._buffer else np.array([], dtype=np.float32)

        # Prepend any leftover from previous call
        if len(self._sample_buffer) > 0:
            all_data = np.concatenate([self._sample_buffer, all_data])

        # Emit windows
        output: list[AudioSample] = []
        pos = 0
        window_idx = 0

        # Use the first chunk's metadata as template (O(1) deque access)
        template = self._buffer[0] if self._buffer else None

        while pos + window_samples <= len(all_data):
            window = all_data[pos:pos + window_samples]

            if self.config.overlap_add:
                window = self._apply_hann(window)

            meta = dict(template.metadata) if template else {}
            meta.update({
                "stream_processor": {
                    "window_idx": window_idx,
                    "start_sample": pos,
                    "end_sample": pos + window_samples,
                    "window_ms": self.config.window_ms,
                    "hop_ms": self.config.hop_ms,
                }
            })

            output.append(AudioSample(
                path=template.path if template else "",
                sample_rate=sr,
                data=window.copy(),
                label=template.label if template else "",
                metadata=meta,
            ))

            pos += hop_samples
            window_idx += 1

        # Keep leftover samples for next call
        self._sample_buffer = all_data[pos:].copy() if pos < len(all_data) else np.array([], dtype=np.float32)

        # Clear processed chunks from buffer
        self._buffer.clear()

        # Latency check
        elapsed_ms = (time.monotonic() - t_start) * 1000
        if elapsed_ms > self.config.target_latency_ms:
            log.warning(
                "StreamProcessorNode: processing latency %.1f ms exceeds target %d ms",
                elapsed_ms, self.config.target_latency_ms,
            )

        return output

    def _apply_hann(self, window: np.ndarray) -> np.ndarray:
        """Apply Hann window for overlap-add reconstruction."""
        hann = np.hanning(len(window)).astype(np.float32)
        return (window * hann).astype(np.float32)
