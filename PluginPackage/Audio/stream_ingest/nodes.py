"""StreamIngestNode — real-time streaming audio ingestion.

Supports microphone capture (sounddevice), WebSocket streams (websockets),
and file-based streaming (librosa) for testing without hardware.
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


class StreamIngestNode(Node):
    """Real-time streaming audio ingestion from microphone, WebSocket, and file streams.

    source options:
        "microphone"   — capture ``duration_s`` seconds from a local audio device
                         (requires ``sounddevice``)
        "websocket"    — connect to ``websocket_url`` and receive ``buffer_size``
                         chunks of raw float32 PCM bytes (requires ``websockets``)
        "file_stream"  — stream a local audio file in ``chunk_ms`` chunks via
                         librosa; useful for testing without hardware

    Config:
        source (str): ingestion backend (default "microphone")
        device_id (int): microphone device index (default 0)
        websocket_url (str): WebSocket URL for source="websocket"
        file_path (str): local audio file path for source="file_stream"
        chunk_ms (int): chunk size in milliseconds (default 100)
        sample_rate (int): target sample rate in Hz (default 16000)
        channels (int): number of capture channels (default 1)
        buffer_size (int): number of chunks to buffer before returning (default 10)
        duration_s (float): total capture duration for microphone/file_stream (default 5.0)
        label (str): label to attach to every produced AudioSample (default "")
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="stream_ingest",
        label="Stream Ingest",
        description="Real-time streaming audio ingestion from microphone, WebSocket, and file streams.",
        category="Input",
        version="1.0.0",
        tags=["audio", "streaming", "realtime", "input"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=False,
        cacheable=False,
        streaming_support=True,
        realtime_support=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {}  # source node — no inputs

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Streaming audio chunks as AudioSample objects",
        )
    }

    class Config(NodeConfig):
        source: str = "microphone"      # "microphone" | "websocket" | "file_stream"
        device_id: int = 0
        websocket_url: str = ""         # WebSocket URL for source="websocket"
        file_path: str = ""             # local file path for source="file_stream"
        chunk_ms: int = 100
        sample_rate: int = 16000
        channels: int = 1
        buffer_size: int = 10           # number of chunks to buffer before returning
        duration_s: float = 5.0        # total capture duration (microphone/file_stream)
        label: str = ""

    # ── process (multi-port / source node signature) ──────────────────────────

    def process(self, inputs: dict) -> dict:
        """Source node — multi-port signature (no input ports)."""
        source = self.config.source

        if source == "microphone":
            chunks = self._capture_microphone()
        elif source == "websocket":
            chunks = self._capture_websocket()
        elif source == "file_stream":
            chunks = self._stream_file()
        elif source in ("rtp", "rtsp"):
            raise NotImplementedError(
                f"StreamIngestNode: source='{source}' (RTP/RTSP) is not yet implemented. "
                "Use source='file_stream' for testing or source='websocket' for live streams."
            )
        else:
            raise ValueError(
                f"StreamIngestNode: unknown source '{source}'. "
                "Choose from: microphone, websocket, file_stream"
            )

        return {"output": chunks}

    # ── microphone backend ────────────────────────────────────────────────────

    def _capture_microphone(self) -> list[AudioSample]:
        """Capture ``duration_s`` seconds from a local microphone via sounddevice."""
        try:
            import sounddevice as sd
        except ImportError:
            raise ImportError(
                "StreamIngestNode: 'sounddevice' required for source='microphone'. "
                "Install with: pip install sounddevice"
            )

        sr = self.config.sample_rate
        duration = self.config.duration_s
        channels = self.config.channels
        device = self.config.device_id

        log.info("StreamIngestNode: recording %.1fs from device %d...", duration, device)
        recording = sd.rec(
            int(duration * sr),
            samplerate=sr,
            channels=channels,
            device=device,
            dtype="float32",
        )
        sd.wait()

        # Convert to mono if needed
        if channels > 1:
            data = recording.mean(axis=1)
        else:
            data = recording.flatten()

        # Split into chunks of chunk_ms
        chunk_samples = int(sr * self.config.chunk_ms / 1000)
        chunks: list[AudioSample] = []
        for i in range(0, len(data) - chunk_samples + 1, chunk_samples):
            chunk = data[i:i + chunk_samples]
            chunks.append(AudioSample(
                path="microphone",
                sample_rate=sr,
                data=chunk.astype(np.float32),
                label=self.config.label,
                metadata={
                    "source": "microphone",
                    "device_id": device,
                    "chunk_index": len(chunks),
                    "start_s": i / sr,
                    "end_s": (i + chunk_samples) / sr,
                },
            ))
        return chunks

    # ── file_stream backend ───────────────────────────────────────────────────

    def _stream_file(self) -> list[AudioSample]:
        """Stream a local audio file in chunk_ms chunks via librosa.

        Uses ``file_path`` config field. Falls back to ``websocket_url`` for
        backward compatibility with older configs.
        Useful for testing without a microphone.
        """
        import librosa

        file_path = self.config.file_path or self.config.websocket_url
        if not file_path:
            raise ValueError(
                "StreamIngestNode: 'file_path' must be set when source='file_stream'"
            )

        sr_target = self.config.sample_rate
        duration = self.config.duration_s

        log.info("StreamIngestNode: streaming file '%s' at %d Hz", file_path, sr_target)

        # Load the file (resample to target sample rate)
        y, sr = librosa.load(file_path, sr=sr_target, mono=True, duration=duration)

        chunk_samples = int(sr * self.config.chunk_ms / 1000)
        chunks: list[AudioSample] = []

        for i in range(0, len(y) - chunk_samples + 1, chunk_samples):
            chunk = y[i:i + chunk_samples]
            chunks.append(AudioSample(
                path=file_path,
                sample_rate=sr,
                data=chunk.astype(np.float32),
                label=self.config.label,
                metadata={
                    "source": "file_stream",
                    "file_path": file_path,
                    "chunk_index": len(chunks),
                    "start_s": i / sr,
                    "end_s": (i + chunk_samples) / sr,
                },
            ))

        return chunks

    # ── websocket backend ─────────────────────────────────────────────────────

    def _capture_websocket(self) -> list[AudioSample]:
        """Connect to a WebSocket URL and receive ``buffer_size`` chunks of raw float32 PCM.

        Each WebSocket message is expected to be raw float32 PCM bytes at
        ``sample_rate`` Hz (mono). Receives exactly ``buffer_size`` messages
        then closes the connection.
        """
        try:
            import asyncio
            import websockets  # type: ignore
        except ImportError:
            raise ImportError(
                "StreamIngestNode: 'websockets' required for source='websocket'. "
                "Install with: pip install websockets"
            )

        url = self.config.websocket_url
        if not url:
            raise ValueError(
                "StreamIngestNode: 'websocket_url' must be set when source='websocket'"
            )

        sr = self.config.sample_rate
        buffer_size = self.config.buffer_size
        label = self.config.label

        async def _receive() -> list[AudioSample]:
            chunks: list[AudioSample] = []
            async with websockets.connect(url) as ws:
                for chunk_index in range(buffer_size):
                    try:
                        message = await ws.recv()
                    except websockets.exceptions.ConnectionClosed:
                        log.warning(
                            "StreamIngestNode: WebSocket connection closed after %d chunks",
                            chunk_index,
                        )
                        break

                    # Decode raw float32 PCM bytes
                    if isinstance(message, bytes):
                        data = np.frombuffer(message, dtype=np.float32).copy()
                    else:
                        # Text frame — try to parse as comma-separated floats
                        try:
                            data = np.array(
                                [float(x) for x in message.split(",")],
                                dtype=np.float32,
                            )
                        except ValueError:
                            log.warning(
                                "StreamIngestNode: could not parse text frame as float32, skipping"
                            )
                            continue

                    chunk_duration = len(data) / sr if sr > 0 else 0.0
                    chunks.append(AudioSample(
                        path=url,
                        sample_rate=sr,
                        data=data,
                        label=label,
                        metadata={
                            "source": "websocket",
                            "websocket_url": url,
                            "chunk_index": chunk_index,
                            "chunk_duration_s": chunk_duration,
                        },
                    ))
            return chunks

        return asyncio.run(_receive())
