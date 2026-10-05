# unit_test/core/test_ingestion_hf_provenance.py
"""HF ingest: max_rows, label column (ClassLabel names), no forced override,
provenance file + dataset.ingest_finish audit; CLI `graphyn data` smoke."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np


class _ClassLabel:
    names = ["no", "yes"]

    def int2str(self, v: int) -> str:
        return self.names[v]


class _FakeDataset:
    def __init__(self, n: int):
        self.n = n
        self.features = {"label": _ClassLabel()}

    def __iter__(self):
        for i in range(self.n):
            yield {"audio": {"array": np.zeros(160, dtype=np.float32) + 0.01 * i, "sampling_rate": 16000}, "label": i % 2}


def _install_fake(monkeypatch, calls: list):
    mod = types.ModuleType("datasets")

    def load_dataset(repo, **kw):
        calls.append((repo, kw))
        return _FakeDataset(50)

    mod.load_dataset = load_dataset
    monkeypatch.setitem(sys.modules, "datasets", mod)
    monkeypatch.setattr("app.domain.ingestion._resolve_hf_revision", lambda repo, rev: "abc123")


def test_hf_job_caps_rows_maps_labels_and_records_provenance(tmp_workspace: Path, monkeypatch):
    from app.domain.ingestion import IngestionJob, IngestionService

    calls: list = []
    _install_fake(monkeypatch, calls)
    svc = IngestionService()
    job = IngestionJob(job_id="j1", status="running")
    svc._run_hf_job(job, "org/kw", "train", "audio", "label", None, max_rows=6, revision="main", actor="alice")
    assert job.status == "completed"
    assert calls[0][1]["revision"] == "main"
    root = tmp_workspace / "datasets" / "input"
    assert len(list((root / "yes").glob("*.wav"))) == 3 and len(list((root / "no").glob("*.wav"))) == 3
    prov = json.loads((root / ".ingest" / "j1.json").read_text())
    assert prov["source"]["repo_id"] == "org/kw" and prov["source"]["resolved_sha"] == "abc123"
    assert prov["source"]["rows_read"] == 6 and prov["file_count"] == 6 and prov["content_hash"]
    events = [json.loads(line) for line in (tmp_workspace / "audit" / "events.jsonl").read_text().splitlines()]
    fin = [e for e in events if e["action"] == "dataset.ingest_finish"][-1]
    assert fin["actor"] == "alice" and fin["metadata"]["content_hash"] == prov["content_hash"]
    summary = job.read_progress()[-1]
    assert summary["type"] == "summary" and summary["resolved_sha"] == "abc123"


def test_hf_label_override_blank_is_ignored(tmp_workspace: Path, monkeypatch):
    from app.domain.ingestion import IngestionJob, IngestionService

    _install_fake(monkeypatch, [])
    job = IngestionJob(job_id="j2", status="running")
    IngestionService()._run_hf_job(job, "org/kw", "train", "audio", "label", "  ", max_rows=2)
    root = tmp_workspace / "datasets" / "input"
    assert (root / "no").is_dir() and not (root / "default").exists()


def test_cli_data_commands(tmp_workspace: Path, tmp_path: Path, capsys):
    import argparse

    from app.cli.cmd_data import cmd_data_download, cmd_data_ls, cmd_data_snapshot, cmd_data_upload

    src = tmp_path / "pick"
    (src / "yes").mkdir(parents=True)
    (src / "yes" / "a.wav").write_bytes(b"RIFF")
    (src / "readme.md").write_text("x")
    cmd_data_upload(argparse.Namespace(paths=[str(src)], label="misc", folders_as_labels=True, json=True))
    up = json.loads(capsys.readouterr().out)
    assert sorted(up["labels"]) == ["misc", "yes"]
    cmd_data_ls(argparse.Namespace(label=None, outputs=False, json=True))
    labels = {r["label"] for r in json.loads(capsys.readouterr().out)}
    assert labels == {"misc", "yes"}
    cmd_data_snapshot(argparse.Namespace(label="yes", json=True))
    snap = json.loads(capsys.readouterr().out)
    assert snap["project"] == "_inputs/yes" and snap["version"] == "v1"
    out = tmp_path / "o.zip"
    cmd_data_download(argparse.Namespace(target="_inputs/yes/v1", output=str(out), json=True))
    capsys.readouterr()
    import zipfile

    assert "_inputs_yes_v1/manifest.json" in zipfile.ZipFile(out).namelist()
    events = [json.loads(line)["action"] for line in (tmp_workspace / "audit" / "events.jsonl").read_text().splitlines()]
    assert {"dataset.upload", "dataset.snapshot", "dataset.download"} <= set(events)
