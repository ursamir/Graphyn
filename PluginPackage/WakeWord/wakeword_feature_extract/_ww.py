"""Shared helpers for the WakeWord pack (copied verbatim into every wakeword_* plugin).

The pack wraps the upstream ``livekit-wakeword`` library (Apache-2.0,
https://github.com/livekit/livekit-wakeword): Piper-VITS / MMS synthetic data,
openWakeWord-style frozen mel + speech-embedding ONNX front end, the 3-phase
PyTorch trainer, ONNX export and the stateless ``WakeWordModel`` detector.

Stages hand a ``WakeWordRun`` to each other. Its ``model_dir`` follows the
library's on-disk layout (``<output_dir>/<model_name>/positive_train/clip_*.wav``,
``*_features_*.npy``, ``<model_name>.pt`` / ``.onnx``) and holds a
``wakeword_run.json`` manifest, so a stage can also be pointed at an existing
directory instead of an upstream edge.
"""
from __future__ import annotations

import io
import json
import shutil
import wave
from pathlib import Path
from typing import Any

import numpy as np

MANIFEST = "wakeword_run.json"
SPLITS = (
    "positive_train", "positive_test",
    "negative_train", "negative_test",
    "background_train", "background_test",
)
FEATURE_FILES = {
    "positive_train": "positive_features_train.npy",
    "positive_test": "positive_features_test.npy",
    "negative_train": "negative_features_train.npy",
    "negative_test": "negative_features_test.npy",
    "background_train": "background_noise_features_train.npy",
    "background_test": "background_noise_features_test.npy",
}
LIB_HINT = "pip install 'livekit-wakeword[train,export]>=0.2.1,<0.3'"
PIPER_RELEASE = "https://github.com/livekit/livekit-wakeword/releases/download/v0.1.0"
PIPER_STEM = "en-us-libritts-high"


# ── library access ────────────────────────────────────────────────────────────

def lib(module: str = "") -> Any:
    """Import ``livekit.wakeword[.module]`` with an actionable error."""
    import importlib

    name = "livekit.wakeword" + (f".{module}" if module else "")
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise RuntimeError(f"WakeWord pack needs the livekit-wakeword library ({LIB_HINT}): {exc}") from exc


def _bundled_cmudict() -> dict[str, list[str]]:
    """CMUdict from the ``cmudict`` wheel (bundled data, no nltk download)."""
    import cmudict  # type: ignore

    return {w: prons[0] for w, prons in cmudict.dict().items() if prons}


def patch_cmudict() -> None:
    """Point livekit-wakeword at the bundled CMUdict instead of ``nltk.download``.

    Upstream fetches cmudict through nltk at runtime (raw.githubusercontent.com);
    the ``cmudict`` package that ``pronouncing`` already depends on ships the
    same dictionary offline.
    """
    for mod in ("data.piper.text", "data.generate"):
        m = lib(mod)
        if getattr(m, "get_cmudict", None) is not _bundled_cmudict:
            m.get_cmudict = _bundled_cmudict


def ww_config(info: dict[str, Any], **overrides: Any) -> Any:
    """Build a library ``WakeWordConfig`` from a run manifest (+ overrides)."""
    cfg_mod = lib("config")
    model_dir = Path(info["model_dir"])
    data = {
        "model_name": info["model_name"],
        "target_phrases": list(info.get("target_phrases") or [info["model_name"]]),
        "output_dir": str(model_dir.parent),
        "data_dir": str(info.get("data_dir") or model_dir.parent / "_data"),
        "custom_negative_phrases": list(info.get("custom_negative_phrases") or []),
    }
    aug = dict(info.get("augmentation") or {})
    for key, value in overrides.items():
        if key == "augmentation":
            aug.update(value)
        else:
            data[key] = value
    if aug:
        data["augmentation"] = aug
    return cfg_mod.WakeWordConfig(**data)


# ── run manifest ──────────────────────────────────────────────────────────────

