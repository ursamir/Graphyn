# unit_test/api/test_ship_packages.py
"""Ship packages REST + lifecycle (SRS §9.2.14 / §19) — Wave A."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def ship_project(tmp_workspace: Path):
    """Create a dataset project + register a model for ship create."""
    from app.core.model_registry import register_model
    from app.domain.project_manager import ProjectManager

    pm = ProjectManager()
    meta = pm.create("ship-demo")
    assert meta["name"] == "ship-demo"
    register_model(
        "edge-model",
        run_id="run-ship-1",
        slug="edge_slug",
        stage="staging",
        actor="tester",
    )
    return "ship-demo"


class TestShipPackagesRest:
    def test_create_requires_idempotency_key(self, api_client, ship_project):
        r = api_client.post(
            f"/api/v1/projects/{ship_project}/ship/packages",
            json={
                "model_name": "edge-model",
                "model_stage_or_version": "staging",
                "target": {"runtime": "tflite", "arch": "arm"},
            },
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "bad_request"

    def test_create_list_get_download_lifecycle(self, api_client, ship_project, tmp_workspace):
        from app.api import idempotency as idem

        idem._MEMORY.clear()
        headers = {"Idempotency-Key": "ship-create-1", "X-Actor": "tester"}
        body = {
            "model_name": "edge-model",
            "model_stage_or_version": "staging",
            "target": {"runtime": "tflite", "arch": "arm"},
            "env": "draft",
            "unsigned_allowed": True,
        }
        r = api_client.post(
            f"/api/v1/projects/{ship_project}/ship/packages",
            json=body,
            headers=headers,
        )
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["package_id"]
        assert created["status"] in ("ready", "signed", "built")
        assert created["manifest"]["checksums"]["sha256"]
        pid = created["package_id"]

        # Idempotent replay
        r2 = api_client.post(
            f"/api/v1/projects/{ship_project}/ship/packages",
            json=body,
            headers=headers,
        )
        assert r2.status_code == 201
        assert r2.headers.get("Idempotent-Replay") == "true"
        assert r2.json()["package_id"] == pid

        listed = api_client.get(f"/api/v1/projects/{ship_project}/ship/packages")
        assert listed.status_code == 200
        assert listed.json()["total"] >= 1
        assert any(i["package_id"] == pid for i in listed.json()["items"])

        got = api_client.get(f"/api/v1/projects/{ship_project}/ship/packages/{pid}")
        assert got.status_code == 200
        assert got.json()["package_id"] == pid
        assert got.json()["checksums"]["sha256"]

        dl = api_client.get(f"/api/v1/projects/{ship_project}/ship/packages/{pid}/download")
        assert dl.status_code == 200
        assert dl.headers.get("X-Content-SHA256")
        assert dl.content[:2] == b"PK"  # zip magic

        # Illegal transition: fail from signed is OK; draft action validate illegal from signed
        bad = api_client.post(
            f"/api/v1/projects/{ship_project}/ship/packages/{pid}/transition",
            json={"action": "validate"},
        )
        assert bad.status_code == 409
        assert bad.json()["error"]["code"] == "invalid_transition"

        # Promote to staging
        promo = api_client.post(
            f"/api/v1/projects/{ship_project}/ship/packages/{pid}/promote",
            json={"to_env": "staging"},
            headers={"Idempotency-Key": "ship-promo-1", "X-Actor": "tester"},
        )
        assert promo.status_code == 200, promo.text
        assert promo.json()["env"] == "staging"
        assert promo.json()["status"] == "published"

        # Prod without approve → 400
        no_approve = api_client.post(
            f"/api/v1/projects/{ship_project}/ship/packages/{pid}/promote",
            json={"to_env": "prod", "approve": False},
            headers={"Idempotency-Key": "ship-promo-prod-deny", "X-Actor": "tester"},
        )
        assert no_approve.status_code == 400

        # Prod with approve
        ok_prod = api_client.post(
            f"/api/v1/projects/{ship_project}/ship/packages/{pid}/promote",
            json={"to_env": "prod", "approve": True},
            headers={"Idempotency-Key": "ship-promo-prod-ok", "X-Actor": "tester"},
        )
        assert ok_prod.status_code == 200
        assert ok_prod.json()["env"] == "prod"

    def test_model_missing_404(self, api_client, ship_project):
        from app.api import idempotency as idem

        idem._MEMORY.clear()
        r = api_client.post(
            f"/api/v1/projects/{ship_project}/ship/packages",
            json={
                "model_name": "no-such-model",
                "model_stage_or_version": "staging",
                "target": {"runtime": "onnx", "arch": "x86"},
            },
            headers={"Idempotency-Key": "ship-missing-model"},
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"

    def test_core_transition_matrix(self, tmp_workspace, ship_project):
        from app.core.ship_packages import (
            InvalidPackageTransition,
            create_package,
            next_status,
            transition_package,
        )
        from app.domain.project_manager import ProjectManager

        project_dir = ProjectManager()._require_project(ship_project)
        created = create_package(
            project_dir,
            project_name=ship_project,
            model_name="edge-model",
            model_stage_or_version="staging",
            target={"runtime": "tflite", "arch": "arm"},
            unsigned_allowed=True,
            actor="tester",
        )
        pid = created["package_id"]
        # create ends at signed when unsigned_allowed
        assert next_status("signed", "publish") == "published"
        with pytest.raises(InvalidPackageTransition):
            next_status("draft", "publish")
        got = transition_package(project_dir, pid, "publish", actor="tester")
        assert got["status"] == "published"
        got2 = transition_package(project_dir, pid, "deploy", actor="tester")
        assert got2["status"] == "deployed"
        with pytest.raises(InvalidPackageTransition):
            transition_package(project_dir, pid, "validate", actor="tester")
