"""Marketplace materialize + validate smoke tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.ir.loader import load_ir
from app.core.nodes.registry import NodeRegistry
from app.core.templates.pipeline_template_materializer import (
    load_marketplace_catalog,
    materialize_template_entry,
)
from app.core.plugins.manager import PluginManager
from app.core.plugins.venv_manager import PluginVenvManager
from app.core.execution.validation import validate_graph_ir

REPO = Path(__file__).resolve().parents[2]

FAMILY_SAMPLES = [
    "tpl-audio-kws-smart-home",
    "tpl-vision-yolo-detect-train-retail-shelf",
    "tpl-rag-ingest-fs-recursive-faiss-support",
    "tpl-tinyml-kws-wearable-cortex-m4-ptq-tflm",
    "tpl-wakeword-en-hey-graphyn-data-gen",
    "tpl-video-ingest-scene-caption-security",
    "tpl-agents-run-pipeline-mlops",
    "tpl-mlops-train-eval-ship-audio",
    "tpl-common-http-poll-transform-general",
]


@pytest.fixture(scope="module")
def full_registry(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("all_plugins_mat")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp))
    mgr._plugins_dir = str(tmp)
    with patch.object(PluginVenvManager, "ensure", return_value=Path("/tmp/fake-venv/bin/python")):
        for toml in sorted((REPO / "PluginPackage").rglob("plugin.toml")):
            try:
                mgr.install(str(toml.parent) + "/")
            except Exception:
                continue
    return reg


def test_catalog_has_thousands_of_templates():
    cat = load_marketplace_catalog()
    assert len(cat.get("templates") or []) >= 2900


@pytest.mark.parametrize("template_id", FAMILY_SAMPLES)
def test_family_sample_materialize_validate(template_id, full_registry):
    cat = load_marketplace_catalog()
    entry = next(t for t in cat["templates"] if t["id"] == template_id)
    graph = materialize_template_entry(entry, registry=full_registry)
    assert graph.get("schema_version") == "1.1"
    ingest = next((n for n in graph["nodes"] if n["node_type"] in {
        "dataset_ingest", "vision_dataset_ingest", "video_ingest", "mcu_dataset_ingest", "rag_fs_connector"
    }), None)
    if ingest is not None:
        path = (ingest.get("config") or {}).get("path") or (ingest.get("config") or {}).get("root")
        assert path and str(path).strip(), f"{template_id} materialized ingest without path"
        assert str(path).startswith("workspace/datasets/input/"), path
        assert str(path).strip() not in {".", "workspace", "workspace/"}
    ir = load_ir(graph)
    errors = validate_graph_ir(ir, full_registry)
    assert errors == [], errors


def test_materialize_binds_dataset_path_alias():
    entry = {
        "id": "tpl-audio-kws-retail",
        "name": "Kws Retail",
        "pack": "Audio",
        "family": "audio",
        "tags": ["kws", "retail"],
        "parameters": {"dataset_path": "workspace/datasets/input/retail-kws", "sample_rate": 16000},
        "node_chain": [
            {"node_type": "dataset_ingest", "config_overrides": {"path": "workspace/datasets/input/security-kws"}},
            {"node_type": "audio_conditioner"},
            {"node_type": "trainer"},
        ],
    }
    graph = materialize_template_entry(entry, ensure_seed_datasets=True)
    # Fictional marketplace path rewritten to bundled seed
    assert graph["nodes"][0]["config"]["path"] == "workspace/datasets/input/speech-commands"
    assert graph["nodes"][0]["config"]["limit"] == 8
    assert graph["nodes"][1]["config"].get("target_sample_rate") == 16000
    assert "sample_rate" not in graph["nodes"][1]["config"]
    trainer = next(n for n in graph["nodes"] if n["node_type"] == "trainer")
    assert trainer["config"].get("epochs") == 1


def test_materialize_synthesizes_path_when_missing():
    entry = {
        "id": "tpl-audio-kws-retail-edge-tflite",
        "pack": "Audio",
        "industry": "retail",
        "family": "audio",
        "tags": ["kws"],
        "parameters": {"export_format": "tflite"},
        "node_chain": [{"node_type": "dataset_ingest"}, {"node_type": "trainer"}],
    }
    graph = materialize_template_entry(entry, ensure_seed_datasets=False)
    path = graph["nodes"][0]["config"]["path"]
    assert path == "workspace/datasets/input/speech-commands"


def test_linear_edges_prefer_output_over_rejected():
    from app.core.templates.pipeline_template_materializer import _linear_edges

    edges = _linear_edges(
        [
            "dataset_ingest",
            "audio_conditioner",
            "audio_quality_gate",
            "augmentation_pipeline",
            "feature_frontend",
        ]
    )
    qg_out = [e for e in edges if e["src_id"] == "n2"]
    assert qg_out, edges
    assert all(e["src_port"] == "output" for e in qg_out), qg_out
    assert not any(e["src_port"] == "rejected" for e in qg_out), qg_out


def test_materialize_sanitizes_unknown_config_with_registry():
    class FakeConfig:
        model_fields = {"path": object(), "limit": object(), "recursive": object()}

    class FakeNode:
        Config = FakeConfig

    class FakeReg:
        def get_class(self, nt):
            assert nt == "dataset_ingest"
            return FakeNode

    entry = {
        "id": "tpl-x",
        "pack": "Audio",
        "tags": ["kws"],
        "node_chain": [
            {
                "node_type": "dataset_ingest",
                "config_overrides": {"path": "x", "dataset_path": "bogus", "limit": 0},
            }
        ],
    }
    graph = materialize_template_entry(entry, registry=FakeReg(), ensure_seed_datasets=False)
    cfg = graph["nodes"][0]["config"]
    assert "dataset_path" not in cfg
    assert cfg["path"] == "workspace/datasets/input/speech-commands"
    assert cfg["limit"] == 8


@pytest.mark.slow
def test_full_catalog_validate_ge_95(full_registry):
    cat = load_marketplace_catalog()
    ok = fail = 0
    for entry in cat["templates"]:
        graph = materialize_template_entry(entry)
        ir = load_ir(graph)
        if validate_graph_ir(ir, full_registry):
            fail += 1
        else:
            ok += 1
    total = ok + fail
    pct = 100.0 * ok / total
    assert pct >= 95.0, f"only {pct:.2f}% validated ({ok}/{total})"
