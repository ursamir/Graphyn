# unit_test/api/test_data_ops_audit.py
"""Datasets: generic listings, uploads (multi / folder / archive), snapshots,
zip downloads, stats, immutable merge and dataset.* audit events."""
from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

API = "/api/v1/data"


def _events(ws: Path) -> list[dict]:
    path = ws / "audit" / "events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _actions(ws: Path) -> list[str]:
    return [e["action"] for e in _events(ws)]


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def inp(tmp_workspace: Path) -> Path:
    root = tmp_workspace / "datasets" / "input"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _upload(api_client, files, **form):
    return api_client.post(f"{API}/inputs/upload", files=files, data=form)


class TestGenericListing:
    def test_counts_include_non_audio(self, api_client, inp):
        (inp / "docs").mkdir()
        (inp / "docs" / "a.csv").write_text("x,y\n")
        (inp / "docs" / "b.md").write_text("# hi")
        (inp / "docs" / "c.wav").write_bytes(b"RIFF")
        (inp / ".ingest").mkdir()
        rows = api_client.get(f"{API}/inputs").json()
        assert [r["label"] for r in rows] == ["docs"]
        assert rows[0]["file_count"] == 3 and rows[0]["audio_count"] == 1

    def test_label_files_have_kind(self, api_client, inp):
        (inp / "docs").mkdir()
        (inp / "docs" / "a.csv").write_text("x,y\n")
        (inp / "docs" / "n.json").write_text("{}")
        rows = api_client.get(f"{API}/inputs/docs").json()
        kinds = {r["path"]: r["kind"] for r in rows}
        assert kinds == {"docs/a.csv": "table", "docs/n.json": "json"}

    def test_input_file_serves_csv(self, api_client, inp):
        (inp / "docs").mkdir()
        (inp / "docs" / "a.csv").write_text("x,y\n")
        resp = api_client.get(f"{API}/inputs/file", params={"path": "docs/a.csv"})
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")

    def test_input_file_download_audited(self, api_client, inp, tmp_workspace):
        (inp / "docs").mkdir()
        (inp / "docs" / "a.csv").write_text("x,y\n")
        # Preview (no download=) is not audited.
        assert api_client.get(f"{API}/inputs/file", params={"path": "docs/a.csv"}).status_code == 200
        before = [e for e in _events(tmp_workspace) if "download" in e.get("action", "")]
        resp = api_client.get(f"{API}/inputs/file", params={"path": "docs/a.csv", "download": 1})
        assert resp.status_code == 200
        assert "attachment" in (resp.headers.get("content-disposition") or "").lower()
        after = [e for e in _events(tmp_workspace) if "download" in e.get("action", "")]
        assert len(after) == len(before) + 1
        assert after[-1]["action"] in ("run.output_download", "model.download", "dataset.download")


