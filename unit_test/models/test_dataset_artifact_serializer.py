"""DatasetArtifact serializes to .npy + manifest, not giant JSON."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.models.dataset_artifact import DatasetArtifact
from app.models.dataset_artifact_serializer import (
    DatasetArtifactHandler,
    register_dataset_serializer,
)


def _sample_artifact() -> DatasetArtifact:
    return DatasetArtifact(
        X_train=np.arange(24, dtype=np.float32).reshape(2, 3, 4, 1),
        y_train=np.array([0, 1], dtype=np.int32),
        X_val=np.zeros((1, 3, 4, 1), dtype=np.float32),
        y_val=np.array([0], dtype=np.int32),
        X_test=np.ones((1, 3, 4, 1), dtype=np.float32),
        y_test=np.array([1], dtype=np.int32),
        labels=["a", "b"],
        input_shape=(3, 4, 1),
        n_classes=2,
        version="v1",
        metadata={"source": "unit"},
    )


def test_round_trip_npy_manifest(tmp_path: Path):
    handler = DatasetArtifactHandler()
    dest = tmp_path / "data"
    dest.mkdir()
    original = _sample_artifact()
    handler.serialize(original, dest)

    assert (dest / "manifest.json").is_file()
    assert (dest / "X_train.npy").is_file()
    assert not (dest / "data.json").exists()
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "dataset_artifact/v1"
    assert manifest["labels"] == ["a", "b"]
    assert manifest["arrays"]["X_train"]["shape"] == [2, 3, 4, 1]

    restored = handler.deserialize(dest)
    assert restored is not None
    assert restored.labels == ["a", "b"]
    assert restored.n_classes == 2
    assert restored.input_shape == (3, 4, 1)
    np.testing.assert_array_equal(restored.X_train, original.X_train)
    np.testing.assert_array_equal(restored.y_train, original.y_train)


def test_infer_and_register():
    register_dataset_serializer()
    from app.core.artifacts.artifact_serializer import get_serializer_registry
    from app.core.artifacts.artifact_store import _infer_artifact_type

    art = _sample_artifact()
    assert DatasetArtifactHandler().infer_type(art) == "dataset_artifact"
    assert get_serializer_registry().get("dataset_artifact") is not None
    assert _infer_artifact_type(art) == "dataset_artifact"


def test_artifact_store_register_uses_npy(tmp_path: Path, monkeypatch):
    register_dataset_serializer()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    from app.core.artifacts.artifact_store import ArtifactStore, _infer_artifact_type

    store = ArtifactStore()
    art = _sample_artifact()
    record, deduped = store.register(
        run_id="r1",
        node_id="dataset_builder_0",
        node_type="dataset_builder",
        artifact_type=_infer_artifact_type(art),
        data=art,
    )
    assert deduped is False
    assert record.artifact_type == "dataset_artifact"
    data_dir = tmp_path / record.data_path
    assert (data_dir / "manifest.json").is_file()
    assert (data_dir / "X_train.npy").is_file()
    assert not (data_dir / "data.json").exists()
    # Must stay tiny — the old JSON path wrote hundreds of MB of floats.
    assert (data_dir / "manifest.json").stat().st_size < 8_000


def test_generic_json_fallback_offloads_ndarrays(tmp_path: Path):
    from app.core.artifacts.artifact_store import ArtifactStore

    store = ArtifactStore()
    dest = tmp_path / "generic"
    dest.mkdir()
    payload = {"X": np.arange(100, dtype=np.float32).reshape(10, 10), "label": "x"}
    store._serialize_json(payload, dest)
    raw = json.loads((dest / "data.json").read_text(encoding="utf-8"))
    assert raw["label"] == "x"
    assert raw["X"]["__ndarray__"].endswith(".npy")
    assert (dest / raw["X"]["__ndarray__"]).is_file()
    # data.json must not contain the expanded float list
    assert (dest / "data.json").stat().st_size < 2_000
