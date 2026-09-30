"""stream_ingest rtp/rtsp: URL validation, credential redaction, -t handling,
protocol whitelist and trailing partial chunk (ffmpeg subprocess mocked)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "PluginPackage" / "Audio" / "stream_ingest"

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


@pytest.fixture(scope="module")
def mod():
    return AutoDiscovery(NodeRegistry())._import_file(PLUGIN / "nodes.py", package_prefix=None)


class _FakeRun:
    def __init__(self, stdout: bytes = b"", returncode: int = 0, stderr: bytes = b""):
        self.calls: list[dict] = []
        self._out = subprocess.CompletedProcess([], returncode, stdout, stderr)

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": list(cmd), **kwargs})
        return self._out


@pytest.fixture
def fake_ffmpeg(mod, monkeypatch):
    def _install(**kw):
        fake = _FakeRun(**kw)
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/ffmpeg")
        monkeypatch.setattr(mod.subprocess, "run", fake)
        return fake

    return _install


def _node(mod, **cfg):
    base = {"source": "rtsp", "sample_rate": 1000, "chunk_ms": 100, "channels": 1}
    base.update(cfg)
    return mod.StreamIngestNode(config=base)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://example.com/a.wav",
        "https://example.com/a.wav",
        "concat:a.wav|b.wav",
        "subfile,,start,0,end,0,,:/etc/passwd",
        "/etc/passwd",
        "rtsp:///nohost",
    ],
)
def test_rejects_disallowed_urls_before_ffmpeg(mod, fake_ffmpeg, url):
    fake = fake_ffmpeg(stdout=np.zeros(10, np.float32).tobytes())
    with pytest.raises(ValueError):
        _node(mod, stream_url=url).process({})
    assert fake.calls == []


@pytest.mark.parametrize(
    "url,whitelist",
    [
        ("rtsp://cam.local:554/stream", "rtsp,rtp,udp,tcp"),
        ("rtp://239.0.0.1:5004", "rtp,udp"),
        ("udp://0.0.0.0:1234", "udp"),
        ("srt://host:9000", "srt,udp"),
    ],
)
def test_allowed_schemes_pass_protocol_whitelist(mod, fake_ffmpeg, url, whitelist):
    fake = fake_ffmpeg(stdout=np.zeros(100, np.float32).tobytes())
    _node(mod, stream_url=url).process({})
    cmd = fake.calls[0]["cmd"]
    i = cmd.index("-protocol_whitelist")
    assert cmd[i + 1] == whitelist
    assert i < cmd.index("-i")


def test_duration_zero_omits_t_and_timeout(mod, fake_ffmpeg):
    fake = fake_ffmpeg(stdout=np.zeros(100, np.float32).tobytes())
    _node(mod, stream_url="rtsp://cam/s", duration_s=0).process({})
    assert "-t" not in fake.calls[0]["cmd"]
    assert fake.calls[0]["timeout"] is None


def test_duration_positive_sets_t(mod, fake_ffmpeg):
    fake = fake_ffmpeg(stdout=np.zeros(100, np.float32).tobytes())
    _node(mod, stream_url="rtsp://cam/s", duration_s=2.5).process({})
    cmd = fake.calls[0]["cmd"]
    assert cmd[cmd.index("-t") + 1] == "2.5"


def test_credentials_redacted_from_outputs(mod, fake_ffmpeg):
    url = "rtsp://admin:s3cret@cam.local:554/live"
    fake = fake_ffmpeg(stdout=np.zeros(250, np.float32).tobytes())
    chunks = _node(mod, stream_url=url).process({})["output"]
    assert fake.calls[0]["cmd"][fake.calls[0]["cmd"].index("-i") + 1] == url  # ffmpeg gets the real URL
    for c in chunks:
        blob = f"{c.path} {c.metadata}"
        assert "s3cret" not in blob and "admin" not in blob
        assert c.path == "rtsp://***@cam.local:554/live"


def test_credentials_redacted_from_errors(mod, fake_ffmpeg):
    url = "rtsp://admin:s3cret@cam.local/live"
    fake_ffmpeg(returncode=1, stderr=f"{url}: 401 Unauthorized (admin:s3cret@)".encode())
    with pytest.raises(RuntimeError) as ei:
        _node(mod, stream_url=url).process({})
    assert "s3cret" not in str(ei.value) and "admin" not in str(ei.value)


def test_rejected_url_error_redacts(mod, fake_ffmpeg):
    fake_ffmpeg()
    with pytest.raises(ValueError) as ei:
        _node(mod, stream_url="rtsp://admin:s3cret@/x").process({})
    assert "s3cret" not in str(ei.value)


def test_trailing_partial_chunk_kept(mod, fake_ffmpeg):
    # 250 samples at 1 kHz, 100 ms chunks -> 100, 100, 50
    fake_ffmpeg(stdout=np.arange(250, dtype=np.float32).tobytes())
    chunks = _node(mod, stream_url="rtp://239.0.0.1:5004", source="rtp").process({})["output"]
    assert [len(c.data) for c in chunks] == [100, 100, 50]
    assert chunks[-1].metadata["partial"] is True
    assert chunks[-1].metadata["end_s"] == pytest.approx(0.25)


def test_plugin_toml_in_sync_with_config(mod):
    data = tomllib.loads((PLUGIN / "plugin.toml").read_text())
    schema = data["config_schema"]["stream_ingest"]
    assert set(schema["source"]["enum"]) == {"microphone", "websocket", "file_stream", "rtp", "rtsp"}
    assert "stream_url" in schema
    props = mod.StreamIngestNode.Config.model_json_schema()["properties"]
    assert set(props["source"]["enum"]) == set(schema["source"]["enum"])
    assert set(props) - {"stub"} <= set(schema)