class TestUpload:
    def test_multi_file_into_new_label_with_sha256_and_audit(self, api_client, inp, tmp_workspace):
        resp = _upload(
            api_client,
            [("files", ("a.wav", b"RIFF1", "audio/wav")), ("files", ("notes.txt", b"hello", "text/plain"))],
            label="fresh",
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["count"] == 2 and body["labels"] == ["fresh"]
        import hashlib

        sha = {f["path"]: f["sha256"] for f in body["files"]}
        assert sha["fresh/notes.txt"] == hashlib.sha256(b"hello").hexdigest()
        ev = [e for e in _events(tmp_workspace) if e["action"] == "dataset.upload"][-1]
        assert ev["metadata"]["count"] == 2 and ev["metadata"]["total_bytes"] == 10
        assert {f["sha256"] for f in ev["metadata"]["files"]} == set(sha.values())

    def test_folder_upload_strips_picked_folder(self, api_client, inp):
        resp = _upload(
            api_client,
            [("files", ("pick/sub/a.wav", b"RIFF", "audio/wav")), ("files", ("pick/b.csv", b"1", "text/csv"))],
            label="target",
        )
        paths = sorted(f["path"] for f in resp.json()["files"])
        assert paths == ["target/b.csv", "target/sub/a.wav"]

    def test_strip_root_false_keeps_paths(self, api_client, inp):
        resp = _upload(
            api_client,
            [("files", ("sub/a.wav", b"R", "audio/wav")), ("files", ("sub/b.wav", b"S", "audio/wav"))],
            label="t",
            strip_root="false",
        )
        assert sorted(f["path"] for f in resp.json()["files"]) == ["t/sub/a.wav", "t/sub/b.wav"]

    def test_folders_as_labels(self, api_client, inp):
        resp = _upload(
            api_client,
            [("files", ("root/yes/a.wav", b"R1", "audio/wav")), ("files", ("root/no/b.wav", b"R2", "audio/wav"))],
            label="uploads",
            folders_as_labels="true",
        )
        assert sorted(resp.json()["labels"]) == ["no", "yes"]

    def test_zip_labelled_folders_filters_members(self, api_client, inp):
        data = _zip_bytes({"yes/a.wav": b"R1", "no/b.wav": b"R2", "no/evil.exe": b"x", "../up.wav": b"x", ".hidden": b"x"})
        resp = _upload(api_client, [("files", ("set.zip", data, "application/zip"))], label="uploads")
        body = resp.json()
        # Default: class folders stay inside the chosen dataset (Dataset Ingest
        # labels by parent folder).
        assert sorted(f["path"] for f in body["files"]) == ["uploads/no/b.wav", "uploads/yes/a.wav"]
        reasons = {s["name"]: s["reason"] for s in body["skipped"]}
        assert "set.zip:no/evil.exe" in reasons and "set.zip:../up.wav" in reasons
        assert not (inp.parent / "up.wav").exists()

    def test_zip_split_into_datasets_when_asked(self, api_client, inp):
        data = _zip_bytes({"yes/a.wav": b"R1", "no/b.wav": b"R2"})
        resp = _upload(api_client, [("files", ("set.zip", data, "application/zip"))], label="uploads",
                       folders_as_labels="true")
        assert sorted(f["path"] for f in resp.json()["files"]) == ["no/b.wav", "yes/a.wav"]

    def test_upload_into_linked_dataset_has_clear_error(self, api_client, inp, tmp_path):
        outside = tmp_path / "examples_data"
        outside.mkdir()
        (inp / "linked").symlink_to(outside, target_is_directory=True)
        data = _zip_bytes({"linked/a.wav": b"R1"})
        resp = api_client.post(
            "/api/v1/data/inputs/upload",
            files=[("files", ("set.zip", data, "application/zip"))],
            data={"label": "uploads", "folders_as_labels": "true"},
        )
        assert resp.status_code == 400
        assert "linked" in resp.text and "read-only" in resp.text
        assert not any(outside.iterdir())

    def test_tar_symlink_skipped(self, api_client, inp):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo("cls/a.wav")
            info.size = 2
            tf.addfile(info, io.BytesIO(b"R1"))
            link = tarfile.TarInfo("cls/link.wav")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tf.addfile(link)
        resp = _upload(api_client, [("files", ("d.tgz", buf.getvalue(), "application/gzip"))])
        body = resp.json()
        assert [f["path"] for f in body["files"]] == ["uploads/cls/a.wav"]
        assert any(s["reason"] == "not a regular file" for s in body["skipped"])

    def test_archive_cap_rolls_back(self, api_client, inp, monkeypatch, tmp_workspace):
        monkeypatch.setenv("GRAPHYN_UPLOAD_MAX_ARCHIVE_FILES", "2")
        data = _zip_bytes({f"c/{i}.wav": b"R" for i in range(3)})
        resp = _upload(api_client, [("files", ("big.zip", data, "application/zip"))])
        assert resp.status_code == 413
        assert not (inp / "c").exists() or not any((inp / "c").iterdir())
        assert _events(tmp_workspace)[-1]["result"] == "failure"

    def test_request_size_cap(self, api_client, inp, monkeypatch):
        monkeypatch.setenv("GRAPHYN_UPLOAD_MAX_BYTES", "10")
        resp = _upload(api_client, [("files", ("a.wav", b"R" * 2000, "audio/wav"))])
        assert resp.status_code == 413
        assert not list((inp / "uploads").glob("*.wav")) if (inp / "uploads").exists() else True

    def test_duplicate_is_skipped_and_name_clash_renamed(self, api_client, inp):
        _upload(api_client, [("files", ("a.wav", b"R1", "audio/wav"))], label="d")
        again = _upload(api_client, [("files", ("a.wav", b"R1", "audio/wav")), ("files", ("x/a.wav", b"R2", "audio/wav"))], label="d")
        body = again.json()
        assert any(s["reason"].startswith("identical") for s in body["skipped"])
        assert [f["path"] for f in body["files"]] == ["d/a_1.wav"] or [f["path"] for f in body["files"]] == ["d/x/a.wav"]

    def test_invalid_label(self, api_client, inp):
        resp = _upload(api_client, [("files", ("a.wav", b"R", "audio/wav"))], label="../x")
        assert resp.status_code == 422


class TestSnapshotDownloadStats:
    def _label(self, inp: Path) -> None:
        (inp / "kw" / "yes").mkdir(parents=True)
        (inp / "kw" / "yes" / "a.wav").write_bytes(b"RIFF1")
        (inp / "kw" / "meta.csv").write_text("a\n")

    def test_snapshot_versions_listing_and_audit(self, api_client, inp, tmp_workspace):
        self._label(inp)
        first = api_client.post(f"{API}/inputs/kw/snapshot").json()
        second = api_client.post(f"{API}/inputs/kw/snapshot").json()
        # Unchanged data → the existing version is reused, never duplicated.
        assert (first["project"], first["version"], second["version"]) == ("_inputs/kw", "v1", "v1")
        assert second.get("reused") is True
        assert first["content_hash"] == second["content_hash"] and first["file_count"] == 2
        outs = api_client.get(f"{API}/outputs", params={"envelope": "0"}).json()
        snap = [o for o in outs if o["project"] == "_inputs/kw"][0]
        assert snap["versions"] == ["v1"] and snap["kind"] == "input_snapshot"
        detail = api_client.get(f"{API}/outputs/_inputs/kw/v1").json()
        assert detail["content_hash"] == first["content_hash"] and detail["source"]["label"] == "kw"
        assert "dataset.snapshot" in _actions(tmp_workspace)
        # input changes never touch the frozen copy
        (inp / "kw" / "yes" / "a.wav").write_bytes(b"CHANGED")
        again = api_client.get(f"{API}/outputs/_inputs/kw/v1").json()
        assert again["content_hash"] == first["content_hash"]
        # …and freezing the changed data creates the next version.
        changed = api_client.post(f"{API}/inputs/kw/snapshot").json()
        assert changed["version"] == "v2" and changed["content_hash"] != first["content_hash"]

    def test_input_zip_manifest_matches_snapshot(self, api_client, inp, tmp_workspace):
        self._label(inp)
        snap = api_client.post(f"{API}/inputs/kw/snapshot").json()
        resp = api_client.get(f"{API}/inputs/kw/zip")
        assert resp.status_code == 200 and resp.headers["content-type"] == "application/zip"
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert sorted(zf.namelist()) == ["kw/manifest.json", "kw/meta.csv", "kw/yes/a.wav"]
        assert json.loads(zf.read("kw/manifest.json"))["content_hash"] == snap["content_hash"]
        assert "dataset.download" in _actions(tmp_workspace)

    def test_output_zip(self, api_client, inp):
        self._label(inp)
        api_client.post(f"{API}/inputs/kw/snapshot")
        resp = api_client.get(f"{API}/outputs/_inputs/kw/v1/zip")
        names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
        assert "_inputs_kw_v1/manifest.json" in names and "_inputs_kw_v1/yes/a.wav" in names

    def test_stats(self, api_client, inp):
        self._label(inp)
        st = api_client.get(f"{API}/inputs/kw/stats").json()
        assert st["file_count"] == 2 and st["by_kind"] == {"audio": 1, "table": 1}
        assert {c["name"]: c["file_count"] for c in st["classes"]} == {"(root)": 1, "yes": 1}
        assert st["audio"]["count"] == 1

    def test_delete_label_audited_with_hash(self, api_client, inp, tmp_workspace):
        self._label(inp)
        resp = api_client.delete(f"{API}/inputs/kw")
        assert resp.status_code == 200 and resp.json()["file_count"] == 2
        ev = [e for e in _events(tmp_workspace) if e["action"] == "dataset.label_delete"][-1]
        assert ev["metadata"]["content_hash"] and ev["metadata"]["file_count"] == 2

    def test_delete_snapshot_cleans_parents(self, api_client, inp, tmp_workspace):
        self._label(inp)
        api_client.post(f"{API}/inputs/kw/snapshot")
        assert api_client.delete(f"{API}/outputs/_inputs/kw/v1").status_code == 200
        assert not (tmp_workspace / "datasets" / "output" / "_inputs").exists()

    def test_bad_snapshot_project_rejected(self, api_client, inp):
        assert api_client.get(f"{API}/outputs/a/b/v1").status_code == 400


class TestMergeImmutable:
    def _src(self, ws: Path, project: str, files: dict[str, bytes]) -> None:
        root = ws / "datasets" / "output" / project / "v1"
        for rel, data in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)

    def test_copies_all_files_and_audits(self, api_client, tmp_workspace):
        self._src(tmp_workspace, "a", {"train/yes/x.wav": b"R1", "notes/readme.md": b"#", "labels.csv": b"id,path,label,split\n"})
        self._src(tmp_workspace, "b", {"train/no/y.wav": b"R2", "notes/readme.md": b"other"})
        resp = api_client.post(
            f"{API}/merge",
            json={"sources": [{"project": "a", "version": "v1"}, {"project": "b", "version": "v1"}], "target_project": "m", "target_version": "v1"},
        )
        body = resp.json()
        assert resp.status_code == 200 and body["files_copied"] == 4
        tgt = tmp_workspace / "datasets" / "output" / "m" / "v1"
        assert (tgt / "notes" / "readme.md").read_bytes() == b"#"
        assert body["renamed"] and (tgt / body["renamed"][0]["to"]).read_bytes() == b"other"
        man = json.loads((tgt / "manifest.json").read_text())
        assert man["content_hash"] == body["content_hash"] and man["source"]["kind"] == "merge"
        assert "dataset.merge" in _actions(tmp_workspace)

    def test_existing_target_refused_then_overwrite(self, api_client, tmp_workspace):
        self._src(tmp_workspace, "a", {"x.wav": b"R"})
        self._src(tmp_workspace, "m", {"old.wav": b"O"})
        body = {"sources": [{"project": "a", "version": "v1"}], "target_project": "m", "target_version": "v1"}
        resp = api_client.post(f"{API}/merge", json=body)
        assert resp.status_code == 409 and "v2" in json.dumps(resp.json())
        resp = api_client.post(f"{API}/merge", json={**body, "overwrite": True})
        assert resp.status_code == 200
        assert not (tmp_workspace / "datasets" / "output" / "m" / "v1" / "old.wav").exists()

    def test_overwrite_referenced_refused(self, api_client, tmp_workspace):
        self._src(tmp_workspace, "a", {"x.wav": b"R"})
        self._src(tmp_workspace, "m", {"old.wav": b"O"})
        run = tmp_workspace / "runs" / "r1"
        run.mkdir(parents=True)
        (run / "meta.json").write_text(json.dumps({"dataset": "datasets/output/m/v1"}))
        resp = api_client.post(
            f"{API}/merge",
            json={"sources": [{"project": "a", "version": "v1"}], "target_project": "m", "target_version": "v1", "overwrite": True},
        )
        assert resp.status_code == 409 and "referenced" in json.dumps(resp.json())


