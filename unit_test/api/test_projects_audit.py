"""Workspace (project) mutations record ``workspace.*`` audit events (category admin)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _events(ws: Path) -> list[dict]:
    path = ws / "audit" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _actions(ws: Path) -> list[str]:
    return [e["action"] for e in _events(ws)]


def _last(ws: Path, action: str) -> dict:
    matches = [e for e in _events(ws) if e["action"] == action]
    assert matches, f"no {action} event; got {_actions(ws)}"
    return matches[-1]


@pytest.fixture
def ws(tmp_workspace: Path, api_client) -> Path:
    resp = api_client.post("/api/v1/projects", json={"name": "alpha"})
    assert resp.status_code == 200, resp.text
    return tmp_workspace


def test_create_records_event(ws):
    ev = _last(ws, "workspace.created")
    assert ev["resource_type"] == "workspace" and ev["resource_id"] == "alpha"


def test_put_metadata_records_changed_fields(api_client, ws):
    resp = api_client.put(
        "/api/v1/projects/alpha",
        json={"display_name": "Alpha keyword spotting", "description": "KWS experiments"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "alpha"
    ev = _last(ws, "workspace.updated")
    assert ev["resource_id"] == "alpha"
    assert ev["meta"]["changed"] == ["description", "display_name"]
    assert ev["after"] == {"display_name": "Alpha keyword spotting", "description": "KWS experiments"}
    # A no-op PUT records nothing new.
    n = _actions(ws).count("workspace.updated")
    api_client.put("/api/v1/projects/alpha", json={"description": "KWS experiments"})
    assert _actions(ws).count("workspace.updated") == n


def test_archive_unarchive_and_status(api_client, ws):
    assert api_client.patch("/api/v1/projects/alpha/status", json={"status": "archived"}).status_code == 200
    ev = _last(ws, "workspace.archived")
    assert ev["before"] == {"status": "draft"} and ev["after"] == {"status": "archived"}
    assert api_client.patch("/api/v1/projects/alpha/status", json={"status": "in-progress"}).status_code == 200
    assert _last(ws, "workspace.unarchived")["after"] == {"status": "in-progress"}
    assert api_client.patch("/api/v1/projects/alpha/status", json={"status": "ready"}).status_code == 200
    assert _last(ws, "workspace.status_changed")["after"] == {"status": "ready"}


def test_clone_records_event_and_copies_pipelines(api_client, ws):
    src = ws / "datasets" / "output" / "alpha"
    (src / "pipelines").mkdir(parents=True, exist_ok=True)
    (src / "pipelines" / "train.graph.json").write_text(
        json.dumps({"nodes": [], "edges": [], "metadata": {"name": "train", "project": "alpha"}})
    )
    (src / "pipelines" / "train" / "versions").mkdir(parents=True)
    (src / "pipelines" / "train" / "versions" / "v1.graph.json").write_text("{}")
    resp = api_client.post("/api/v1/projects/alpha/clone", json={"new_name": "beta"})
    assert resp.status_code == 200, resp.text
    ev = _last(ws, "workspace.cloned")
    assert ev["resource_id"] == "beta" and ev["meta"]["source"] == "alpha"
    dst = ws / "datasets" / "output" / "beta" / "pipelines"
    copied = json.loads((dst / "train.graph.json").read_text())
    assert copied["metadata"]["project"] == "beta"
    assert not (dst / "train").exists()  # version history is not copied


def test_rename_records_deprecated_event(api_client, ws):
    resp = api_client.patch("/api/v1/projects/alpha", json={"new_name": "gamma"})
    assert resp.status_code == 200, resp.text
    ev = _last(ws, "workspace.renamed")
    assert ev["before"] == {"name": "alpha"} and ev["after"] == {"name": "gamma"}
    assert ev["meta"]["deprecated"] is True and ev["meta"]["migrated"] is False


def test_delete_records_what_was_removed(api_client, ws):
    src = ws / "datasets" / "output" / "alpha"
    (src / "v1").mkdir()
    (src / "pipelines").mkdir(exist_ok=True)
    (src / "pipelines" / "train.graph.json").write_text(json.dumps({"nodes": [], "edges": []}))
    bad = api_client.request("DELETE", "/api/v1/projects/alpha", json={"confirm": "nope"})
    assert bad.status_code == 422
    assert "workspace.deleted" not in _actions(ws)
    resp = api_client.request("DELETE", "/api/v1/projects/alpha", json={"confirm": "alpha"})
    assert resp.status_code == 200, resp.text
    ev = _last(ws, "workspace.deleted")
    assert ev["resource_id"] == "alpha"
    assert ev["meta"]["removed"]["pipelines"] == ["train"]
    assert ev["meta"]["removed"]["dataset_versions"] == ["v1"]


def test_spec_taxonomy_contract_snapshot_and_version_restore(api_client, ws):
    assert api_client.put("/api/v1/projects/alpha/spec", json={"markdown": "# hi"}).status_code == 200
    assert api_client.put("/api/v1/projects/alpha/taxonomy", json=[{"name": "yes"}]).status_code == 200
    assert api_client.put("/api/v1/projects/alpha/contract", json={"min_samples": 3}).status_code == 200
    assert api_client.post("/api/v1/projects/alpha/snapshots", json={"snapshot_name": "s1"}).status_code == 200
    assert api_client.post("/api/v1/projects/alpha/snapshots/s1/restore").status_code == 200
    (ws / "datasets" / "output" / "alpha" / "v1").mkdir()
    assert api_client.post("/api/v1/projects/alpha/versions/v1/restore").status_code == 200
    acts = _actions(ws)
    for a in (
        "workspace.spec_updated",
        "workspace.taxonomy_updated",
        "workspace.contract_updated",
        "workspace.snapshot_created",
        "workspace.snapshot_restored",
        "workspace.version_restored",
    ):
        assert a in acts
    assert _last(ws, "workspace.version_restored")["resource_id"] == "alpha/v1"


def test_audit_listing_labels_and_category(api_client, ws):
    api_client.patch("/api/v1/projects/alpha/status", json={"status": "archived"})
    resp = api_client.get("/api/v1/audit", params={"category": "admin", "limit": 50})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body.get("items", body.get("events", body)) if isinstance(body, dict) else body
    by_action = {e["action"]: e for e in items}
    assert by_action["workspace.archived"]["label"] == "Workspace archived"
    assert by_action["workspace.archived"]["category"] == "admin"
    assert by_action["workspace.created"]["label"] == "Workspace created"


def test_failed_mutation_records_nothing(api_client, ws):
    before = len(_events(ws))
    resp = api_client.patch("/api/v1/projects/alpha/status", json={"status": "bogus"})
    assert resp.status_code == 422
    resp = api_client.post("/api/v1/projects/missing/clone", json={"new_name": "x"})
    assert resp.status_code == 404
    assert len(_events(ws)) == before
