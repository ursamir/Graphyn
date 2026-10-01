"""Example 06 — behavioural tests for every audio-side config value.

Plugins: dataset_ingest, audio_conditioner, segmenter, audio_quality_gate,
augmentation_pipeline, audio_exporter, feature_frontend (PluginPackage/Audio).
Each enum value / boolean toggle / boundary used (or exposed) by
examples/06_speech_commands_e2e is exercised on small synthetic audio.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry
from app.models.audio_sample import AudioSample

ROOT = Path(__file__).resolve().parents[2]
AUDIO = ROOT / "PluginPackage" / "Audio"
SR = 16000


def _load(plugin: str, node_type: str | None = None):
    root = AUDIO / plugin
    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    for entry in ("types.py", "nodes.py"):
        if (root / entry).is_file():
            disc._process_module(disc._import_file(root / entry, package_prefix=None))
    return reg.get_class(node_type or plugin)


def _run(cls, samples, config=None, seed=0, port="output"):
    out = cls(config=config or {}, seed=seed).process({"input": samples})
    return out[port] if port else out


def _tone(seconds=1.0, amp=0.5, freq=440.0, sr=SR, noise=0.0, seed=0):
    t = np.arange(int(seconds * sr)) / sr
    y = amp * np.sin(2 * np.pi * freq * t)
    if noise:
        y = y + np.random.default_rng(seed).normal(0, noise, size=y.shape)
    return y.astype(np.float32)


def _speechlike(seed=0, sr=SR):
    """0.3 s silence + 0.5 s harmonic burst + 0.2 s silence (≈ a 1 s keyword clip)."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(0.5 * sr)) / sr
    burst = sum(np.sin(2 * np.pi * f * t) / (i + 1) for i, f in enumerate((220, 660, 1500, 3100)))
    burst = 0.4 * burst * np.hanning(len(t)) + rng.normal(0, 0.01, len(t))
    y = np.concatenate([rng.normal(0, 1e-4, int(0.3 * sr)), burst, rng.normal(0, 1e-4, int(0.2 * sr))])
    return y.astype(np.float32)


def _sample(y, sr=SR, label="yes", path="clip.wav", **meta):
    return AudioSample(path=path, sample_rate=sr, data=y, label=label, metadata=dict(meta))


def _db(x):
    return 20 * np.log10(max(float(x), 1e-12))


# ── dataset_ingest ───────────────────────────────────────────────────────────


@pytest.fixture()
def labelled_tree(tmp_path: Path) -> Path:
    root = tmp_path / "ds"
    for split in ("train", "test"):
        for label in ("go", "yes"):
            d = root / split / label
            d.mkdir(parents=True)
            for i in range(3):
                sf.write(d / f"{label}_{split}_{i}.wav", _tone(0.2, freq=300 + 50 * i), SR)
    return root


class TestDatasetIngest:
    cls = staticmethod(lambda: _load("dataset_ingest"))

    def _ingest(self, **cfg):
        return self.cls()(config=cfg).process({})["output"]

    def test_recursive_labels_from_dirnames(self, labelled_tree):
        out = self._ingest(path=str(labelled_tree), recursive=True)
        assert len(out) == 12
        assert {s.label for s in out} == {"go", "yes"}
        assert all(("/train/" in s.path) or ("/test/" in s.path) for s in out)

    def test_recursive_limit_is_per_label(self, labelled_tree):
        out = self._ingest(path=str(labelled_tree), recursive=True, limit=2)
        counts = {lbl: sum(s.label == lbl for s in out) for lbl in ("go", "yes")}
        assert counts == {"go": 2, "yes": 2}
        # sorted walk: the per-label budget is consumed by test/ before train/
        assert all("/test/" in s.path for s in out)

    def test_non_recursive_limit_is_total_and_label_is_folder(self, labelled_tree):
        flat = labelled_tree / "train" / "go"
        out = self._ingest(path=str(flat), recursive=False, limit=2)
        assert len(out) == 2 and {s.label for s in out} == {"go"}

    def test_label_override(self, labelled_tree):
        out = self._ingest(path=str(labelled_tree / "train" / "go"), recursive=False, label_override="cmd")
        assert {s.label for s in out} == {"cmd"}

    def test_limit_negative_rejected(self):
        with pytest.raises(Exception):
            self.cls().Config(limit=-1)

    def test_empty_path_rejected(self):
        with pytest.raises(ValueError, match="path is required"):
            self._ingest(path="")

    def test_deduplicate(self, tmp_path):
        d = tmp_path / "dup"
        d.mkdir()
        sf.write(d / "a.wav", _tone(0.2), SR)
        sf.write(d / "b.wav", _tone(0.2), SR)
        assert len(self._ingest(path=str(d), recursive=False, deduplicate=False)) == 2
        assert len(self._ingest(path=str(d), recursive=False, deduplicate=True)) == 1