def read_manifest(model_dir: str | Path) -> dict[str, Any]:
    p = Path(model_dir) / MANIFEST
    if not p.is_file():
        raise ValueError(f"WakeWord: {p} not found — point at a directory produced by wakeword_data_gen")
    return json.loads(p.read_text(encoding="utf-8"))


def write_manifest(info: dict[str, Any]) -> dict[str, Any]:
    model_dir = Path(info["model_dir"])
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / MANIFEST).write_text(json.dumps(info, indent=2, default=str), encoding="utf-8")
    return info


def as_run(obj: Any, fallback_dir: str = "") -> dict[str, Any]:
    """Accept a WakeWordRun (object or dict after isolated transfer), a list of
    one, a model_dir string, or fall back to ``fallback_dir``; return the manifest."""
    if isinstance(obj, (list, tuple)):
        obj = obj[0] if obj else None
    if obj is not None and hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    model_dir = ""
    if isinstance(obj, dict):
        model_dir = str(obj.get("model_dir") or "")
    elif isinstance(obj, (str, Path)):
        model_dir = str(obj)
    model_dir = model_dir or (fallback_dir or "").strip()
    if not model_dir:
        raise ValueError("WakeWord: no run — connect the upstream wakeword stage or set config.model_dir")
    info = read_manifest(model_dir)
    info["model_dir"] = str(Path(model_dir))
    return info


def count_clips(model_dir: str | Path) -> dict[str, int]:
    import re

    rx = re.compile(r"^clip_\d{6}\.wav$")
    out: dict[str, int] = {}
    for split in SPLITS:
        d = Path(model_dir) / split
        out[split] = sum(1 for f in d.iterdir() if rx.match(f.name)) if d.is_dir() else 0
    return out


def run_payload(info: dict[str, Any]) -> dict[str, Any]:
    """Fields of the WakeWordRun port type."""
    keys = ("model_name", "model_dir", "target_phrases", "stage", "clip_counts", "features",
            "checkpoint_path", "onnx_path", "onnx_int8_path", "threshold", "metrics")
    out = {k: info.get(k) for k in keys if info.get(k) is not None}
    out["metadata"] = {k: v for k, v in info.items() if k not in keys}
    return out


# ── Piper checkpoint ──────────────────────────────────────────────────────────

def ensure_piper_checkpoint(path: str | Path) -> Path:
    """Return the Piper VITS state_dict path, downloading the public release
    (≈174 MB, livekit-wakeword v0.1.0 assets on GitHub) when missing."""
    import urllib.request

    pt = Path(path)
    js = pt.with_suffix(".json")
    pt.parent.mkdir(parents=True, exist_ok=True)
    for dest, asset in ((pt, f"{PIPER_STEM}.state_dict.pt"), (js, f"{PIPER_STEM}.config.json")):
        if dest.is_file() and dest.stat().st_size > 0:
            continue
        tmp = dest.with_suffix(dest.suffix + ".part")
        req = urllib.request.Request(f"{PIPER_RELEASE}/{asset}", headers={"User-Agent": "graphyn-wakeword/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, length=1 << 20)
            tmp.replace(dest)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"WakeWord: could not download Piper VITS {asset} from {PIPER_RELEASE}: {exc}") from exc
    return pt


# ── audio decoding (AudioSample / dict / bytes / path → float32 mono) ─────────

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



def pcm16k(obj: Any) -> np.ndarray:
    """Decode any supported audio input to float32 mono 16 kHz (``ValueError`` if undecodable)."""
    return np.asarray(_pcm(obj, target_rate=16000), dtype=np.float32)


def source_of(obj: Any) -> str:
    if isinstance(obj, (str, Path)):
        return str(obj)
    if isinstance(obj, dict):
        return str(obj.get("path") or obj.get("source_path") or "")
    return str(getattr(obj, "path", "") or getattr(obj, "source_path", "") or "")
