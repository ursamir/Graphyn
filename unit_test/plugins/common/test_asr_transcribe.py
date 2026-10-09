
"""Tests for the asr_transcribe plugin (real providers only; no product mock mode)."""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

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
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


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


def test_default_provider_is_local_whisper(installed_cls, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    node = installed_cls(config={}, seed=0)
    assert node.config.provider == "local_whisper"


def test_every_sample_transcribed_and_merged(installed_cls, monkeypatch):
    """All samples are transcribed (not just the first); timings share one timeline."""
    seen = []

    def fake_local(self, samples, *, provider_label="local_whisper"):
        seen.append(samples[0].metadata["i"])
        i = samples[0].metadata["i"]
        return self_types.Transcript(text=f"t{i}", language="en",
                                     words=[self_types.WordTiming(word=f"w{i}", start=0.1, end=0.4)])

    import sys
    self_types = sys.modules[installed_cls.__module__]
    monkeypatch.setattr(installed_cls, "_local_whisper", fake_local)
    node = installed_cls(config={}, seed=0)
    out = node.process({"input": [_sample(i=0), _sample(n=32000, i=1), _sample(i=2)]})["output"]
    assert seen == [0, 1, 2]
    assert out.text == "t0\nt1\nt2"
    assert [round(w.start, 3) for w in out.words] == [0.1, 1.1, 3.1]
    items = out.metadata["items"]
    assert [it["text"] for it in items] == ["t0", "t1", "t2"]
    assert [it["offset_s"] for it in items] == [0.0, 1.0, 3.0]
    single = node.process({"input": [_sample(i=7)]})["output"]
    assert single.text == "t7" and "items" not in single.metadata


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

    # faster-whisper lives in the plugin's isolated venv, not the host venv, so
    # inject a stub module rather than patching a (possibly) missing import.
    import sys
    fake_fw = SimpleNamespace(WhisperModel=MagicMock(return_value=fake_model))
    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
        out = node.process({"input": [sample]})["output"]
    assert out.text.strip() == "hello"
    assert out.metadata.get("provider") == "local_whisper"
    assert len(out.words) == 1
    assert out.words[0].word == "hello"


def test_openai_compat_groq_key_fallback(installed_cls, tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    # ASR-BASE-URL-BINDING-1: an env key is only sent to a node base_url that is
    # bound to it (provider default) or allowlisted — Groq must be allowlisted.
    monkeypatch.setenv("GRAPHYN_LLM_BASE_URL_ALLOWLIST", "api.groq.com")
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


def test_openai_compat_refuses_key_to_unbound_base_url(installed_cls, tmp_path, monkeypatch):
    """ASR-BASE-URL-BINDING-1: env OPENAI_API_KEY never goes to an arbitrary host."""
    from unittest.mock import patch

    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("GRAPHYN_LLM_BASE_URL_ALLOWLIST", raising=False)
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")
    sample = _sample()
    sample.path = str(wav)
    node = installed_cls(
        config={"provider": "openai_compat", "base_url": "https://evil.example.com/v1"},
        seed=0,
    )
    # Egress DNS policy is tested elsewhere; isolate the key<->base_url binding.
    import sys
    monkeypatch.setattr(sys.modules[installed_cls.__module__], "validate_http_egress_url", lambda url: None)
    with patch("httpx.post") as post:
        with pytest.raises(RuntimeError, match="base_url"):
            node.process({"input": [sample]})
    post.assert_not_called()


def test_openai_compat_default_base_uses_bound_endpoint(installed_cls, tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("OPENAI_API_KEY", "sk-ok")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")
    sample = _sample()
    sample.path = str(wav)
    node = installed_cls(config={"provider": "openai_compat"}, seed=0)
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"text": "ok", "language": "en", "words": []}
    with patch("httpx.post", return_value=mock_resp) as post:
        out = node.process({"input": [sample]})["output"]
    assert out.text == "ok"
    assert post.call_args.args[0] == "https://api.openai.com/v1/audio/transcriptions"
    assert (post.call_args.kwargs.get("headers") or {}).get("Authorization") == "Bearer sk-ok"