# ── audio_conditioner ────────────────────────────────────────────────────────


class TestAudioConditioner:
    @pytest.fixture(scope="class")
    def cls(self):
        return _load("audio_conditioner")

    def test_resample_and_mono(self, cls):
        stereo = np.stack([_tone(0.5, sr=8000), _tone(0.5, sr=8000)])
        (out,) = _run(cls, [_sample(stereo, sr=8000)], {"target_sample_rate": 16000, "trim_silence": False})
        assert out.sample_rate == 16000 and out.data.ndim == 1
        assert abs(len(out.data) - 8000) <= 2

    def test_peak_normalize_hits_target_level(self, cls):
        (out,) = _run(cls, [_sample(_tone(amp=0.1))], {"normalize_method": "peak", "target_level_db": -6.0, "trim_silence": False})
        assert _db(np.max(np.abs(out.data))) == pytest.approx(-6.0, abs=0.05)

    def test_rms_normalize_hits_target_level(self, cls):
        (out,) = _run(cls, [_sample(_tone(amp=0.1))], {"normalize_method": "rms", "target_level_db": -20.0, "trim_silence": False})
        assert _db(np.sqrt(np.mean(out.data ** 2))) == pytest.approx(-20.0, abs=0.05)

    def test_lufs_normalize_hits_target(self, cls):
        pyln = pytest.importorskip("pyloudnorm")
        (out,) = _run(cls, [_sample(_tone(2.0, amp=0.05, noise=0.01))], {"normalize_method": "lufs", "target_lufs": -23.0, "trim_silence": False})
        assert pyln.Meter(SR).integrated_loudness(out.data) == pytest.approx(-23.0, abs=0.3)
        assert out.metadata["conditioning"]["target_lufs"] == -23.0

    def test_methods_produce_different_levels(self, cls):
        y = _sample(_tone(amp=0.1, noise=0.02))
        peaks = {
            m: float(np.max(np.abs(_run(cls, [y], {"normalize_method": m, "target_level_db": -12.0, "trim_silence": False})[0].data)))
            for m in ("peak", "rms")
        }
        assert peaks["peak"] != pytest.approx(peaks["rms"], rel=0.05)

    def test_normalize_off_keeps_level(self, cls):
        (out,) = _run(cls, [_sample(_tone(amp=0.1))], {"normalize": False, "trim_silence": False, "remove_dc_offset": False})
        assert np.max(np.abs(out.data)) == pytest.approx(0.1, rel=1e-3)

    def test_trim_silence_toggle_and_threshold(self, cls):
        y = _sample(_speechlike())
        on = _run(cls, [y], {"trim_silence": True, "trim_threshold_db": 40.0})[0]
        off = _run(cls, [y], {"trim_silence": False})[0]
        assert len(off.data) == len(y.data) and len(on.data) < 0.75 * len(y.data)
        loose = _run(cls, [y], {"trim_silence": True, "trim_threshold_db": 90.0})[0]
        assert len(loose.data) > len(on.data), "higher top_db = less audio trimmed"

    def test_dc_offset_removal(self, cls):
        y = _tone(amp=0.1) + 0.3
        on = _run(cls, [_sample(y)], {"remove_dc_offset": True, "normalize": False, "trim_silence": False})[0]
        off = _run(cls, [_sample(y)], {"remove_dc_offset": False, "normalize": False, "trim_silence": False})[0]
        assert abs(np.mean(on.data)) < 1e-3 and np.mean(off.data) == pytest.approx(0.3, abs=1e-3)

    def test_preemphasis_boosts_highs(self, cls):
        y = _tone(amp=0.3, freq=100) + _tone(amp=0.3, freq=6000)
        base = {"normalize": False, "trim_silence": False}
        on = _run(cls, [_sample(y)], {**base, "preemphasis": True, "preemphasis_coeff": 0.97})[0].data
        assert not np.allclose(on, y)
        assert _run(cls, [_sample(y)], base)[0].data == pytest.approx(y - np.mean(y), abs=1e-6)

    def test_compression_reduces_peaks(self, cls):
        y = _tone(amp=0.9)
        base = {"normalize": False, "trim_silence": False}
        comp = _run(cls, [_sample(y)], {**base, "compress": True, "compress_threshold_db": -20.0, "compress_ratio": 4.0})[0]
        assert np.max(np.abs(comp.data)) < 0.5

    def test_limiter_and_skip_clipped(self, cls):
        # rms normalisation to -1 dBFS drives a sine's peaks above full scale
        base = {"normalize_method": "rms", "target_level_db": -1.0, "trim_silence": False}
        limited = _run(cls, [_sample(_tone(amp=0.1))], {**base, "limiter": True})[0]
        assert np.max(np.abs(limited.data)) <= 1.0 and limited.metadata["clipped"] is True
        raw = _run(cls, [_sample(_tone(amp=0.1))], {**base, "limiter": False})[0]
        assert np.max(np.abs(raw.data)) > 1.0
        assert _run(cls, [_sample(_tone(amp=0.1))], {**base, "skip_clipped": True}) == []

    @pytest.mark.parametrize("batch_size", [0, 1, 3])
    def test_batch_size_does_not_change_output(self, cls, batch_size):
        samples = [_sample(_tone(amp=0.1 * (i + 1)), path=f"{i}.wav") for i in range(4)]
        out = _run(cls, samples, {"batch_size": batch_size, "trim_silence": False})
        assert [s.path for s in out] == [s.path for s in samples]

    @pytest.mark.parametrize("bad", [
        {"target_sample_rate": 0}, {"trim_threshold_db": 0}, {"target_level_db": 1.0},
        {"preemphasis_coeff": 1.5}, {"compress_ratio": 0}, {"batch_size": -1},
        {"normalize_method": "loud"},
    ])
    def test_invalid_config_rejected(self, cls, bad):
        with pytest.raises(Exception):
            cls.Config(**bad)


