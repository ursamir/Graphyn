# unit_test/plugins/audio/test_audio_exporter_versions.py
"""audio_exporter immutable dataset versions + manifest (plugin 1.2.0 / node 1.1.0).

Covers: next-free-version on an existing tag, overwrite, append manifest
recompute, referenced-version guard, dotted tag bump, dataset.version_create audit.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry
from app.models.audio_sample import AudioSample

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "PluginPackage" / "Audio" / "audio_exporter"


@pytest.fixture(scope="module")
def cls():
    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    disc._process_module(disc._import_file(PLUGIN / "nodes.py", package_prefix=None))
    return reg.get_class("audio_exporter")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    return tmp_path


def _samples(n: int, label: str = "yes") -> list[AudioSample]:
    y = (0.1 * np.sin(np.arange(1600) / 5.0)).astype(np.float32)
    return [AudioSample(data=y, sample_rate=16000, label=label, path=f"/d/{label}_{i}.wav", metadata={}) for i in range(n)]


def _run(cls, n, cfg, label="yes"):
    return cls(config=cfg, seed=0).process({"input": _samples(n, label)})["output"]


def _manifest(path: Path) -> dict:
    return json.loads((path / "manifest.json").read_text())


def test_version_metadata_bumped(cls):
    assert cls.metadata.version == "1.1.0"
    assert "overwrite" in cls.Config.model_fields


def test_manifest_written_with_sha256(cls, ws):
    _run(cls, 5, {"output_dir": "out"})
    man = _manifest(ws / "out/v1")
    paths = {f["path"] for f in man["files"]}
    assert "labels.csv" in paths and any(p.endswith(".wav") for p in paths)
    assert man["content_hash"] and all(len(f["sha256"]) == 64 for f in man["files"])
    assert man["source"]["kind"] == "audio_exporter"


def test_existing_version_goes_to_next_free(cls, ws):
    _run(cls, 5, {"output_dir": "out"})
    before = _manifest(ws / "out/v1")["content_hash"]
    _run(cls, 3, {"output_dir": "out"}, label="no")
    assert _manifest(ws / "out/v1")["content_hash"] == before
    assert (ws / "out/v2/labels.csv").is_file()


def test_dotted_tag_bumps_last_component(cls, ws):
    _run(cls, 2, {"output_dir": "out", "version_tag": "v1.0.0"})
    _run(cls, 2, {"output_dir": "out", "version_tag": "v1.0.0"})
    assert (ws / "out/v1.0.1/labels.csv").is_file()


def test_append_recomputes_manifest(cls, ws):
    _run(cls, 3, {"output_dir": "out"})
    first = _manifest(ws / "out/v1")
    _run(cls, 2, {"output_dir": "out", "append": True}, label="no")
    second = _manifest(ws / "out/v1")
    assert second["file_count"] > first["file_count"]
    assert second["content_hash"] != first["content_hash"]


def _reference_from_run(ws: Path, project: str, version: str) -> None:
    run = ws / "workspace" / "runs" / "run-ref"
    run.mkdir(parents=True)
    (run / "graph.json").write_text(json.dumps({"nodes": [{"config": {"path": f"out/{project}/{version}"}}]}))


@pytest.mark.parametrize("flag", ["append", "overwrite"])
def test_referenced_version_is_protected(cls, ws, flag):
    _run(cls, 3, {"output_dir": "workspace/datasets/output/proj"})
    _reference_from_run(ws, "proj", "v1")
    with pytest.raises(ValueError, match="referenced"):
        _run(cls, 2, {"output_dir": "workspace/datasets/output/proj", flag: True})
    # untouched
    assert _manifest(ws / "workspace/datasets/output/proj/v1")["file_count"] >= 3


def test_overwrite_unreferenced_replaces(cls, ws):
    _run(cls, 4, {"output_dir": "out"})
    _run(cls, 1, {"output_dir": "out", "overwrite": True}, label="no")
    man = _manifest(ws / "out/v1")
    assert not any("/yes/" in f["path"] for f in man["files"])


def test_version_create_audited(cls, ws):
    _run(cls, 2, {"project": "audited"})
    events = [
        json.loads(line)
        for line in (ws / "workspace" / "audit" / "events.jsonl").read_text().splitlines()
    ]
    ev = [e for e in events if e["action"] == "dataset.version_create"]
    assert ev and ev[-1]["resource_id"] == "audited/v1"
    assert ev[-1]["metadata"]["content_hash"]
