"""Isolated-runtime stubs must see the real list defaults of wakeword_data_gen.

The host builds the Config of an isolated node from an AST scan of nodes.py; a
``default_factory=lambda: [...]`` is read as ``[]`` there, which then fails the
``min_length=1`` check inside the plugin venv. The defaults must be literals.
"""
from __future__ import annotations

from pathlib import Path

from app.core.plugins.isolated_schema import specs_from_source

NODES = Path(__file__).resolve().parents[3] / "PluginPackage" / "WakeWord" / "wakeword_data_gen" / "nodes.py"


def test_isolated_stub_keeps_list_defaults():
    spec = specs_from_source(NODES.read_text(encoding="utf-8"))["wakeword_data_gen"]
    defaults = {name: default for name, _typ, default in spec.config_fields}
    assert defaults["target_phrases"] == ["hey graphyn"]
    assert defaults["length_scales"] == [0.75, 1.0, 1.25]
    assert defaults["noise_scales"] == [0.667, 0.98]
