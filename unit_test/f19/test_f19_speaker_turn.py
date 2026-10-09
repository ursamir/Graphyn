"""F19 (F-17): segmenter speaker_turn runs real offline diarization."""
from __future__ import annotations

import collections
import glob
import os

import numpy as np
import pytest

librosa = pytest.importorskip("librosa")

from app.core.plugins.manager import PluginManager
from app.models.audio_sample import AudioSample
from unit_test.plugins._helpers import materialize_isolated_class

SR = 16000
_DATA = "examples/02_speech_commands/data"


@pytest.fixture(scope="module")
def seg_cls(tmp_path_factory):
    from app.core.nodes.registry import NodeRegistry

    tmp = tmp_path_factory.mktemp("seg")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp))
    mgr._plugins_dir = str(tmp)
    mgr.install("PluginPackage/Audio/segmenter/")
    return materialize_isolated_class(reg.get_class("segmenter"))


def _speakers():
    by = collections.defaultdict(list)
    for f in sorted(glob.glob(f"{_DATA}/*/*.wav")):
        by[os.path.basename(f).split("_")[0]].append(f)
    return by


def _conversation(a: list[str], b: list[str], pattern: str = "ABAB", per: int = 4):
    y, truth, t, ia, ib = [], [], 0.0, 0, 0
    for who in pattern:
        parts = []
        for _ in range(per):
            f = a[ia % len(a)] if who == "A" else b[ib % len(b)]
            ia, ib = (ia + 1, ib) if who == "A" else (ia, ib + 1)
            x, _ = librosa.load(f, sr=SR)
            x, _ = librosa.effects.trim(x, top_db=30)
            parts += [x, np.zeros(int(0.08 * SR), np.float32)]
        x = np.concatenate(parts)
        truth.append((t, t + len(x) / SR, who))
        t += len(x) / SR
        y += [x, np.zeros(int(0.5 * SR), np.float32)]
        t += 0.5
    return np.concatenate(y).astype(np.float32), truth


def _accuracy(segments, truth) -> float:
    best = 0.0
    labs = sorted({s.metadata["speaker_id"] for s in segments})
    for first in labs:
        hit = tot = 0.0
        for s0, e0, who in truth:
            for s in segments:
                o = min(e0, s.metadata["end"]) - max(s0, s.metadata["start"])
                if o > 0:
                    tot += o
                    hit += o if ((s.metadata["speaker_id"] == first) == (who == "A")) else 0
        best = max(best, hit / tot if tot else 0)
    return best


def test_two_real_speakers_are_separated(seg_cls):
    by = _speakers()
    if len(by.get("893705bb", [])) < 8 or len(by.get("4c6167ca", [])) < 8:
        pytest.skip("bundled speech-commands clips not present")
    y, truth = _conversation(by["893705bb"], by["4c6167ca"])
    node = seg_cls(config={"mode": "speaker_turn", "num_speakers": 2}, seed=0)
    out = node.process({"input": [AudioSample(path="conv.wav", sample_rate=SR, data=y)]})["output"]
    assert {s.metadata["speaker_id"] for s in out} == {"spk0", "spk1"}
    assert all(s.metadata["diarization"] == "offline" for s in out)
    assert _accuracy(out, truth) >= 0.9
    # turns alternate A B A B → speaker of first and third turn match
    starts = sorted(out, key=lambda s: s.metadata["start"])
    assert starts[0].metadata["speaker_id"] == "spk0"


def test_auto_speaker_count_on_clear_pair(seg_cls):
    by = _speakers()
    if len(by.get("893705bb", [])) < 8 or len(by.get("4c6167ca", [])) < 8:
        pytest.skip("bundled speech-commands clips not present")
    y, truth = _conversation(by["893705bb"], by["4c6167ca"])
    out = seg_cls(config={"mode": "speaker_turn"}, seed=0).process(
        {"input": [AudioSample(path="conv.wav", sample_rate=SR, data=y)]}
    )["output"]
    info = out[0].metadata["diarization_info"]
    assert info["k"] == 2 and info["method"].startswith("mfcc_pitch")


def test_upstream_speaker_segments_win(seg_cls):
    y = np.random.default_rng(0).normal(0, 0.1, SR * 3).astype(np.float32)
    s = AudioSample(path="x.wav", sample_rate=SR, data=y,
                    metadata={"speaker_segments": [{"start": 0, "end": 1.5, "speaker_id": "alice"},
                                                   {"start": 1.5, "end": 3, "speaker_id": "bob"}]})
    out = seg_cls(config={"mode": "speaker_turn"}, seed=0).process({"input": [s]})["output"]
    assert [o.metadata["speaker_id"] for o in out] == ["alice", "bob"]
    assert out[0].metadata["diarization"] == "upstream"


def test_silence_only_gives_no_turns(seg_cls):
    s = AudioSample(path="q.wav", sample_rate=SR, data=np.zeros(SR * 2, np.float32) + 1e-6)
    out = seg_cls(config={"mode": "speaker_turn"}, seed=0).process({"input": [s]})["output"]
    assert out == [] or all(o.metadata["diarization"] == "offline" for o in out)
