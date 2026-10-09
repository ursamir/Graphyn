"""Registry coverage for the restored proposed packs (F20).

Video, Agents and WakeWord were restored by user request; RAG, Vision, TinyML
and MLOps stay out of the product (F8 3cc62d7 compose note, F1 docs). Their
old cases (yolo_train, tflm_quantize, vector_store_*, rag_generate,
text_embed, mcu_*, ship_package_create, "stub" process and needs-api checks)
were removed with the packs. Restored nodes must install, register and carry
no opt-in "stub"/placeholder mode.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.nodes.registry import NodeRegistry
from app.core.plugins.manager import PluginManager
from app.core.plugins.venv_manager import PluginVenvManager

REPO = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO / "PluginPackage"
RESTORED_PACKS = ["Video", "Agents", "WakeWord"]
DROPPED_PACKS = ["TinyML", "Vision", "RAG", "MLOps"]


def _tomls():
    for pack in RESTORED_PACKS:
        yield from sorted((PLUGIN_ROOT / pack).glob("*/plugin.toml"))


@pytest.fixture(scope="module")
def restored_registry(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("restored_plugins")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp))
    mgr._plugins_dir = str(tmp)
    installed, failures = [], []
    with patch.object(PluginVenvManager, "ensure", return_value=Path("/tmp/fake-venv/bin/python")):
        for toml in _tomls():
            try:
                mgr.install(str(toml.parent) + "/")
                installed.append(toml.parent.name)
            except Exception as exc:
                failures.append(f"{toml.parent.name}: {type(exc).__name__}: {exc}")
    if failures:
        raise AssertionError("restored plugin install failures:\n" + "\n".join(failures))
    return reg, installed


def test_all_restored_packs_install(restored_registry):
    _, installed = restored_registry
    assert len(installed) == len(list(_tomls())) == 24


@pytest.mark.parametrize(
    "node_type",
    [
        "video_ingest", "scene_detect", "clip_segment", "frame_sample", "video_caption",
        "video_embed", "action_classify", "av_align", "video_quality_gate", "video_exporter",
        "agent_loop", "mcp_tool_call", "memory_store", "tool_router",
        "wakeword_data_gen", "wakeword_feature_extract", "wakeword_train",
        "wakeword_export_onnx", "wakeword_infer",
    ],
)
def test_key_nodes_registered(node_type, restored_registry):
    reg, _ = restored_registry
    assert node_type in {m.node_type for m in reg.list_nodes()}


# Kept Agents plugins (llm_chat, prompt_template, guardrail_filter, hitl_approve,
# output_schema_validate) are owned by the F19 track; their opt-in stub flags are
# listed in docs/reviews/full/F20_REQUESTS.md rather than asserted here.
_F20_RESTORED = {"agent_loop", "mcp_tool_call", "memory_store", "tool_router"}


@pytest.mark.parametrize(
    "toml",
    [t for t in _tomls() if t.parent.parent.name != "Agents" or t.parent.name in _F20_RESTORED],
    ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}",
)
def test_no_stub_mode(toml):
    data = tomllib.loads(toml.read_text())
    for node_type, fields in (data.get("config_schema") or {}).items():
        assert "stub" not in fields, f"{node_type} still exposes a stub/placeholder mode"
    assert "scaffold" not in (toml.parent / "nodes.py").read_text().lower()


def test_dropped_packs_are_absent():
    for pack in DROPPED_PACKS:
        assert not (PLUGIN_ROOT / pack).exists(), f"{pack} should stay out of the product"
