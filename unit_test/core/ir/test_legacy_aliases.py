# unit_test/core/ir/test_legacy_aliases.py
"""Tests for legacy node_type → PluginPackage migration."""
from __future__ import annotations

from app.core.ir.legacy_aliases import migrate_legacy_node_types
from app.core.ir.loader import load_ir


def test_input_clean_export_migrate():
    data = {
        "schema_version": "1.1",
        "metadata": {"name": "t", "seed": 1},
        "nodes": [
            {"id": "a", "node_type": "input", "config": {"path": "data"}},
            {"id": "b", "node_type": "clean", "config": {"sample_rate": 16000}},
            {"id": "c", "node_type": "split", "config": {"train": 0.8, "val": 0.1}},
            {
                "id": "d",
                "node_type": "export",
                "config": {"output": "out", "project": "p", "version": "v1"},
            },
        ],
        "edges": [
            {"src_id": "a", "src_port": "output", "dst_id": "b", "dst_port": "input"},
            {"src_id": "b", "src_port": "output", "dst_id": "c", "dst_port": "input"},
            {"src_id": "c", "src_port": "output", "dst_id": "d", "dst_port": "input"},
        ],
        "parameters": {},
    }
    migrated = migrate_legacy_node_types(data)
    types = [n["node_type"] for n in migrated["nodes"]]
    assert "input" not in types
    assert "split" not in types
    assert "dataset_ingest" in types
    assert "audio_conditioner" in types
    assert "audio_exporter" in types
    exporter = next(n for n in migrated["nodes"] if n["node_type"] == "audio_exporter")
    assert exporter["config"]["split_ratios"]["train"] == 0.8
    # Graph must validate
    load_ir(migrated)


def test_starter_audio_classification_loads():
    import json
    from pathlib import Path

    path = Path("examples/templates/audio-classification.graph.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    graph = load_ir(data)
    assert all(
        n.node_type
        in {
            "dataset_ingest",
            "audio_conditioner",
            "segmenter",
            "augmentation_pipeline",
            "audio_exporter",
            "speech_enhancer",
            "audio_quality_gate",
            "audio_annotator",
        }
        for n in graph.nodes
    )
