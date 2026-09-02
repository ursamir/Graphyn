
"""Tests for the pii_redact plugin (regex fallback, no presidio)."""
from __future__ import annotations

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager
from app.models.audio_sample import AudioSample

PLUGIN_SOURCE = "PluginPackage/Common/pii_redact/"
NODE_TYPE = "pii_redact"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("pii_redact_plugins")
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
    assert meta.label and meta.category and meta.version


def test_empty_input(installed_cls):
    node = installed_cls(config={}, seed=0)
    out = node.process({"transcript": None, "audio": None})
    assert out["audit"].n_redacted == 0


def test_regex_email_phone_card(installed_cls):
    node = installed_cls(config={"engine": "regex"}, seed=0)
    text = "Contact ada@example.com or +1-415-555-0100. Card 4111 1111 1111 1111."
    tr = {"text": text, "language": "en", "words": []}
    out = node.process({"transcript": tr})
    red = out["transcript"]["text"]
    assert "ada@example.com" not in red
    assert "4111 1111 1111 1111" not in red
    assert out["audit"].n_redacted >= 2


def test_silence_audio_spans(installed_cls):
    node = installed_cls(config={"engine": "regex"}, seed=0)
    sr = 1000
    data = np.ones(3000, dtype=np.float32)
    sample = AudioSample(path="/fake/a.wav", sample_rate=sr, data=data)
    words = [
        {"word": "hello", "start": 0.0, "end": 1.0, "speaker": ""},
        {"word": "ada@example.com", "start": 1.0, "end": 2.0, "speaker": ""},
        {"word": "bye", "start": 2.0, "end": 3.0, "speaker": ""},
    ]
    tr = {"text": "hello ada@example.com bye", "words": words}
    out = node.process({"transcript": tr, "audio": [sample]})
    audio = out["audio"][0]
    # middle second silenced
    mid = audio.data[1000:2000]
    assert float(np.max(np.abs(mid))) == 0.0
    assert float(audio.data[0]) == 1.0
