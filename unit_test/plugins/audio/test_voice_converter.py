# unit_test/plugins/audio/test_voice_converter.py
"""Tests for the voice_converter plugin (kNN-VC + explicit pitch shift).

Light tests cover registration, schema, reference resolution, the explicit
pitch_shift backend and the clear errors. The real kNN-VC conversion
(WavLM-Large + HiFi-GAN via torch.hub, ~1.3 GB) is ``heavy``
(GRAPHYN_RUN_HEAVY=1).
"""
from __future__ import annotations

import sys

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class

PLUGIN_SOURCE = "PluginPackage/Audio/voice_converter/"
NODE_TYPE = "voice_converter"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("voice_converter_plugins")
    from app.core.nodes.registry import NodeRegistry

    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


@pytest.fixture(scope="module")
def mod(installed_cls):
    return sys.modules[installed_cls.__module__]


def _tone(sr=16000, secs=1.0, f=220.0):
    from app.models.audio_sample import AudioSample

    t = np.arange(int(sr * secs)) / sr
    return AudioSample(path="/fake/tone.wav", sample_rate=sr, data=(0.3 * np.sin(2 * np.pi * f * t)).astype(np.float32))


def test_registers(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


def test_metadata_and_schema(installed_cls):
    meta = installed_cls.metadata
    assert meta.label and meta.category and meta.version == "2.0.0"
    fields = set(installed_cls.Config.model_fields)
    assert {"backend", "target_speaker", "topk", "pitch_shift_semitones", "device"} <= fields
    # Reserved/no-op option removed (it never changed the conversion).
    assert "conversion_type" not in fields
    assert installed_cls.Config().backend == "knnvc"


def test_knnvc_requires_target_reference(installed_cls):
    node = installed_cls(config={}, seed=0)
    with pytest.raises(ValueError, match="target_speaker"):
        node.process({"input": [_tone()]})


def test_missing_reference_file_is_clear(installed_cls, mod, tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        mod.reference_paths(str(tmp_path / "nope.wav"))


def test_reference_paths_dir_and_list(mod, tmp_path):
    import soundfile as sf

    for i in range(3):
        sf.write(tmp_path / f"r{i}.wav", np.zeros(1600, np.float32), 16000)
    (tmp_path / "notes.txt").write_text("x")
    assert len(mod.reference_paths(str(tmp_path))) == 3
    two = f"{tmp_path / 'r0.wav'}, {tmp_path / 'r1.wav'}"
    assert [p.name for p in mod.reference_paths(two)] == ["r0.wav", "r1.wav"]


def test_pitch_shift_backend(installed_cls):
    librosa = pytest.importorskip("librosa")
    node = installed_cls(config={"backend": "pitch_shift", "pitch_shift_semitones": 12}, seed=0)
    out = node.process({"input": [_tone(f=220.0)]})["output"]
    assert len(out) == 1
    y, sr = out[0].data, out[0].sample_rate
    spec = np.abs(np.fft.rfft(y))
    peak_hz = np.argmax(spec) * sr / len(y)
    assert 400 < peak_hz < 480  # one octave up from 220 Hz
    assert out[0].metadata["voice_converter"]["backend"] == "pitch_shift"


def test_pitch_shift_zero_is_rejected(installed_cls):
    node = installed_cls(config={"backend": "pitch_shift"}, seed=0)
    with pytest.raises(ValueError, match="does nothing"):
        node.process({"input": [_tone()]})


def test_empty_input(installed_cls):
    assert installed_cls(config={"target_speaker": "/x"}, seed=0).process({"input": []})["output"] == []


@pytest.mark.heavy
def test_knnvc_real_conversion_moves_toward_target(installed_cls, tmp_path):
    """Convert one synthetic voice to another; output must be 16 kHz speech."""
    pytest.importorskip("torch")
    pytest.importorskip("torchaudio")
    import soundfile as sf

    from app.models.audio_sample import AudioSample

    sr = 16000
    t = np.arange(sr * 3) / sr
    rng = np.random.default_rng(0)
    # Crude harmonic "voices" at two pitches (no network data needed).
    ref = sum(np.sin(2 * np.pi * 110 * k * t) / k for k in range(1, 8)) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))
    sf.write(tmp_path / "ref.wav", (0.2 * ref).astype(np.float32), sr)
    src = sum(np.sin(2 * np.pi * 230 * k * t) / k for k in range(1, 8)) * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t))
    src = (0.2 * src + 0.01 * rng.standard_normal(t.size)).astype(np.float32)
    node = installed_cls(config={"target_speaker": str(tmp_path / "ref.wav")}, seed=0)
    out = node.process({"input": [AudioSample(path="/src.wav", sample_rate=sr, data=src)]})["output"][0]
    assert out.sample_rate == 16000
    assert out.data.ndim == 1 and abs(out.data.size - src.size) < 1600
    assert np.isfinite(out.data).all() and np.abs(out.data).max() > 1e-3
    assert out.metadata["voice_converter"]["target_references"] == [str(tmp_path / "ref.wav")]