def test_capabilities(api_client, tmp_workspace, monkeypatch):
    import importlib.util

    body = api_client.get(f"{API}/capabilities").json()
    assert body["upload"]["max_request_bytes"] > 0 and ".csv" in body["upload"]["allowed_extensions"]
    assert isinstance(body["ingest"]["huggingface"], bool)
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "datasets" else real(name, *a))
    body = api_client.get(f"{API}/capabilities").json()
    assert body["ingest"]["huggingface"] is False and body["ingest"]["huggingface_reason"]
    resp = api_client.post("/api/v1/ingest/huggingface", json={"repo_id": "org/ds"})
    assert resp.status_code == 503


def test_links_pin_unpin_audited(api_client, tmp_workspace):
    assert api_client.post("/api/v1/projects", json={"name": "wsx"}).status_code in (200, 201)
    api_client.post("/api/v1/projects/wsx/links", json={"inputs": ["kw"]})
    api_client.request("DELETE", "/api/v1/projects/wsx/links", json={"inputs": ["kw"]})
    acts = _actions(tmp_workspace)
    assert "dataset.link" in acts and "dataset.unlink" in acts


def test_audit_category_data(api_client, tmp_workspace):
    from app.core.trust.audit import AUDIT_CATEGORIES, audit_category

    assert "data" in AUDIT_CATEGORIES
    assert audit_category("dataset.upload") == "data" and audit_category("dataset.version_delete") == "data"


