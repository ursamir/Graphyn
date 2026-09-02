
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
