"""Registry + stub process coverage for newly scaffolded packs."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.nodes.registry import NodeRegistry
from app.core.plugins.manager import PluginManager
from app.core.plugins.venv_manager import PluginVenvManager

REPO = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO / "PluginPackage"
NEW_PACKS = ["TinyML", "Vision", "RAG", "Video", "Agents", "MLOps", "WakeWord"]


@pytest.fixture(scope="module")
def new_packs_registry(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("proposed_plugins")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp))
    mgr._plugins_dir = str(tmp)
    installed = []
    failures: list[str] = []
    with patch.object(PluginVenvManager, "ensure", return_value=Path("/tmp/fake-venv/bin/python")):
        for pack in NEW_PACKS:
            root = PLUGIN_ROOT / pack
            if not root.is_dir():
                continue
            for toml in sorted(root.rglob("plugin.toml")):
                src = str(toml.parent) + "/"
                try:
                    mgr.install(src)
                    installed.append(toml.parent.name)
                except Exception as exc:
                    failures.append(f"{toml.parent.name}: {type(exc).__name__}: {exc}")
    if failures:
        raise AssertionError(
            "proposed plugin install failures:\n" + "\n".join(failures)
        )
    return reg, installed


def test_all_new_packs_install(new_packs_registry):
    reg, installed = new_packs_registry
    assert len(installed) >= 100
    assert len(reg.list_nodes()) >= 100


@pytest.mark.parametrize(
    "node_type",
    [
        "yolo_train",
        "tflm_quantize",
        "vector_store_write",
        "vector_store_query",
        "rag_generate",
        "text_embed",
        "mcu_train",
        "wakeword_train",
        "video_ingest",
        "agent_loop",
        "ship_package_create",
    ],
)
def test_key_nodes_registered(node_type, new_packs_registry):
    reg, _ = new_packs_registry
    types = {m.node_type for m in reg.list_nodes()}
    assert node_type in types


@pytest.mark.offline
@pytest.mark.parametrize(
    "node_type",
    ["yolo_train", "tflm_quantize", "rag_generate", "text_embed", "vector_store_write", "mcu_window"],
)
def test_stub_process(node_type, new_packs_registry, tmp_path):
    from unit_test.plugins._helpers import materialize_isolated_class

    reg, _ = new_packs_registry
    cls = materialize_isolated_class(reg.get_class(node_type))
    cfg: dict = {"stub": True}
    if node_type == "yolo_train":
        cfg["project"] = str(tmp_path / "yolo")
    node = cls(config=cfg)
    out = node.process({})
    assert isinstance(out, dict) and out


@pytest.mark.offline
def test_needs_api_honesty(new_packs_registry):
    reg, _ = new_packs_registry
    for nt in ("mcu_flash_ota", "mcu_ondevice_metrics"):
        cls = reg.get_class(nt)
        node = cls(config={"stub": True, "dry_run": True})
        out = node.process({})
        payload = next(iter(out.values()))
        status = getattr(payload, "status", None)
        assert status == "needs-api"
