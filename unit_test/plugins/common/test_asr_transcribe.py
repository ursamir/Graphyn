
"""Tests for the asr_transcribe plugin (offline mock, no API keys)."""
from __future__ import annotations

import os

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager
from app.models.audio_sample import AudioSample

PLUGIN_SOURCE = "PluginPackage/Common/asr_transcribe/"
NODE_TYPE = "asr_transcribe"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("asr_transcribe_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


def test_registers(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


def test_metadata(installed_cls):
    meta = installed_cls.metadata
    assert meta.label
    assert meta.category
    assert meta.version


def test_construct(installed_cls):
    node = installed_cls(config={}, seed=0)
    assert node is not None


def _sample(n=16000, sr=16000, **meta):
    data = np.zeros(n, dtype=np.float32)
    return AudioSample(path="/fake/a.wav", sample_rate=sr, data=data, label="x", metadata=meta)


def test_empty_input(installed_cls):
    node = installed_cls(config={"provider": "mock"}, seed=0)
    result = node.process({"input": []})["output"]
    assert result.text == ""


def test_mock_deterministic(installed_cls):
    node = installed_cls(config={"provider": "mock", "language": "en"}, seed=0)
    sample = _sample(n=16000)
    a = node.process({"input": [sample]})["output"]
    b = node.process({"input": [sample]})["output"]
    assert a.text == b.text
    assert a.language == "en"
    assert a.words
    assert a.words[0].start == 0.0
    assert a.words[-1].end > 0


def test_mock_uses_metadata_transcript(installed_cls):
    node = installed_cls(config={"provider": "mock"}, seed=0)
    sample = _sample(n=8000, transcript="hello world")
    result = node.process({"input": [sample]})["output"]
    assert result.text == "hello world"
    assert len(result.words) == 2


def test_http_provider_missing_key(installed_cls):
    os.environ.pop("OPENAI_API_KEY", None)
    node = installed_cls(config={"provider": "openai_compat"}, seed=0)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        node.process({"input": [_sample()]})


def test_default_provider_is_not_mock(installed_cls, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    node = installed_cls(config={}, seed=0)
    assert (node.config.provider or "").lower() != "mock"
    assert node.config.provider == "openai_compat"
    sample = _sample()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        node.process({"input": [sample]})


def test_assemblyai_polls_until_completed(installed_cls, tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "aa-test")
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")
    sample = _sample()
    sample.path = str(wav)
    node = installed_cls(config={"provider": "assemblyai", "timeout_s": 5}, seed=0)

    upload = MagicMock()
    upload.json.return_value = {"upload_url": "https://cdn.example/a"}
    upload.raise_for_status = MagicMock()
    created = MagicMock()
    created.json.return_value = {"id": "tr_1", "status": "queued"}
    created.raise_for_status = MagicMock()
    done = MagicMock()
    done.json.return_value = {
        "id": "tr_1",
        "status": "completed",
        "text": "hello there",
        "words": [{"text": "hello", "start": 0, "end": 400}, {"text": "there", "start": 400, "end": 800}],
    }
    done.raise_for_status = MagicMock()

    def fake_post(url, **kwargs):
        if url.endswith("/upload"):
            return upload
        if url.endswith("/transcript"):
            return created
        raise AssertionError(url)

    def fake_get(url, **kwargs):
        assert "tr_1" in url
        return done

    with patch("httpx.post", side_effect=fake_post), patch("httpx.get", side_effect=fake_get), patch("time.sleep"):
        out = node.process({"input": [sample]})["output"]
    assert out.text == "hello there"
    assert out.metadata.get("status") == "completed"
    assert len(out.words) == 2
