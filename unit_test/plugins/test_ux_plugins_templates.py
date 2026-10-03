"""UX overhaul — Example 06 as a two-step template group.

* ``speech-commands-e2e-prepare`` (examples/templates/) — Step 1: all six
  labels in one graph (recursive ingest → … → one exporter, fresh version).
* ``ex-06-speech-commands-e2e`` (examples/06…/pipeline_train_ml) — Step 2.

Both carry ``metadata.group = "speech-commands-e2e"``, ``phase`` 1/2,
``step_title`` and a ``title``; Step 1's export folder is exactly what Step 2
ingests after the template sync path rewrite. Every node has a human label
consistent with its config.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry
from app.core.templates.example_templates import discover_example_graphs, rewrite_graph_paths

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "PluginPackage"
STEP1 = ROOT / "examples" / "templates" / "speech-commands-e2e-prepare.graph.json"
STEP2 = ROOT / "examples" / "06_speech_commands_e2e" / "pipeline_train_ml.graph.json"
EX06 = ROOT / "examples" / "06_speech_commands_e2e"
STEP1_ID = "speech-commands-e2e-prepare"
STEP2_ID = "ex-06-speech-commands-e2e"
GROUP = "speech-commands-e2e"
SIX = {"yes", "no", "up", "down", "go", "stop"}

PLUGINS = {
    "dataset_ingest": "Audio/dataset_ingest", "audio_conditioner": "Audio/audio_conditioner",
    "segmenter": "Audio/segmenter", "audio_quality_gate": "Audio/audio_quality_gate",
    "augmentation_pipeline": "Audio/augmentation_pipeline", "audio_exporter": "Audio/audio_exporter",
    "feature_frontend": "Audio/feature_frontend", "dataset_builder": "Common/dataset_builder",
    "trainer": "Common/trainer", "model_builder": "Common/trainer", "evaluator": "Common/evaluator",
    "edge_optimizer": "Common/edge_optimizer", "realtime_inference": "Common/realtime_inference",
}


def _graph(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _cls(node_type: str):
    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    root = PKG / PLUGINS[node_type]
    for entry in ("types.py", "nodes.py"):
        if (root / entry).is_file():
            disc._process_module(disc._import_file(root / entry, package_prefix=None))
    return reg.get_class(node_type)


@pytest.fixture(scope="module")
def discovered() -> dict[str, dict]:
    return {d["id"]: d for d in discover_example_graphs()}


def test_both_steps_are_discovered_with_titles(discovered):
    assert discovered[STEP1_ID]["title"] == "Speech commands E2E · Step 1 · Prepare dataset"
    assert discovered[STEP1_ID]["source"] == "templates/speech-commands-e2e-prepare.graph.json"
    assert discovered[STEP2_ID]["title"] == "Speech commands E2E · Step 2 · Train model"
    assert discovered[STEP2_ID]["source"] == "06_speech_commands_e2e/pipeline_train_ml.graph.json"


@pytest.mark.parametrize("path,phase,step_title", [(STEP1, 1, "Prepare dataset"), (STEP2, 2, "Train model")])
def test_group_metadata(path, phase, step_title):
    meta = _graph(path)["metadata"]
    assert meta["group"] == GROUP and meta["phase"] == phase and meta["step_title"] == step_title
    assert meta["title"].startswith("Speech commands E2E · Step")
    assert meta["description"].startswith(f"Step {phase} of 2")


def test_step_links():
    assert _graph(STEP1)["metadata"]["next_template"] == STEP2_ID
    assert _graph(STEP2)["metadata"]["previous_template"] == STEP1_ID


def test_train_description_is_user_facing():
    desc = _graph(STEP2)["metadata"]["description"]
    assert "Run Step 1".lower() in desc.lower()
    assert ".graph.json" not in desc and "pipeline_preprocess" not in desc and ".sh" not in desc
    assert "fall" not in desc.lower() and "raw clip" not in desc.lower(), "stale raw-clip fallback claim"


@pytest.mark.parametrize("path", [STEP1, STEP2], ids=["step1", "step2"])
def test_graph_loads_and_configs_validate(path):
    from app.core.ir.loader import load_ir

    graph = _graph(path)
    load_ir(graph)
    for node in graph["nodes"]:
        nt = node["node_type"]
        schema = tomllib.loads((PKG / PLUGINS[nt] / "plugin.toml").read_text())["config_schema"][nt]
        assert set(node["config"]) <= set(schema), f"{node['id']}: undeclared keys"
        _cls(nt).Config(**node["config"])


def test_step1_covers_six_labels_in_one_graph():
    graph = _graph(STEP1)
    ingest = [n for n in graph["nodes"] if n["node_type"] == "dataset_ingest"]
    exporters = [n for n in graph["nodes"] if n["node_type"] == "audio_exporter"]
    assert len(ingest) == 1 and len(exporters) == 1
    cfg = ingest[0]["config"]
    assert cfg["recursive"] is True, "labels come from the six sub-folders"
    assert cfg["path"] == "workspace/datasets/input/speech-commands"
    seed = ROOT / "examples" / "02_speech_commands" / "data"  # seeded into workspace/datasets/input/speech-commands
    assert {p.name for p in seed.iterdir() if p.is_dir()} == SIX
    assert exporters[0]["config"]["append"] is False, "re-running Step 1 replaces the dataset"
    # same per-clip processing as the per-label CLI shards
    shard = _graph(EX06 / "pipeline_preprocess.graph.json")
    for a, b in zip(graph["nodes"][1:], shard["nodes"][1:]):
        assert (a["node_type"], a["config"]) == (b["node_type"], b["config"])
    assert graph["edges"] == shard["edges"]


def test_step1_output_is_step2_input_after_template_sync():
    s1 = rewrite_graph_paths(_graph(STEP1), slug=STEP1_ID)
    s2 = rewrite_graph_paths(_graph(STEP2), slug=STEP2_ID)
    exp = next(n for n in s1["nodes"] if n["node_type"] == "audio_exporter")["config"]
    ing = next(n for n in s2["nodes"] if n["node_type"] == "dataset_ingest")["config"]
    assert f"{exp['output_dir']}/{exp['version_tag']}" == ing["path"]
    assert ing["path"].startswith("workspace/artifacts/speech-commands/dataset/")


def test_ui_project_stamp_keeps_handoff_dir():
    """projectStamp.ts never retargets workspace/artifacts/<slug>/dataset/... exporters."""
    exp = next(n for n in _graph(STEP1)["nodes"] if n["node_type"] == "audio_exporter")["config"]
    assert re.search(r"(^|/)workspace/artifacts/[^/]+/dataset(/|$)", exp["output_dir"])
    assert not exp["output_dir"].startswith("workspace/datasets/output/")


@pytest.mark.parametrize("path", sorted(EX06.glob("*.graph.json")) + [STEP1], ids=lambda p: p.name)
def test_every_node_has_a_human_label(path):
    for node in _graph(path)["nodes"]:
        label = node.get("label")
        assert isinstance(label, str) and label.strip(), f"{path.name}:{node['id']}"
        assert "_" not in label, f"{node['id']}: label should be human text, got {label!r}"


def test_train_labels_match_configs():
    nodes = {n["id"]: n for n in _graph(STEP2)["nodes"]}
    mb = nodes["model_builder_0"]
    assert mb["config"]["architecture"] == "ds_cnn" and "DS-CNN" in mb["label"]
    assert f"{mb['config']['filters']} filters" in mb["label"] and f"{mb['config']['num_layers']} blocks" in mb["label"]
    tr = nodes["trainer_0"]
    assert f"{tr['config']['epochs']} epochs" in tr["label"]
    eo = nodes["edge_optimizer_0"]
    assert eo["config"]["quantization"] == "int8" and "INT8" in eo["label"] and "TFLite" in eo["label"]
