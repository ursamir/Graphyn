
"""Tests for the asr_transcribe plugin (real providers only; no product mock mode)."""
from __future__ import annotations

import os

import numpy as np
import pytest
from pydantic import ValidationError

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
    node = installed_cls(config={"provider": "openai_compat"}, seed=0)
    result = node.process({"input": []})["output"]
    assert result.text == ""


def test_mock_provider_rejected(installed_cls):
    with pytest.raises((ValidationError, ValueError, RuntimeError)):
        installed_cls(config={"provider": "mock"}, seed=0)


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


def test_local_whisper_provider_accepted(installed_cls):
    node = installed_cls(config={"provider": "local_whisper", "model": "tiny"}, seed=0)
    assert node.config.provider == "local_whisper"


def test_faster_whisper_alias_accepted(installed_cls):
    node = installed_cls(config={"provider": "faster_whisper", "model": "tiny"}, seed=0)
    assert node.config.provider == "faster_whisper"


def test_local_whisper_mocked_model(installed_cls, tmp_path):
    """Unit test with a mocked WhisperModel — no heavy download."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch
    import importlib

    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 64)
    sample = _sample()
    sample.path = str(wav)

    word = SimpleNamespace(word="hello", start=0.0, end=0.4)
    seg = SimpleNamespace(text=" hello", words=[word])
    info = SimpleNamespace(language="en")
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([seg]), info)

    node = installed_cls(config={"provider": "local_whisper", "model": "tiny"}, seed=0)
    mod = importlib.import_module(type(node).__module__)
    if hasattr(mod, "_WHISPER_MODELS"):
        mod._WHISPER_MODELS.clear()

    with patch("faster_whisper.WhisperModel", return_value=fake_model):
        out = node.process({"input": [sample]})["output"]
    assert out.text.strip() == "hello"
    assert out.metadata.get("provider") == "local_whisper"
    assert len(out.words) == 1
    assert out.words[0].word == "hello"


def test_openai_compat_groq_key_fallback(installed_cls, tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")
    sample = _sample()
    sample.path = str(wav)
    node = installed_cls(
        config={
            "provider": "openai_compat",
            "base_url": "https://api.groq.com/openai/v1",
            "model": "whisper-large-v3-turbo",
        },
        seed=0,
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"text": "hi", "language": "en", "words": []}

    with patch("httpx.post", return_value=mock_resp) as post:
        out = node.process({"input": [sample]})["output"]
    assert out.text == "hi"
    headers = post.call_args.kwargs.get("headers") or {}
    assert headers.get("Authorization") == "Bearer gsk-test"
