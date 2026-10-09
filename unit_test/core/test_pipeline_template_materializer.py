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

# One sample per shipped family (RAG / Vision / TinyML / MLOps packs are not
# shipped, so the catalog has no templates for them).
FAMILY_SAMPLES = [
    "tpl-audio-kws-train-smart-home",
    "tpl-audio-speech-enhancement",
    "tpl-wakeword-train-export",
    "tpl-video-scene-clips-security",
    "tpl-agents-guarded-reply-memory",
    "tpl-common-http-poll-transform",
    "tpl-common-asr-pii-redact-callcenter",
    "tpl-cross-call-analytics",
]
REMOVED_PACK_PREFIXES = ("tpl-rag-", "tpl-vision-", "tpl-tinyml-", "tpl-mlops-")


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


def test_catalog_only_advertises_shipped_packs():
    cat = load_marketplace_catalog()
    templates = cat.get("templates") or []
    # Honest size: base pipelines x industry presets (see generator docstring).
    assert len(templates) >= 100
    assert cat.get("base_pipelines", 0) >= 40
    assert not [t["id"] for t in templates if t["id"].startswith(REMOVED_PACK_PREFIXES)]
    assert {t["pack"] for t in templates} <= {"Audio", "Common", "Agents", "Video", "WakeWord"}
    for t in templates:
        assert t["edges_hint"] or len(t["node_chain"]) == 1, t["id"]
        assert t["status"] in {"ready", "needs-credentials", "needs-endpoint", "needs-upstream"}, t["id"]
        assert t["metadata_extra"].get("base_template"), t["id"]


def test_catalog_node_types_exist_in_shipped_plugins(full_registry):
    cat = load_marketplace_catalog()
    shipped = set(full_registry._classes)
    used = {s["node_type"] for t in cat["templates"] for s in t["node_chain"]}
    assert used <= shipped, sorted(used - shipped)


def test_every_base_template_has_a_seed_graph():
    cat = load_marketplace_catalog()
    bases = {t["metadata_extra"]["base_template"] for t in cat["templates"]}
    for b in bases:
        assert (REPO / "examples" / "templates" / "marketplace" / f"{b}.graph.json").is_file(), b


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
    """Every entry is materialized the way the API does it and validated."""
    cat = load_marketplace_catalog()
    ok = 0
    failed: dict[str, list] = {}
    for entry in cat["templates"]:
        graph = materialize_template_entry(entry, registry=full_registry, ensure_seed_datasets=False)
        errors = validate_graph_ir(load_ir(graph), full_registry)
        if errors:
            failed[entry["id"]] = [str(getattr(e, "message", e))[:160] for e in errors[:2]]
        else:
            ok += 1
    total = ok + len(failed)
    pct = 100.0 * ok / total
    assert pct >= 95.0, f"only {pct:.2f}% validated ({ok}/{total}): {dict(list(failed.items())[:5])}"
    # The generator refuses to write invalid entries, so anything failing here
    # means the catalog and the plugins drifted apart.
    assert not failed, failed
