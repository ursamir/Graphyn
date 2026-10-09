# unit_test/plugins/video/test_video_pack.py
"""Video pack (PluginPackage/Video) — real ffmpeg-backed behaviour.

Synthetic test media is generated with ffmpeg's lavfi sources (no network):
two visually different 2 s scenes + a 1 s black tail, with a sine soundtrack.
CLIP / Kinetics model tests are ``heavy`` (GRAPHYN_RUN_HEAVY=1, weights
download once). The caption node is tested against a patched LLM client.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")

PLUGINS = ["video_ingest", "video_quality_gate", "scene_detect", "clip_segment", "frame_sample",
           "video_caption", "video_embed", "action_classify", "av_align", "video_exporter"]


@pytest.fixture(scope="module")
def classes(tmp_path_factory):
    from app.core.nodes.registry import NodeRegistry

    tmp = tmp_path_factory.mktemp("video_plugins")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp))
    mgr._plugins_dir = str(tmp)
    for p in PLUGINS:
        mgr.install(f"PluginPackage/Video/{p}/")
    return {p: materialize_isolated_class(reg.get_class(p)) for p in PLUGINS}


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    (d / "in").mkdir()
    video = d / "in" / "demo.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=2",
        "-f", "lavfi", "-i", "mandelbrot=size=160x120:rate=10",
        "-f", "lavfi", "-i", "color=c=black:size=160x120:rate=10:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=5",
        "-filter_complex", "[1:v]trim=duration=2,setpts=PTS-STARTPTS[m];[0:v][m][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video),
    ], check=True)
    (d / "in" / "notes.txt").write_text("not a video")
    return d


def run(cls, cfg, inputs):
    node = cls(config=cfg, seed=0)
    if hasattr(node, "setup"):
        node.setup()
    return node.process(inputs)


def test_all_register(classes):
    assert set(classes) == set(PLUGINS)
    for cls in classes.values():
        fields = cls.Config.model_fields
        assert "stub" not in fields  # no placeholder mode anywhere


def test_ingest_probes(classes, media):
    out = run(classes["video_ingest"], {"path": str(media / "in")}, {})["output"]
    assert len(out) == 1
    v = out[0]
    assert abs(v.duration_s - 5.0) < 0.3 and v.fps == 10.0 and (v.width, v.height) == (160, 120)
    assert v.has_audio and v.codec == "h264"


def test_ingest_missing_path_is_clear(classes, tmp_path):
    with pytest.raises(FileNotFoundError):
        run(classes["video_ingest"], {"path": str(tmp_path / "nope")}, {})
    with pytest.raises(ValueError, match="config.path is required"):
        run(classes["video_ingest"], {}, {})


def test_quality_gate_measures_black(classes, media):
    vids = run(classes["video_ingest"], {"path": str(media / "in")}, {})["output"]
    ok = run(classes["video_quality_gate"], {"max_black_ratio": 0.5}, {"input": vids})
    q = ok["output"][0].metadata["quality"]
    assert q["pass"] and 0.1 < q["black_ratio"] < 0.35  # ~1 s of 5 s
    strict = run(classes["video_quality_gate"], {"max_black_ratio": 0.1}, {"input": vids})
    assert not strict["output"] and len(strict["rejected"]) == 1
    assert "black" in strict["rejected"][0].metadata["quality"]["reasons"][0]
    with pytest.raises(ValueError, match="failed"):
        run(classes["video_quality_gate"], {"min_width": 640, "rejection_policy": "fail"}, {"input": vids})


def test_scenes_clips_frames(classes, media, tmp_path):
    vids = run(classes["video_ingest"], {"path": str(media / "in")}, {})["output"]
    scenes = run(classes["scene_detect"], {"threshold": 0.3, "min_scene_len_s": 0.5}, {"input": vids})["output"]
    cuts = [s.start_s for s in scenes]
    assert cuts[0] == 0.0 and any(abs(c - 2.0) < 0.25 for c in cuts) and any(abs(c - 4.0) < 0.25 for c in cuts)
    clips = run(classes["clip_segment"], {"output_dir": str(tmp_path / "clips")}, {"video": vids, "scenes": scenes})["output"]
    assert len(clips) == len(scenes)
    assert all((tmp_path / "clips").joinpath(c.path.split("/")[-1]).is_file() for c in clips)
    assert abs(sum(c.duration_s for c in clips) - vids[0].duration_s) < 0.3
    virt = run(classes["clip_segment"], {"mode": "fixed", "window_s": 2, "write_files": False}, {"video": vids})["output"]
    assert [(c.start_s, c.end_s) for c in virt][:2] == [(0.0, 2.0), (2.0, 4.0)]
    with pytest.raises(ValueError, match="mode=scenes"):
        run(classes["clip_segment"], {}, {"video": vids})
    frames = run(classes["frame_sample"], {"mode": "fps", "fps": 2, "output_dir": str(tmp_path / "f")}, {"input": vids})["output"]
    assert len(frames) == 10 and [f.timestamp_s for f in frames[:3]] == [0.0, 0.5, 1.0]
    uni = run(classes["frame_sample"], {"mode": "uniform", "num_frames": 2, "output_dir": str(tmp_path / "u")}, {"input": clips[1:2]})["output"]
    # Timestamps are on the source timeline even though the clip is its own file.
    assert clips[1].metadata["source_start_s"] <= uni[0].timestamp_s < uni[1].timestamp_s <= clips[1].metadata["source_end_s"]
    every = run(classes["frame_sample"], {"mode": "every_n", "every_n": 10, "output_dir": str(tmp_path / "e")}, {"input": vids})["output"]
    assert [round(f.timestamp_s) for f in every] == [0, 1, 2, 3, 4]


def test_av_align_extract_and_xcorr(classes, media):
    from app.models.audio_sample import AudioSample

    vids = run(classes["video_ingest"], {"path": str(media / "in")}, {})["output"]
    ext = run(classes["av_align"], {}, {"video": vids})
    a = ext["audio"][0]
    assert a.sample_rate == 16000 and abs(a.data.size - 80000) < 1600
    spec = np.abs(np.fft.rfft(a.data))
    assert abs(np.argmax(spec) * 16000 / a.data.size - 440) < 5
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(16000 * 6).astype(np.float32) * 0.3
    # A broadband external recording that carries the noise burst 150 ms later.
    vid_mod = vids[0].model_copy()
    import importlib

    vio = importlib.import_module(classes["av_align"].__module__.rsplit(".", 1)[0] + "._vio")
    track = vio.audio_pcm(vids[0].path, sample_rate=16000)
    rec = np.concatenate([np.zeros(2400, np.float32), track + noise[: track.size]])
    # Put the same noise into "video" audio via a patched decoder so both share content.
    orig = vio.audio_pcm
    vio.audio_pcm = lambda *a, **k: (lambda y: y + noise[: y.size])(orig(*a, **k))
    try:
        out = run(classes["av_align"], {"method": "xcorr", "max_offset_ms": 500},
                  {"video": [vid_mod], "audio": [AudioSample(path="/ext.wav", sample_rate=16000, data=rec)]})
    finally:
        vio.audio_pcm = orig
    r = out["output"][0]
    assert abs(r.offset_ms - 150.0) < 1.0 and r.confidence > 5
    with pytest.raises(ValueError, match="needs recordings"):
        run(classes["av_align"], {"method": "xcorr"}, {"video": vids})


def test_caption_uses_llm_client(classes, media, tmp_path, monkeypatch):
    import app.core.ml.llm_client as lc

    seen = []

    def fake_chat(**kw):
        seen.append(kw)
        return {"content": "a test pattern", "provider": kw["provider"], "model": kw["model"], "base_url": "http://ollama:11434/v1"}

    monkeypatch.setattr(lc, "chat_completion", fake_chat)
    vids = run(classes["video_ingest"], {"path": str(media / "in")}, {})["output"]
    node = classes["video_caption"](config={"frames_per_video": 2}, seed=0)
    out = node.process({"input": vids})
    assert out["output"] == ["a test pattern"] * 2
    assert [round(c.timestamp_s, 2) for c in out["captions"]] == [1.25, 3.75]
    msg = seen[0]["messages"][0]["content"]
    assert msg[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert seen[0]["provider"] == "ollama" and seen[0]["model"] == "moondream"
    calls = node.take_external_calls()
    assert len(calls) == 2 and calls[0]["status"] == 200


def test_caption_needs_credentials_for_hosted(classes, media, monkeypatch):
    from app.core.credentials.errors import NeedsCredentialsError

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    vids = run(classes["video_ingest"], {"path": str(media / "in")}, {})["output"]
    with pytest.raises(NeedsCredentialsError):
        run(classes["video_caption"], {"provider": "openai_compat", "model": "gpt-4o-mini",
                                       "api_secret_name": "F20_TEST_NO_SUCH_KEY", "max_frames": 1}, {"input": vids})


def test_exporter_manifest(classes, media, tmp_path):
    vids = run(classes["video_ingest"], {"path": str(media / "in")}, {})["output"]
    clips = run(classes["clip_segment"], {"mode": "fixed", "window_s": 2.5, "write_files": False}, {"video": vids})["output"]
    from app.models.prediction_result import PredictionResult

    anns = [{"text": "early", "source_path": vids[0].path, "timestamp_s": 1.0},
            {"text": "late", "source_path": vids[0].path, "timestamp_s": 3.0},
            PredictionResult(source_path=vids[0].path, predicted_label="x", metadata={"video_path": "/other.mp4"})]
    out = run(classes["video_exporter"], {"output_dir": str(tmp_path / "exp")}, {"input": clips, "annotations": anns})
    rows = [json.loads(l) for l in open(out["manifest"])]
    assert [r["annotations"][0]["text"] for r in rows] == ["early", "late"]
    assert all((tmp_path / "exp" / r["file"]).is_file() for r in rows)
    assert (tmp_path / "exp" / "manifest.csv").is_file()


@pytest.mark.heavy
def test_embed_clip_and_action(classes, media):
    pytest.importorskip("transformers")
    pytest.importorskip("torchvision")
    vids = run(classes["video_ingest"], {"path": str(media / "in")}, {})["output"]
    emb = run(classes["video_embed"], {"num_frames": 4, "zero_shot_labels": ["a colorful test pattern", "a dog"]}, {"input": vids})["output"]
    assert emb[0].embedding.shape == (512,) and abs(float(np.linalg.norm(emb[0].embedding)) - 1) < 1e-4
    assert set(emb[0].metadata["zero_shot"]) == {"a colorful test pattern", "a dog"}
    preds = run(classes["action_classify"], {"top_k": 3}, {"input": vids})["output"]
    assert len(preds[0].probabilities) == 3 and preds[0].predicted_label
