"""Legacy artifact dataset soft-list + publish into Library Outputs."""
from __future__ import annotations

from pathlib import Path

from app.core.mlops.dataset_inputs import list_artifact_datasets, publish_artifact_dataset


def test_list_artifact_datasets(tmp_path: Path):
    root = tmp_path / "artifacts"
    ds = root / "speech-commands" / "dataset" / "speech_commands"
    (ds / "v1" / "train").mkdir(parents=True)
    (ds / "v1" / "train" / "a.wav").write_bytes(b"x")
    (ds / "v2" / "train").mkdir(parents=True)
    (ds / "v2" / "train" / "b.wav").write_bytes(b"y")
    (ds / "empty").mkdir()
    rows = list_artifact_datasets(root)
    assert len(rows) == 1
    assert rows[0]["kind"] == "artifact_dataset"
    assert rows[0]["versions"] == ["v1", "v2"]
    assert rows[0]["fs_path"].endswith("speech-commands/dataset/speech_commands")


def test_publish_artifact_dataset(tmp_path: Path):
    src = tmp_path / "src" / "v1"
    (src / "train").mkdir(parents=True)
    (src / "train" / "a.wav").write_bytes(b"x")
    target = tmp_path / "my-test1"
    out = publish_artifact_dataset(source_dir=src, target_project_dir=target)
    assert out["project"] == "my-test1"
    assert out["version"] == "v1"
    assert (target / "v1" / "train" / "a.wav").is_file()
    assert (target / "v1" / "manifest.json").is_file()
