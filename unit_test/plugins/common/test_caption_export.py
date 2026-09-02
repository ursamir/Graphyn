
"""Tests for the caption_export plugin."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/caption_export/"
NODE_TYPE = "caption_export"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("caption_export_plugins")
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
    out = node.process({"input": None})["output"]
    assert out.paths == []


def test_writes_srt_vtt_json(installed_cls, tmp_path):
    node = installed_cls(
        config={
            "output_dir": str(tmp_path / "caps"),
            "basename": "talk",
            "formats": ["srt", "vtt", "json"],
            "max_words_per_cue": 2,
        },
        seed=0,
    )
    tr = {
        "text": "hello world there",
        "words": [
            {"word": "hello", "start": 0.0, "end": 0.4, "speaker": "A"},
            {"word": "world", "start": 0.4, "end": 0.8, "speaker": "A"},
            {"word": "there", "start": 0.8, "end": 1.2, "speaker": "B"},
        ],
    }
    out = node.process({"input": tr})["output"]
    assert out.n_cues >= 2
    paths = {Path(p).suffix: Path(p) for p in out.paths}
    assert paths[".srt"].is_file()
    assert paths[".vtt"].is_file()
    assert paths[".json"].is_file()
    srt = paths[".srt"].read_text(encoding="utf-8")
    assert "-->" in srt
    vtt = paths[".vtt"].read_text(encoding="utf-8")
    assert vtt.startswith("WEBVTT")