def test_dataset_version_recognises_dotted_and_snapshots(tmp_workspace):
    from app.core.runs.audit_record import _dataset_version

    out = tmp_workspace / "datasets" / "output"
    for rel in ("p/v1.0.0/x.wav", "_inputs/kw/v3/a.wav", "p/v2/b.wav"):
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_bytes(b"x")
    assert _dataset_version(out / "p" / "v1.0.0") == {"project": "p", "version": "v1.0.0"}
    assert _dataset_version(out / "_inputs" / "kw" / "v3") == {"project": "_inputs/kw", "version": "v3"}
    assert _dataset_version(out / "p" / "v2" / "b.wav") == {"project": "p", "version": "v2"}
    assert _dataset_version(out / "p" / "latest") is None


def test_hf_router_passes_fields(api_client, tmp_workspace):
    from unittest.mock import MagicMock, patch

    svc = MagicMock()
    svc.start_hf_job.return_value = "job"
    with patch("app.api.routers.ingest._svc", svc):
        resp = api_client.post(
            "/api/v1/ingest/huggingface",
            json={"repo_id": "org/kw", "split": "test", "label_col": "label", "label_override": "", "max_rows": 7, "revision": "v1.0"},
        )
    assert resp.status_code == 200
    kw = svc.start_hf_job.call_args.kwargs
    assert kw["label_override"] is None and kw["max_rows"] == 7 and kw["revision"] == "v1.0" and kw["split"] == "test"
    events = [json.loads(line) for line in (tmp_workspace / "audit" / "events.jsonl").read_text().splitlines()]
    assert events[-1]["action"] == "dataset.ingest_start"