# ── segmenter ────────────────────────────────────────────────────────────────


class TestSegmenter:
    @pytest.fixture(scope="class")
    def cls(self):
        return _load("segmenter")

    def test_fixed_windows_and_overlap(self, cls):
        y = _sample(_tone(3.0))
        assert len(_run(cls, [y], {"mode": "fixed", "window_ms": 1000})) == 3
        assert len(_run(cls, [y], {"mode": "fixed", "window_ms": 1000, "overlap": 0.5})) == 5

    def test_fixed_short_clip_emitted_whole(self, cls):
        (seg,) = _run(cls, [_sample(_tone(0.6))], {"mode": "fixed", "window_ms": 1000})
        assert len(seg.data) == int(0.6 * SR)

    def test_silence_mode_strips_silence(self, cls):
        segs = _run(cls, [_sample(_speechlike())], {"mode": "silence", "silence_threshold_db": 40.0})
        assert len(segs) >= 1
        total = sum(len(s.data) for s in segs)
        assert 0.3 * SR < total < 0.7 * SR
        assert all(s.metadata["segmentation_mode"] == "silence" for s in segs)

    def test_silence_mode_can_split_one_clip_into_several(self, cls):
        gap = np.zeros(int(0.3 * SR), dtype=np.float32)
        y = np.concatenate([_tone(0.3), gap, _tone(0.3)])
        segs = _run(cls, [_sample(y)], {"mode": "silence"})
        assert len(segs) == 2 and all(s.metadata["parent"] == "clip.wav" for s in segs)

    def test_silence_threshold_higher_keeps_more(self, cls):
        y = _sample(_speechlike())
        strict = sum(len(s.data) for s in _run(cls, [y], {"mode": "silence", "silence_threshold_db": 20.0}))
        loose = sum(len(s.data) for s in _run(cls, [y], {"mode": "silence", "silence_threshold_db": 80.0}))
        assert loose > strict

    def test_vad_mode(self, cls):
        segs = _run(cls, [_sample(_speechlike())], {"mode": "vad", "vad_aggressiveness": 0})
        assert all(s.metadata["segmentation_mode"] == "vad" for s in segs)

    def test_event_mode_threshold(self, cls):
        y = np.concatenate([np.zeros(SR // 2), _tone(0.3), np.zeros(SR // 2), _tone(0.3, amp=0.05), np.zeros(SR // 2)]).astype(np.float32)
        loud_only = _run(cls, [_sample(y)], {"mode": "event", "event_threshold_db": -10.0})
        both = _run(cls, [_sample(y)], {"mode": "event", "event_threshold_db": -40.0})
        assert len(loud_only) == 1 and len(both) == 2

    def test_speaker_turn_uses_metadata_segments(self, cls):
        s = _sample(_tone(2.0), speaker_segments=[{"start": 0, "end": 0.5, "speaker_id": "A"}, {"start": 1.0, "end": 2.0, "speaker_id": "B"}])
        segs = _run(cls, [s], {"mode": "speaker_turn"})
        assert [x.metadata["speaker_id"] for x in segs] == ["A", "B"]

    def test_speaker_turn_falls_back_to_silence(self, cls):
        assert _run(cls, [_sample(_speechlike())], {"mode": "speaker_turn"})

    def test_min_segment_drops_short(self, cls):
        assert _run(cls, [_sample(_tone(0.05))], {"mode": "fixed", "min_segment_ms": 100}) == []

    def test_max_segment_splits_long_spans(self, cls):
        """Regression: max_segment_ms used to DROP long spans although documented as 'split'."""
        segs = _run(cls, [_sample(_tone(2.5))], {"mode": "silence", "max_segment_ms": 1000, "min_segment_ms": 100})
        assert [len(s.data) for s in segs] == [SR, SR, SR // 2]
        assert [s.metadata["segment_id"] for s in segs] == [0, 1, 2]

    @pytest.mark.parametrize("bad", [
        {"overlap": 1.0}, {"overlap": -0.1}, {"vad_aggressiveness": 4}, {"window_ms": 0},
        {"min_segment_ms": 500, "max_segment_ms": 400}, {"silence_threshold_db": 0},
        {"event_threshold_db": 3.0}, {"mode": "words"},
    ])
    def test_invalid_config_rejected(self, cls, bad):
        with pytest.raises(Exception):
            cls.Config(**bad)


# ── audio_quality_gate ───────────────────────────────────────────────────────


class TestAudioQualityGate:
    @pytest.fixture(scope="class")
    def cls(self):
        return _load("audio_quality_gate")

    def _gate(self, cls, samples, **cfg):
        out = cls(config=cfg).process({"input": samples})
        return out["output"], out["rejected"]

    ONLY = {k: False for k in ("check_snr", "check_clipping", "check_silence", "check_duration", "check_bandwidth", "check_lufs")}

    def test_duration_bounds(self, cls):
        clips = [_sample(_tone(d), path=f"{d}.wav") for d in (0.1, 0.5, 1.5)]
        ok, bad = self._gate(cls, clips, **{**self.ONLY, "check_duration": True, "min_duration_s": 0.2, "max_duration_s": 1.0})
        assert [s.path for s in ok] == ["0.5.wav"] and len(bad) == 2
        assert "too_short" in bad[0].metadata["quality_rejection_reasons"][0]

    def test_max_duration_zero_means_no_max(self, cls):
        """Regression: max_duration_s=0 was documented as 'no max' but rejected everything."""
        ok, _ = self._gate(cls, [_sample(_tone(5.0))], **{**self.ONLY, "check_duration": True, "max_duration_s": 0})
        assert len(ok) == 1

    def test_snr_check(self, cls):
        """SNR = mean power / (5th-percentile |x|)^2.

        A constant-magnitude floor (e.g. hum/buzz) gives ~0 dB and is rejected.
        Known limitation: Gaussian white noise alone estimates ~24 dB (its 5th
        percentile magnitude is tiny), so stationary hiss passes min_snr_db=5.
        """
        clean = _sample(_speechlike(), path="clean.wav")
        buzz = np.sign(_tone(1.0, freq=50.0)) * 0.1 + _tone(1.0, amp=0.02)
        noisy = _sample(buzz.astype(np.float32), path="buzz.wav")
        hiss = _sample(np.random.default_rng(0).normal(0, 0.1, SR).astype(np.float32), path="hiss.wav")
        ok, bad = self._gate(cls, [clean, noisy, hiss], **{**self.ONLY, "check_snr": True, "min_snr_db": 5.0})
        assert [s.path for s in bad] == ["buzz.wav"]
        assert sorted(s.path for s in ok) == ["clean.wav", "hiss.wav"]

    def test_clipping_check(self, cls):
        clipped = _sample(np.clip(_tone(amp=2.0), -1, 1), path="clip.wav")
        ok, bad = self._gate(cls, [clipped, _sample(_tone(amp=0.5))], **{**self.ONLY, "check_clipping": True, "max_clipping_ratio": 0.01})
        assert [s.path for s in bad] == ["clip.wav"] and len(ok) == 1

    def test_silence_check(self, cls):
        ok, bad = self._gate(cls, [_sample(np.zeros(SR, dtype=np.float32))], **{**self.ONLY, "check_silence": True})
        assert not ok and "silent" in bad[0].metadata["quality_rejection_reasons"][0]

    def test_bandwidth_check(self, cls):
        low = _sample(_tone(freq=200.0), path="low.wav")
        ok, bad = self._gate(cls, [low], **{**self.ONLY, "check_bandwidth": True, "min_bandwidth_hz": 1000.0})
        assert [s.path for s in bad] == ["low.wav"]

    def test_lufs_check(self, cls):
        pytest.importorskip("pyloudnorm")
        quiet = _sample(_tone(2.0, amp=0.001), path="quiet.wav")
        ok, bad = self._gate(cls, [quiet, _sample(_tone(2.0, amp=0.3))], **{**self.ONLY, "check_lufs": True, "min_lufs": -40.0, "max_lufs": 0.0})
        assert [s.path for s in bad] == ["quiet.wav"] and len(ok) == 1

    @pytest.mark.parametrize("policy", ["skip", "warn"])
    def test_skip_and_warn_route_to_rejected(self, cls, policy, caplog):
        ok, bad = self._gate(cls, [_sample(np.zeros(SR, dtype=np.float32))], **{**self.ONLY, "check_silence": True, "rejection_policy": policy})
        assert not ok and len(bad) == 1
        warned = any("rejected" in r.getMessage() for r in caplog.records if r.levelname == "WARNING")
        assert warned is (policy == "warn")

    def test_raise_policy(self, cls):
        with pytest.raises(ValueError, match="rejected"):
            self._gate(cls, [_sample(np.zeros(SR, dtype=np.float32))], **{**self.ONLY, "check_silence": True, "rejection_policy": "raise"})

    def test_ex06_duration_gate_no_longer_applies_hidden_snr(self, cls):
        """The ex-06 'duration filter' must not reject on SNR (it used the 10 dB default)."""
        graph = json.loads((ROOT / "examples/06_speech_commands_e2e/pipeline_preprocess.graph.json").read_text())
        cfg = next(n["config"] for n in graph["nodes"] if n["id"] == "audio_quality_gate_4")
        buzz = (np.sign(_tone(0.6, freq=50.0)) * 0.1).astype(np.float32)  # ~0 dB "SNR"
        ok, _ = self._gate(cls, [_sample(buzz)], **cfg)
        assert len(ok) == 1

    @pytest.mark.parametrize("bad", [
        {"max_clipping_ratio": 1.5}, {"min_duration_s": -1}, {"min_duration_s": 2, "max_duration_s": 1},
        {"min_lufs": -5, "max_lufs": -10}, {"rejection_policy": "error"}, {"silence_rms_threshold": -0.1},
    ])
    def test_invalid_config_rejected(self, cls, bad):
        with pytest.raises(Exception):
            cls.Config(**bad)


# ── augmentation_pipeline ────────────────────────────────────────────────────


class TestAugmentationPipeline:
    @pytest.fixture(scope="class")
    def cls(self):
        return _load("augmentation_pipeline")

    @pytest.mark.parametrize("aug,check", [
        ({"type": "gain", "gain_db": [6, 6]}, lambda o, a: np.max(np.abs(a)) == pytest.approx(2 * np.max(np.abs(o)), rel=0.01)),
        ({"type": "pitch_shift", "semitones": [2, 2]}, lambda o, a: len(a) == len(o) and not np.allclose(a, o, atol=1e-3)),
        ({"type": "time_stretch", "rate": [0.5, 0.5]}, lambda o, a: len(a) == pytest.approx(2 * len(o), rel=0.02)),
        ({"type": "speed_perturb", "speed_factor": [1.1, 1.1]}, lambda o, a: abs(len(a) - len(o)) <= 2 and not np.allclose(a, o, atol=1e-3)),
        ({"type": "noise_inject", "snr_db": [10, 10]}, lambda o, a: 8 < 10 * np.log10(np.mean(o ** 2) / np.mean((a - o) ** 2)) < 12),
        ({"type": "codec_degrade", "codec": "ogg", "bitrate": 32}, lambda o, a: len(a) == len(o) and not np.allclose(a, o)),
        ({"type": "eq", "bands": [{"freq": 440, "gain_db": 12, "q": 1.0}]}, lambda o, a: np.max(np.abs(a)) > 2 * np.max(np.abs(o))),
    ])
    def test_each_augmentation_applies(self, cls, aug, check):
        y = _tone(0.5, amp=0.2)
        out = _run(cls, [_sample(y)], {"copies_per_sample": 1, "augmentations": [{**aug, "apply_prob": 1.0}]})
        assert len(out) == 2
        orig, augd = out
        assert np.array_equal(orig.data, y) and orig.metadata.get("augmented") is None
        assert augd.metadata["augmentations_applied"] == [aug["type"]]
        assert check(y, augd.data)

    def test_reverb_with_ir_dir(self, cls, tmp_path):
        ir = np.zeros(800, dtype=np.float32)
        ir[0], ir[400] = 1.0, 0.6
        sf.write(tmp_path / "ir.wav", ir, SR)
        out = _run(cls, [_sample(_tone(0.3))], {"augmentations": [{"type": "reverb", "apply_prob": 1.0, "impulse_response_path": str(tmp_path)}]})
        assert out[1].metadata["impulse_response"] == "ir.wav"

    def test_apply_prob_zero_never_applies(self, cls):
        out = _run(cls, [_sample(_tone(0.3))], {"copies_per_sample": 3, "augmentations": [{"type": "gain", "apply_prob": 0.0}]})
        assert len(out) == 4 and all(o.metadata.get("augmentations_applied", []) == [] for o in out[1:])

    @pytest.mark.parametrize("copies", [0, 2])
    def test_copies_per_sample(self, cls, copies):
        out = _run(cls, [_sample(_tone(0.3)), _sample(_tone(0.3), path="b.wav")], {"copies_per_sample": copies, "augmentations": [{"type": "gain", "apply_prob": 1.0}]})
        assert len(out) == 2 * (1 + copies)

    def test_ex06_config_triples_dataset_and_is_seeded(self, cls):
        graph = json.loads((ROOT / "examples/06_speech_commands_e2e/pipeline_preprocess.graph.json").read_text())
        cfg = next(n["config"] for n in graph["nodes"] if n["node_type"] == "augmentation_pipeline")
        a = _run(cls, [_sample(_speechlike())], cfg, seed=42)
        b = _run(cls, [_sample(_speechlike())], cfg, seed=42)
        assert len(a) == 3
        assert all(x.metadata["augmentations_applied"] == ["pitch_shift", "time_stretch"] for x in a[1:])
        assert all(np.array_equal(x.data, y.data) for x, y in zip(a, b))

    def test_toml_default_matches_config_default(self, cls):
        import tomllib

        toml = tomllib.loads((AUDIO / "augmentation_pipeline/plugin.toml").read_text())
        assert toml["config_schema"]["augmentation_pipeline"]["augmentations"]["default"] == cls.Config().augmentations

    @pytest.mark.parametrize("bad", [
        {"copies_per_sample": -1},
        {"augmentations": [{"type": "pitchshift"}]},
        {"augmentations": [{"type": "gain", "apply_prob": 1.5}]},
        {"augmentations": [{"type": "time_stretch", "rate": [0, 1]}]},
        {"augmentations": ["gain"]},
    ])
    def test_invalid_config_rejected(self, cls, bad):
        with pytest.raises(Exception):
            cls.Config(**bad)


# ── audio_exporter ───────────────────────────────────────────────────────────


@pytest.fixture()
def in_tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _labels_csv(root: Path) -> list[dict]:
    with open(root / "labels.csv", newline="") as f:
        return list(csv.DictReader(f))


class TestAudioExporter:
    @pytest.fixture(scope="class")
    def cls(self):
        return _load("audio_exporter")

    def _samples(self, n=40, label="yes", copies=0):
        out = []
        for i in range(n):
            out.append(_sample(_tone(0.1), label=label, path=f"/data/{label}/{label}_{i}.wav"))
            for c in range(copies):
                out.append(_sample(_tone(0.1, amp=0.3), label=label, path=f"/data/{label}/{label}_{i}.wav", augmented=True, augmentation_copy=c))
        return out

    def test_layout_and_split_ratios(self, cls, in_tmp_cwd):
        _run(cls, self._samples(200), {"output_dir": "out", "split_ratios": {"train": 0.7, "val": 0.15, "test": 0.15}})
        rows = _labels_csv(in_tmp_cwd / "out/v1")
        counts = {s: sum(r["split"] == s for r in rows) for s in ("train", "val", "test")}
        assert sum(counts.values()) == 200
        assert 120 <= counts["train"] <= 160 and counts["val"] > 10 and counts["test"] > 10
        for r in rows:
            assert (in_tmp_cwd / "out/v1" / r["path"]).is_file()
            assert r["path"].startswith(f"{r['split']}/yes/")
        assert json.loads((in_tmp_cwd / "out/v1/lineage.json").read_text())["n_samples"] == 200

    def test_split_ratio_extremes(self, cls, in_tmp_cwd):
        _run(cls, self._samples(20), {"output_dir": "out", "split_ratios": {"train": 1.0, "val": 0, "test": 0}})
        assert {r["split"] for r in _labels_csv(in_tmp_cwd / "out/v1")} == {"train"}

    def test_unnormalised_ratios_are_normalised(self, cls, in_tmp_cwd):
        _run(cls, self._samples(100), {"output_dir": "out", "split_ratios": {"train": 2, "test": 2}})
        counts = [r["split"] for r in _labels_csv(in_tmp_cwd / "out/v1")]
        assert 30 < counts.count("train") < 70

    def test_preassigned_split_wins(self, cls, in_tmp_cwd):
        s = self._samples(5)
        for x in s:
            x.metadata["split"] = "val"
        _run(cls, s, {"output_dir": "out"})
        assert {r["split"] for r in _labels_csv(in_tmp_cwd / "out/v1")} == {"val"}

    def test_group_by_source_prevents_augmentation_leakage(self, cls, in_tmp_cwd):
        """Regression: augmented copies of one clip used to land in different splits."""
        _run(cls, self._samples(60, copies=2), {"output_dir": "out"})
        rows = _labels_csv(in_tmp_cwd / "out/v1")
        meta = json.loads((in_tmp_cwd / "out/v1/metadata.json").read_text())
        by_src: dict[str, set] = {}
        for m in meta:
            src = Path(m["path"]).stem.split("_0")[0]  # yes_12, yes_12_001 → same source
            by_src.setdefault("_".join(Path(m["path"]).stem.split("_")[:2]), set()).add(m["split"])
        assert len(rows) == 180
        assert all(len(v) == 1 for v in by_src.values()), "a source clip spans several splits"

    def test_group_by_source_off_scatters(self, cls, in_tmp_cwd):
        _run(cls, self._samples(60, copies=2), {"output_dir": "out", "group_by_source": False})
        meta = json.loads((in_tmp_cwd / "out/v1/metadata.json").read_text())
        by_src: dict[str, set] = {}
        for m in meta:
            by_src.setdefault("_".join(Path(m["path"]).stem.split("_")[:2]), set()).add(m["split"])
        assert any(len(v) > 1 for v in by_src.values())

    def test_group_split_is_stable_across_runs(self, cls, in_tmp_cwd):
        _run(cls, self._samples(30), {"output_dir": "a"})
        _run(cls, list(reversed(self._samples(30))), {"output_dir": "b"})
        a = {r["path"]: r["split"] for r in _labels_csv(in_tmp_cwd / "a/v1")}
        b = {r["path"]: r["split"] for r in _labels_csv(in_tmp_cwd / "b/v1")}
        assert a == b

    def test_append_accumulates_labels(self, cls, in_tmp_cwd):
        _run(cls, self._samples(10, "yes"), {"output_dir": "out", "append": False})
        _run(cls, self._samples(10, "no"), {"output_dir": "out", "append": True})
        rows = _labels_csv(in_tmp_cwd / "out/v1")
        assert len(rows) == 20 and {r["label"] for r in rows} == {"yes", "no"}
        assert sorted(int(r["id"]) for r in rows) == list(range(20))

    def test_append_false_replaces_version_dir(self, cls, in_tmp_cwd):
        _run(cls, self._samples(10, "yes"), {"output_dir": "out"})
        _run(cls, self._samples(4, "no"), {"output_dir": "out", "append": False})
        rows = _labels_csv(in_tmp_cwd / "out/v1")
        assert len(rows) == 4 and not (in_tmp_cwd / "out/v1/train/yes").exists()

    def test_version_tag_dir(self, cls, in_tmp_cwd):
        _run(cls, self._samples(3), {"output_dir": "out", "version_tag": "v2.1.0"})
        assert (in_tmp_cwd / "out/v2.1.0/labels.csv").is_file()

    def test_project_overrides_output_dir(self, cls, in_tmp_cwd):
        _run(cls, self._samples(3), {"output_dir": "ignored", "project": "e06-unit"})
        root = in_tmp_cwd / "workspace/datasets/output/e06-unit"
        assert (root / "v1/labels.csv").is_file()
        assert json.loads((root / "project.json").read_text())["versions"] == ["v1"]

    def test_random_seed_changes_assignment(self, cls, in_tmp_cwd):
        _run(cls, self._samples(60), {"output_dir": "a", "random_seed": 1})
        _run(cls, self._samples(60), {"output_dir": "b", "random_seed": 2})
        a = {r["path"]: r["split"] for r in _labels_csv(in_tmp_cwd / "a/v1")}
        b = {r["path"]: r["split"] for r in _labels_csv(in_tmp_cwd / "b/v1")}
        assert a != b

    def test_refuses_outside_cwd(self, cls, in_tmp_cwd):
        with pytest.raises(ValueError, match="outside the workspace"):
            _run(cls, self._samples(1), {"output_dir": "/tmp/../etc/e06"})

    @pytest.mark.parametrize("bad", [
        {"version_tag": "latest"}, {"split_ratios": {}}, {"split_ratios": {"train": -0.1, "test": 1.1}},
        {"split_ratios": {"train": 0, "test": 0}}, {"split_ratios": {"train": "a"}}, {"format": "mp3"},
    ])
    def test_invalid_config_rejected(self, cls, bad):
        with pytest.raises(Exception):
            cls.Config(**bad)


# ── feature_frontend ─────────────────────────────────────────────────────────


class TestFeatureFrontend:
    @pytest.fixture(scope="class")
    def cls(self):
        return _load("feature_frontend")

    def _one(self, cls, y=None, sr=SR, **cfg):
        (fa,) = _run(cls, [_sample(_speechlike() if y is None else y, sr=sr)], cfg)
        return fa

    def test_ex06_mfcc_shape_101x40(self, cls):
        graph = json.loads((ROOT / "examples/06_speech_commands_e2e/pipeline_infer.graph.json").read_text())
        cfg = next(n["config"] for n in graph["nodes"] if n["node_type"] == "feature_frontend")
        fa = self._one(cls, **cfg)
        assert fa.data.shape == (101, 40) and fa.feature_type == "mfcc"
        assert abs(float(np.mean(fa.data))) < 1e-4 and float(np.std(fa.data)) == pytest.approx(1.0, abs=1e-3)

    @pytest.mark.parametrize("ft,width", [
        ("log_mel", 80), ("mfcc", 13), ("spectrogram", 257), ("chroma", 12),
        ("zcr", 1), ("spectral_centroid", 1), ("spectral_rolloff", 1),
    ])
    def test_feature_types_shapes(self, cls, ft, width):
        fa = self._one(cls, feature_type=ft)
        assert fa.data.shape == (101, width) and fa.metadata["feature_type"] == ft

    def test_raw_passthrough(self, cls):
        y = _speechlike()
        fa = self._one(cls, y=y, feature_type="raw")
        # (1, N) from the extractor is transposed to (T=N, F=1) like every other type
        assert fa.data.shape == (len(y), 1) and fa.metadata["normalized"] is False

    @pytest.mark.parametrize("fixed", [50, 150])
    def test_fixed_length_pads_or_truncates(self, cls, fixed):
        fa = self._one(cls, feature_type="mfcc", n_mfcc=40, fixed_length=fixed)
        assert fa.data.shape == (fixed, 40)

    def test_resamples_to_sample_rate(self, cls):
        fa = self._one(cls, y=_tone(1.0, sr=8000), sr=8000, feature_type="mfcc")
        assert fa.sample_rate == SR and fa.data.shape[0] == 101

    def test_hop_length_controls_frames(self, cls):
        assert self._one(cls, hop_length=320).data.shape[0] == 51

    def test_center_off_drops_edge_frames(self, cls):
        assert self._one(cls, feature_type="mfcc", center=False).data.shape[0] < 101

    def test_mfcc_honours_fmax(self, cls):
        """Regression: fmin/fmax were ignored for mfcc (only log_mel used them)."""
        a = self._one(cls, feature_type="mfcc", n_mfcc=20, fmax=8000.0, normalize=False).data
        b = self._one(cls, feature_type="mfcc", n_mfcc=20, fmax=2000.0, normalize=False).data
        assert not np.allclose(a, b)

    def test_log_scale_toggle_for_log_mel(self, cls):
        db = self._one(cls, feature_type="log_mel", normalize=False, log_scale=True).data
        lin = self._one(cls, feature_type="log_mel", normalize=False, log_scale=False).data
        assert db.max() <= 0.0 + 1e-5 and lin.min() >= 0.0

    def test_normalize_toggle(self, cls):
        off = self._one(cls, feature_type="mfcc", normalize=False).data
        assert abs(float(np.mean(off))) > 1.0

    @pytest.mark.parametrize("delta,dd,width", [(True, False, 26), (False, True, 26), (True, True, 39)])
    def test_deltas(self, cls, delta, dd, width):
        fa = self._one(cls, feature_type="mfcc", delta=delta, delta_delta=dd)
        assert fa.data.shape == (101, width)

    @pytest.mark.parametrize("bad", [
        {"win_length": 1024, "n_fft": 512}, {"feature_type": "mfcc", "n_mfcc": 100, "n_mels": 40},
        {"fmax": 9000.0}, {"fmax": 0}, {"fixed_length": -1}, {"hop_length": 0}, {"feature_type": "mel"},
    ])
    def test_invalid_config_rejected(self, cls, bad):
        with pytest.raises(Exception):
            cls.Config(**bad)


def test_ingest_warns_when_falling_back(tmp_path, caplog, monkeypatch):
    """Missing Phase-1 dataset silently fell back to the bundled raw clips.

    Now it is an error by default ("has not been produced yet"); the raw-clip
    fallback needs GRAPHYN_INGEST_EXAMPLE_FALLBACK=1 and is logged.
    """
    cls = _load("dataset_ingest")
    monkeypatch.chdir(tmp_path)
    missing = "workspace/artifacts/speech-commands/dataset/speech_commands/v_missing"
    monkeypatch.delenv("GRAPHYN_INGEST_EXAMPLE_FALLBACK", raising=False)
    with pytest.raises(ValueError, match="has not been produced yet"):
        cls(config={"path": missing, "recursive": True, "limit": 1}).process({})
    monkeypatch.setenv("GRAPHYN_INGEST_EXAMPLE_FALLBACK", "1")
    out = cls(config={"path": missing, "recursive": True, "limit": 1}).process({})["output"]
    # falls back to examples/02_speech_commands/data (one clip per label with limit=1)
    assert {s.label for s in out} == {"yes", "no", "up", "down", "go", "stop"}
    assert any("fallback directory" in r.getMessage() for r in caplog.records)
    caplog.clear()
    d = tmp_path / "real"
    d.mkdir()
    sf.write(d / "a.wav", _tone(0.2), SR)
    cls(config={"path": str(d), "recursive": False}).process({})
    assert not any("fallback directory" in r.getMessage() for r in caplog.records)
