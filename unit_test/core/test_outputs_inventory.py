"""Generic outputs inventory: list_files, file_tree, publish_files, listing."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _register_serializers():
    from app.core.artifacts.file_tree import register_file_tree_serializer
    from app.models.audio_artifact_serializer import register_audio_serializer
    from app.models.dataset_artifact_serializer import register_dataset_serializer

    register_audio_serializer()
    register_dataset_serializer()
    register_file_tree_serializer()


def test_audio_handler_list_files(tmp_path: Path):
    from app.models.audio_artifact_serializer import AudioSampleHandler
    from app.models.audio_sample import AudioSample

    samples = [
        AudioSample(
            data=np.zeros(8, dtype=np.float32),
            sample_rate=16000,
            label="a",
            path="a.wav",
        ),
        AudioSample(
            data=np.ones(8, dtype=np.float32),
            sample_rate=16000,
            label="b",
            path="b.wav",
        ),
    ]
    dest = tmp_path / "data"
    dest.mkdir()
    AudioSampleHandler().serialize(samples, dest)
    listing = AudioSampleHandler().list_files(dest)
    assert listing is not None
    assert listing.total == 3  # manifest + 2 wavs
    names = {e.name or e.path.name for e in listing.entries}
    assert "manifest.json" in names
    assert "0.wav" in names and "1.wav" in names


def test_dataset_handler_list_files(tmp_path: Path):
    from app.models.dataset_artifact import DatasetArtifact
    from app.models.dataset_artifact_serializer import DatasetArtifactHandler

    art = DatasetArtifact(
        X_train=np.zeros((2, 2), dtype=np.float32),
        y_train=np.array([0, 1], dtype=np.int32),
        X_val=np.zeros((1, 2), dtype=np.float32),
        y_val=np.array([0], dtype=np.int32),
        X_test=np.zeros((1, 2), dtype=np.float32),
        y_test=np.array([1], dtype=np.int32),
        labels=["a", "b"],
        input_shape=(2,),
        n_classes=2,
    )
    dest = tmp_path / "data"
    dest.mkdir()
    DatasetArtifactHandler().serialize(art, dest)
    listing = DatasetArtifactHandler().list_files(dest)
    assert listing is not None
    assert listing.total >= 7  # manifest + 6 npy
    assert any(e.name == "manifest.json" for e in listing.entries)
    assert any(str(e.path).endswith("X_train.npy") for e in listing.entries)


def test_file_tree_round_trip_and_list(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    from app.core.artifacts.artifact_store import ArtifactStore
    from app.core.artifacts.file_tree import FileTreeHandler, file_tree_payload

    root = tmp_path / "out"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "b.json").write_text("{}", encoding="utf-8")
    payload = file_tree_payload(
        {
            "root": str(root),
            "files": [{"path": "a.txt", "size": 1}, {"path": "b.json"}],
            "total": 2,
        }
    )
    dest = tmp_path / "artifact_data"
    dest.mkdir()
    FileTreeHandler().serialize(payload, dest)
    assert (dest / "inventory.json").is_file()
    listing = FileTreeHandler().list_files(dest)
    assert listing is not None and listing.total == 2
    assert {e.path.name for e in listing.entries} == {"a.txt", "b.json"}

    store = ArtifactStore()
    record, _ = store.register(
        run_id="r-ft",
        node_id="writer",
        node_type="webhook_dump",
        artifact_type="file_tree",
        data=payload,
    )
    assert record.artifact_type == "file_tree"


def test_publish_files_drains_to_file_tree(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    from app.core.artifacts.artifact_store import ArtifactStore, infer_artifact_type
    from app.core.artifacts.file_tree import file_tree_payload
    from app.core.nodes.base import Node
    from app.core.nodes.ports import InputPort, OutputPort

    class _Pub(Node):
        node_type = "pub_test"
        input_ports = {"input": InputPort(name="input", data_type=object)}
        output_ports = {"output": OutputPort(name="output", data_type=object)}

        def process(self, inputs):
            out = tmp_path / "published"
            out.mkdir(exist_ok=True)
            (out / "result.json").write_text('{"ok":true}', encoding="utf-8")
            self.publish_files(out, [{"path": "result.json", "size": 10}])
            return {"output": {"ok": True}}

    node = _Pub({})
    outputs = node.process({"input": 1})
    trees = node.take_published_file_trees()
    assert len(trees) == 1 and trees[0]["files"][0]["path"] == "result.json"
    assert node.take_published_file_trees() == []

    store = ArtifactStore()
    record, _ = store.register(
        run_id="r-pub",
        node_id="pub_0",
        node_type="pub_test",
        artifact_type="file_tree",
        data=file_tree_payload(trees[0]),
        metadata={"kind": "published_files"},
    )
    assert record.node_id == "pub_0"
    assert outputs["output"]["ok"] is True
    # Port value is generic dict — not auto file_tree unless format set.
    assert infer_artifact_type(outputs["output"]) == "generic"


def test_listing_uses_artifact_inventory_not_labels_csv(tmp_workspace: Path, monkeypatch):
    monkeypatch.chdir(tmp_workspace.parent)
    from app.core.artifacts.artifact_store import ArtifactStore
    from app.core.artifacts.file_tree import file_tree_payload, register_file_tree_serializer
    from app.core.runs import run_outputs as ro

    register_file_tree_serializer()
    run_id = "run-inv"
    run_dir = tmp_workspace / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "graph.json").write_text("{}", encoding="utf-8")
    (run_dir / "meta.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")

    root = tmp_workspace / "exports" / "v1"
    root.mkdir(parents=True)
    (root / "labels.csv").write_text("id,path\n", encoding="utf-8")
    for i in range(5):
        (root / f"{i}.json").write_text("{}", encoding="utf-8")

    # Without ArtifactStore: listing must not scavenge labels.csv / walk the tree.
    bare = ro.list_run_output_files(run_id, run_dir)
    assert not any(e["name"].endswith(".json") and e["name"] != "graph.json" and e["name"] != "meta.json" for e in bare)

    ArtifactStore().register(
        run_id=run_id,
        node_id="llm_dump_0",
        node_type="llm_call",
        artifact_type="file_tree",
        data=file_tree_payload(
            {
                "root": "workspace/exports/v1",
                "files": [{"path": f"{i}.json"} for i in range(5)]
                + [{"path": "labels.csv"}],
                "total": 6,
            }
        ),
    )
    # Drop any stale index so ensure rebuilds from store.
    idx = run_dir / "outputs_index.json"
    if idx.exists():
        idx.unlink()

    detail = ro.list_run_output_files_detail(run_id, run_dir)
    attributed = [e for e in detail["items"] if e.get("node_id") == "llm_dump_0"]
    assert len(attributed) >= 1
    page = ro.list_node_output_files(run_id, run_dir, "llm_dump_0", limit=100)
    assert page["total"] == 6
    names = {i["name"] for i in page["items"]}
    assert "labels.csv" in names and "0.json" in names
    # Force a small cap so truncated_by_node reports the inventory total.
    monkeypatch.setattr(ro, "_MAX_LISTED_FILES", 3)
    capped = ro.list_run_output_files_detail(run_id, run_dir)
    assert capped["truncated_by_node"]["llm_dump_0"]["total"] == 6
