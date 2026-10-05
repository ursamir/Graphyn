# unit_test/api/test_download_audit.py
"""Explicit downloads are audited (who took which bytes); previews are not."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

RUN = "c" * 32


def _isolate(tmp_path, monkeypatch) -> Path:
    ws = tmp_path / "workspace"
    home = tmp_path / "graphyn-home"
    ws.mkdir()
    home.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
    monkeypatch.setenv("GRAPHYN_HOME", str(home))
    return ws


def _events(ws: Path) -> list[dict]:
    path = ws / "audit" / "events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _downloads(ws: Path) -> list[dict]:
    return [e for e in _events(ws) if str(e.get("action", "")).endswith(("download", "outputs_zip"))]


def test_preview_fetch_is_not_audited(api_client, tmp_path, monkeypatch):
    ws = _isolate(tmp_path, monkeypatch)
    f = ws / "artifacts" / "demo" / "metrics.json"
    f.parent.mkdir(parents=True)
    f.write_text('{"a": 1}')
    resp = api_client.get("/api/v1/outputs/file", params={"path": str(f)})
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("inline")
    assert _downloads(ws) == []


def test_explicit_package_download_audited_with_sha(api_client, tmp_path, monkeypatch):
    ws = _isolate(tmp_path, monkeypatch)
    pkg = ws / "artifacts" / "edge-deploy" / "runs" / RUN / "packages" / "kws_edge.tar.gz"
    pkg.parent.mkdir(parents=True)
    pkg.write_bytes(b"package-bytes")
    resp = api_client.get(
        "/api/v1/outputs/file",
        params={"path": str(pkg), "download": 1},
        headers={"X-Actor": "alice"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment")
    (ev,) = _downloads(ws)
    assert ev["action"] == "model.download"
    assert ev["actor"] == "alice"
    meta = ev.get("meta") or ev.get("metadata") or {}
    assert meta["sha256"] == hashlib.sha256(b"package-bytes").hexdigest()
    assert meta["size_bytes"] == len(b"package-bytes")
    assert meta["run_id"] == RUN and meta["file"] == "kws_edge.tar.gz"


def test_known_manifest_sha_is_reused(api_client, tmp_path, monkeypatch):
    ws = _isolate(tmp_path, monkeypatch)
    pkg = ws / "artifacts" / "p" / "m.zip"
    pkg.parent.mkdir(parents=True)
    pkg.write_bytes(b"zzz")
    (pkg.parent / "m.zip.manifest.json").write_text(json.dumps({"sha256": "a" * 64}))
    resp = api_client.get("/api/v1/outputs/file", params={"path": str(pkg), "download": "1"})
    assert resp.status_code == 200
    (ev,) = _downloads(ws)
    assert (ev.get("meta") or ev.get("metadata"))["sha256"] == "a" * 64


def test_explicit_output_download_category_run(api_client, tmp_path, monkeypatch):
    ws = _isolate(tmp_path, monkeypatch)
    f = ws / "artifacts" / "demo" / "metrics.json"
    f.parent.mkdir(parents=True)
    f.write_text('{"a": 1}')
    resp = api_client.get("/api/v1/outputs/file", params={"path": str(f), "download": "true"})
    assert resp.status_code == 200
    (ev,) = _downloads(ws)
    assert ev["action"] == "run.output_download"
    from app.core.trust.audit import audit_category, audit_label

    assert audit_category("run.output_download") == "run"
    assert audit_category("model.download") == "model"
    assert audit_category("ship.download") == "model"
    assert audit_label("ship.download") == "Ship package downloaded"


def test_run_outputs_zip_audited(api_client, tmp_path, monkeypatch):
    ws = _isolate(tmp_path, monkeypatch)
    from app.core.config import runs_dir

    rd = Path(runs_dir()) / RUN
    rd.mkdir(parents=True)
    (rd / "meta.json").write_text(json.dumps({"run_id": RUN, "status": "succeeded"}))
    resp = api_client.get(f"/api/v1/runs/{RUN}/outputs/zip", headers={"X-Actor": "bob"})
    assert resp.status_code == 200
    (ev,) = _downloads(ws)
    assert ev["action"] == "run.outputs_zip" and ev["actor"] == "bob"
    assert ev["resource_id"] == RUN
    meta = ev.get("meta") or ev.get("metadata")
    assert meta["sha256"] == hashlib.sha256(resp.content).hexdigest()
    assert meta["size_bytes"] == len(resp.content)


def test_ship_package_download_audited(api_client, tmp_path, monkeypatch):
    ws = _isolate(tmp_path, monkeypatch)
    archive = tmp_path / "pkg.zip"
    archive.write_bytes(b"zipbytes")
    with patch("app.api.routers.ship._require_project", return_value=tmp_path), patch(
        "app.core.mlops.ship_packages.download_package_path",
        return_value=(archive, {"checksums": {"sha256": "b" * 64}}),
    ):
        resp = api_client.get("/api/v1/projects/demo/ship/packages/pkg_1/download")
    assert resp.status_code == 200
    (ev,) = _downloads(ws)
    assert ev["action"] == "ship.download" and ev["resource_id"] == "pkg_1"
    meta = ev.get("meta") or ev.get("metadata")
    assert meta["sha256"] == "b" * 64 and meta["size_bytes"] == 8 and meta["project"] == "demo"
