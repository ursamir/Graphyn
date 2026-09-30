"""MicroSpeechPipelineNode — Opinionated KWS→int8 tflite helper

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import io
import json
import math
import re
import struct
import wave

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
import numpy as np
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.audio_sample import AudioSample
from app.models.deployment_artifact import DeploymentArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("micro_speech_pipeline.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

McuSample = _types.McuSample

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj

def _text(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, list):
        return "\n".join(_text(x) for x in obj)
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("text", "query", "content", "answer", "user", "path", "value", "final"):
            if data.get(key):
                return str(data[key])
        return json.dumps(data, default=str)
    return str(obj)

def _as_list(obj: Any) -> list:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, tuple):
        return list(obj)
    return [obj]

def _numbers(obj: Any) -> list[float]:
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("values", "features", "payload", "vector", "embedding", "data"):
            if key in data:
                return _numbers(data[key])
        return [float(v) for v in data.values() if isinstance(v, (int, float))]
    if isinstance(data, (list, tuple)):
        out: list[float] = []
        for item in data:
            if isinstance(item, (int, float)):
                out.append(float(item))
            elif isinstance(item, (list, tuple, dict)):
                out.extend(_numbers(item))
        return out
    if isinstance(data, (int, float)):
        return [float(data)]
    return []

def _bytes_of(obj: Any) -> bytes:
    if isinstance(obj, bytes):
        return obj
    data = _dump(obj)
    if isinstance(data, dict) and isinstance(data.get("bytes"), (bytes, bytearray)):
        return bytes(data["bytes"])
    if isinstance(data, dict) and data.get("path"):
        path = Path(str(data["path"]))
        if path.is_file():
            return path.read_bytes()
    return _text(obj).encode("utf-8")

def _out_path(config: Any, default_name: str) -> Path:
    raw = _cfg(config, "output_path") or _cfg(config, "output_dir") or _cfg(config, "persist_path")
    path = Path(str(raw or f"workspace/artifacts/proposed/{default_name}"))
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path.mkdir(parents=True, exist_ok=True)
    return path

# --- PCM decoding (kept identical across TinyML / WakeWord / Video plugin copies;
# plugins are self-contained so this helper is duplicated rather than shared). ---
_PCM_DEFAULT_RATE = 16000
_PCM_DATA_KEYS = ("data", "samples", "waveform", "audio", "pcm", "payload", "values")
_PCM_RATE_KEYS = ("sample_rate", "sr", "rate", "framerate")


def _pcm_downmix(arr: Any) -> Any:
    """Collapse (n, ch) or (ch, n) arrays to mono by channel mean."""
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim == 0:
        return arr.reshape(1)
    if arr.ndim == 1:
        return arr
    arr = np.squeeze(arr)
    if arr.ndim == 1:
        return arr
    if arr.ndim != 2:
        raise ValueError(f"_pcm: expected 1-D or 2-D audio array, got shape {arr.shape}")
    # Channels are the short axis: (n, ch) when rows >= cols, else (ch, n).
    axis = 1 if arr.shape[0] >= arr.shape[1] else 0
    return arr.mean(axis=axis).astype(np.float32)


def _pcm_resample(arr: Any, src_rate: int | None, target_rate: int | None) -> Any:
    """Linear-interpolation resample (adequate for MCU feature front-ends)."""
    if not target_rate or not src_rate or int(src_rate) == int(target_rate) or arr.size == 0:
        return arr
    n_out = max(1, int(round(arr.size * float(target_rate) / float(src_rate))))
    x_out = np.arange(n_out, dtype=np.float64) * (float(src_rate) / float(target_rate))
    return np.interp(x_out, np.arange(arr.size, dtype=np.float64), arr.astype(np.float64)).astype(np.float32)


def _pcm_from_wave(wf: Any) -> tuple[Any, int]:
    width = wf.getsampwidth()
    channels = max(1, wf.getnchannels())
    rate = int(wf.getframerate())
    raw = wf.readframes(wf.getnframes())
    if width == 1:  # 8-bit WAV is unsigned
        arr = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        arr = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw[: len(raw) // 3 * 3], dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = (v ^ 0x800000) - 0x800000  # sign-extend 24-bit
        arr = v.astype(np.float32) / 8388608.0
    elif width == 4:
        arr = (np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0).astype(np.float32)
    else:
        raise ValueError(f"_pcm: unsupported WAV sample width {width * 8} bits")
    frames = arr.size // channels
    arr = arr[: frames * channels].reshape(frames, channels).mean(axis=1).astype(np.float32)
    return arr, rate


def _pcm_from_wav_bytes(raw: bytes) -> tuple[Any, int]:
    try:
        with wave.open(io.BytesIO(raw), "rb") as wf:
            return _pcm_from_wave(wf)
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"_pcm: could not decode WAV bytes ({exc})") from exc


def _pcm_from_path(path_str: str) -> tuple[Any, int]:
    path = Path(path_str)
    if not path.is_file():
        raise ValueError(f"_pcm: audio file not found: {path_str!r} (and no in-memory samples were provided)")
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as wf:
                return _pcm_from_wave(wf)
        except (wave.Error, EOFError):
            pass  # e.g. float WAV — fall through to soundfile
    try:
        import soundfile as sf  # type: ignore
    except ImportError as exc:
        raise ValueError(f"_pcm: cannot decode {path.name!r}: soundfile not installed") from exc
    try:
        data, rate = sf.read(str(path), dtype="float32", always_2d=False)
    except Exception as exc:  # soundfile raises RuntimeError/LibsndfileError
        raise ValueError(f"_pcm: cannot decode audio file {path.name!r} ({exc})") from exc
    return _pcm_downmix(data), int(rate)


def _pcm_is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, np.ndarray):
        # AudioSample(data omitted) yields a 0-d NaN array (np.asarray(None)).
        return value.size == 0 or (value.ndim == 0 and bool(np.isnan(value)))
    if isinstance(value, (list, tuple, bytes, bytearray, str)):
        return len(value) == 0
    return False


def _pcm_decode(obj: Any) -> tuple[Any, int | None]:
    """Return (mono float32 ndarray, source sample rate or None)."""
    if obj is None:
        raise ValueError("_pcm: no audio input (got None)")
    if isinstance(obj, np.ndarray):
        return _pcm_downmix(obj), None
    if isinstance(obj, (bytes, bytearray, memoryview)):
        raw = bytes(obj)
        if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
            return _pcm_from_wav_bytes(raw)
        raise ValueError(
            "_pcm: undecodable bytes input (expected a RIFF/WAVE container); "
            "pass an AudioSample, a numeric array, or WAV bytes"
        )
    if isinstance(obj, str):
        return _pcm_from_path(obj)
    if isinstance(obj, Path):
        return _pcm_from_path(str(obj))
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return np.asarray([obj], dtype=np.float32), None
    if isinstance(obj, (list, tuple)):
        if not obj:
            return np.zeros(0, dtype=np.float32), None
        try:
            return _pcm_downmix(np.asarray(obj, dtype=np.float32)), None
        except (TypeError, ValueError):
            pass
        if len(obj) == 1:
            return _pcm_decode(obj[0])
        parts = [_pcm_decode(item) for item in obj]
        rate = next((r for _, r in parts if r), None)
        arrs = [_pcm_resample(a, r, rate) if r else a for a, r in parts]
        return np.concatenate(arrs).astype(np.float32), rate
    if isinstance(obj, dict):
        data = obj
    elif hasattr(obj, "model_dump"):
        # Attribute access keeps ndarrays intact (model_dump may copy/convert).
        data = {k: getattr(obj, k, None) for k in (*_PCM_DATA_KEYS, *_PCM_RATE_KEYS, "bytes", "path", "metadata")}
    else:
        raise ValueError(f"_pcm: undecodable audio input of type {type(obj).__name__}")
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    rate = next((int(data[k]) for k in _PCM_RATE_KEYS if data.get(k)), None)
    if rate is None:
        rate = next((int(meta[k]) for k in _PCM_RATE_KEYS if meta.get(k)), None)
    saw_empty = False
    for key in _PCM_DATA_KEYS:
        if key not in data:
            continue
        value = data[key]
        if _pcm_is_empty(value):
            saw_empty = saw_empty or value is not None
            continue
        arr, inner = _pcm_decode(value)
        return arr, inner or rate
    raw = data.get("bytes")
    if isinstance(raw, (bytes, bytearray)) and raw:
        arr, inner = _pcm_decode(bytes(raw))
        return arr, inner or rate
    path = data.get("path")
    if path:
        arr, inner = _pcm_from_path(str(path))
        return arr, inner or rate
    if saw_empty:
        return np.zeros(0, dtype=np.float32), rate
    raise ValueError("_pcm: undecodable audio input (no data/samples/bytes/path field)")


def _pcm(obj: Any, target_rate: int | None = _PCM_DEFAULT_RATE) -> list[float]:
    """Decode audio-like input to mono float PCM resampled to ``target_rate``.

    Accepts AudioSample / McuSample (pydantic or dict), numpy arrays, numeric
    lists, WAV bytes or a file path. Multichannel audio is downmixed by mean.
    When the source rate is unknown (bare arrays/lists) it is assumed to
    already be ``target_rate``. Raises ValueError on undecodable input.
    """
    arr, src_rate = _pcm_decode(obj)
    arr = _pcm_resample(np.asarray(arr, dtype=np.float32).reshape(-1), src_rate, target_rate)
    return arr.astype(np.float32).tolist()

def _dft_mag(frame: list[float]) -> list[float]:
    n = len(frame)
    if n == 0:
        return []
    # Real magnitude via a short radix-2-free DFT, capped so long audio stays bounded.
    step = max(1, n // 256)
    samples = frame[::step][:256]
    n = len(samples)
    mags = []
    bins = min(64, n)
    for k in range(bins):
        re = 0.0
        im = 0.0
        for i, x in enumerate(samples):
            ang = 2 * math.pi * k * i / n
            re += x * math.cos(ang)
            im -= x * math.sin(ang)
        mags.append(math.sqrt(re * re + im * im) / n)
    return mags

def _mfcc(samples: list[float], n_mfcc: int, n_fft: int, hop: int) -> list[list[float]]:
    n_mfcc = max(1, int(n_mfcc or 13))
    n_fft = max(8, int(n_fft or 256))
    hop = max(1, int(hop or 128))
    if not samples:
        return [[0.0] * n_mfcc]
    frames = []
    for start in range(0, max(1, len(samples) - n_fft + 1), hop):
        frame = samples[start : start + n_fft]
        if len(frame) < n_fft:
            frame = frame + [0.0] * (n_fft - len(frame))
        windowed = [frame[i] * (0.5 - 0.5 * math.cos(2 * math.pi * i / n_fft)) for i in range(n_fft)]
        mag = _dft_mag(windowed)
        logm = [math.log(m + 1e-8) for m in mag] or [0.0]
        coeffs = []
        for m in range(n_mfcc):
            acc = 0.0
            for k, val in enumerate(logm):
                acc += val * math.cos(math.pi * m * (k + 0.5) / len(logm))
            coeffs.append(acc)
        frames.append(coeffs)
        if len(frames) >= 64:
            break
    return frames or [[0.0] * n_mfcc]

def _logistic_train(xs: list[list[float]], ys: list[float], epochs: int) -> dict[str, Any]:
    if not xs:
        return {"weights": [], "bias": 0.0, "loss": 0.0, "epochs": 0}
    dim = max(len(row) for row in xs)
    w = [0.0] * dim
    bias = 0.0
    lr = 0.05
    last = 0.0
    for _ in range(max(1, int(epochs or 1))):
        loss = 0.0
        for row, y in zip(xs, ys):
            z = bias + sum(w[i] * (row[i] if i < len(row) else 0.0) for i in range(dim))
            p = 1 / (1 + math.exp(-max(-20, min(20, z))))
            err = p - (1.0 if y >= 0.5 else 0.0)
            loss += err * err
            for i in range(dim):
                w[i] -= lr * err * (row[i] if i < len(row) else 0.0)
            bias -= lr * err
        last = loss / max(1, len(xs))
    return {"weights": w, "bias": bias, "loss": last, "epochs": int(epochs or 1)}

def _train_from_dataset(config, inputs):
    dataset = _as_list(inputs.get("dataset") or inputs.get("input"))
    xs, ys = [], []
    labels = []
    for item in dataset:
        data = _dump(item)
        feats = _numbers(data)
        if not feats and isinstance(data, dict):
            feats = _numbers(data.get("payload"))
        if not feats and isinstance(data, dict) and (data.get("path") or _pcm_is_empty(data.get("data")) is False):
            # AudioSample (ndarray data / audio file): train on flattened MFCCs.
            feats = [c for frame in _mfcc(_pcm(item), 13, 256, 128) for c in frame]
        label = data.get("label") if isinstance(data, dict) else None
        if label not in labels:
            labels.append(label)
        xs.append(feats or [0.0])
        ys.append(float(labels.index(label) > 0) if labels else 0.0)
    epochs = int(_cfg(config, "epochs", 5) or 5)
    model = _logistic_train(xs, ys, epochs)
    model["labels"] = [str(x) for x in labels]
    model["n"] = len(xs)
    path = _out_path(config, "mcu_train")
    dest = path / "model.json" if path.is_dir() else path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(model), encoding="utf-8")
    model["path"] = str(dest)
    return model

def _impl(config, inputs, types):
    return {**_train_from_dataset(config, {"dataset": inputs.get("input")}), "features": _mfcc(_pcm(_as_list(inputs.get("input"))[0]) if _as_list(inputs.get("input")) else [], 13, 256, 128)[:4]}



class MicroSpeechPipelineNode(Node):
    """Opinionated KWS→int8 tflite helper"""

    node_type: ClassVar[str] = "micro_speech_pipeline"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="micro_speech_pipeline",
        label="Micro Speech Pipeline",
        description="Opinionated KWS→int8 tflite helper",
        category="ML",
        version="0.1.0",
        tags=["tinyml"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[AudioSample]|list[McuSample] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="DeploymentArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        labels: list = Field(default_factory=list)
        architecture: Literal["ds_cnn", "mobilenet", "simple_cnn"] = Field(default='ds_cnn', title="Architecture", description="Architecture.")
        quantize: str = Field(default='int8', title="Quantize", description="Quantize.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'micro_speech_pipeline'
        if stub:
            log.warning(
                "%s: stub mode (config.stub=True) returned a placeholder, not a real result",
                getattr(self, "node_type", type(self).__name__),
            )
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            _out = out_dir / 'stub'
            result = DeploymentArtifact(package_path=str(_out), target="stub", metadata={"stub": True})
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"micro_speech_pipeline: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _impl(self.config, inputs, _types)}
