"""Marketplace materialize + validate smoke tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.ir.loader import load_ir
from app.core.nodes.registry import NodeRegistry
from app.core.pipeline_template_materializer import (
    load_marketplace_catalog,
    materialize_template_entry,
)
from app.core.plugins.manager import PluginManager
from app.core.plugins.venv_manager import PluginVenvManager
from app.core.validation import validate_graph_ir

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


def test_catalog_has_2998_templates():
    cat = load_marketplace_catalog()
    assert len(cat.get("templates") or []) == 2998


@pytest.mark.parametrize("template_id", FAMILY_SAMPLES)
def test_family_sample_materialize_validate(template_id, full_registry):
    cat = load_marketplace_catalog()
    entry = next(t for t in cat["templates"] if t["id"] == template_id)
    graph = materialize_template_entry(entry)
    assert graph.get("schema_version") == "1.1"
    ir = load_ir(graph)
    errors = validate_graph_ir(ir, full_registry)
    assert errors == [], errors


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
