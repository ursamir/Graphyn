"""Regression tests for the shared ``_pcm()`` audio decoder.

The decoder now lives in the WakeWord pack's ``_ww.py`` (exposed as
``wakeword_infer.nodes._pcm``): ndarray AudioSample data, sample-rate
handling, multichannel downmix, WAV bytes at several sample widths and clear
errors on undecodable input.

F20: the TinyML copies (mcu_window / mcu_mfcc / mcu_spectrogram /
mcu_feature_pipeline / mcu_dataset_ingest / micro_speech_pipeline) and their
window-cap tests were removed with the TinyML pack (it stays out of the
product — see docs/reviews/full/SWEEP_TEMPLATES_F20.md). The old
wakeword_feature_extract copy is gone (features now come from
livekit-wakeword's ONNX front end) and Video/av_align decodes through ffmpeg.
The old wakeword_infer logistic-JSON tests were replaced by
unit_test/plugins/wakeword/test_wakeword_pack.py.
"""
from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np
import pytest

from app.models.audio_sample import AudioSample

ROOT = Path(__file__).resolve().parents[2]

PCM_PLUGINS = [
    "WakeWord/wakeword_infer",
]


def _load(rel: str):
    import importlib
    import sys

    root = ROOT / "PluginPackage" / rel
    parent, name = str(root.parent), root.name
    if parent not in sys.path:
        sys.path.insert(0, parent)
    for k in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
        del sys.modules[k]
    return importlib.import_module(f"{name}.nodes")


@pytest.fixture(scope="module", params=PCM_PLUGINS)
def mod(request):
    return _load(request.param)


def _wav_bytes(samples: np.ndarray, rate: int, width: int, channels: int = 1) -> bytes:
    """Encode float samples in [-1, 1] (shape (n,) or (n, ch)) as WAV."""
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    if width == 1:
        raw = np.clip(np.round(x * 127 + 128), 0, 255).astype(np.uint8).tobytes()
    elif width == 2:
        raw = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2").tobytes()
    elif width == 3:
        v = np.clip(np.round(x * 8388607), -8388608, 8388607).astype(np.int32)
        b = v.astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3]
        raw = b.tobytes()
    else:
        raw = np.clip(np.round(x * 2147483647), -2147483648, 2147483647).astype("<i4").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(raw)
    return buf.getvalue()


def _tone(n: int, rate: int, freq: float = 440.0, amp: float = 0.5) -> np.ndarray:
    return (amp * np.sin(2 * np.pi * freq * np.arange(n) / rate)).astype(np.float32)


# ── _pcm decoding (every copy) ────────────────────────────────────────────────


def test_audiosample_ndarray_is_decoded_not_path_text(mod):
    data = _tone(32000, 16000)
    s = AudioSample(path="clip_001.flac", sample_rate=16000, data=data)
    out = mod._pcm(s)
    assert len(out) == 32000
    np.testing.assert_allclose(out, data, atol=1e-6)


def test_audiosample_8k_stereo_is_mono_and_resampled(mod):
    mono = _tone(8000, 8000, freq=200.0)
    stereo = np.stack([mono, mono * 0.0], axis=1)  # (n, ch)
    s = AudioSample(path="x.wav", sample_rate=8000, data=stereo)
    out = np.asarray(mod._pcm(s))  # default target 16 kHz
    assert out.ndim == 1
    assert len(out) == 16000
    # Mean downmix halves amplitude.
    assert abs(float(np.max(np.abs(out))) - 0.25) < 0.01
    # (ch, n) layout gives the same result.
    s2 = AudioSample(path="x.wav", sample_rate=8000, data=stereo.T.copy())
    np.testing.assert_allclose(mod._pcm(s2), out, atol=1e-6)
    # Native rate preserved when target_rate=None.
    assert len(mod._pcm(s, target_rate=None)) == 8000


def test_dict_sample_with_metadata_rate(mod):
    s = {"payload": _tone(4000, 8000).tolist(), "metadata": {"sample_rate": 8000}}
    assert len(mod._pcm(s)) == 8000


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_wav_bytes_by_sample_width(mod, width):
    ref = _tone(1600, 16000, amp=0.5)
    out = np.asarray(mod._pcm(_wav_bytes(ref, 16000, width)))
    assert len(out) == 1600
    tol = 0.02 if width == 1 else 1e-3
    np.testing.assert_allclose(out, ref, atol=tol)


def test_wav_bytes_stereo_8k_resampled(mod):
    ref = _tone(800, 8000, freq=100.0)
    inter = np.stack([ref, ref], axis=1)
    out = mod._pcm({"bytes": _wav_bytes(inter, 8000, 2, channels=2)})
    assert len(out) == 1600


def test_wav_file_path(mod, tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(_wav_bytes(_tone(4000, 8000), 8000, 1))
    assert len(mod._pcm({"path": str(p)})) == 8000
    assert len(mod._pcm(AudioSample(path=str(p), sample_rate=8000))) == 8000


@pytest.mark.parametrize(
    "bad",
    [
        b"just some text bytes",
        "clip_does_not_exist.flac",
        {"path": "missing/clip.flac"},
        {"foo": "bar"},
        None,
        object(),
    ],
)
def test_undecodable_input_raises(mod, bad):
    with pytest.raises(ValueError):
        mod._pcm(bad)


def test_plain_list_and_empty(mod):
    assert mod._pcm([0.1, 0.2, 0.3]) == pytest.approx([0.1, 0.2, 0.3])
    assert mod._pcm([]) == []
    assert mod._pcm(AudioSample(path="", sample_rate=16000)) == []
