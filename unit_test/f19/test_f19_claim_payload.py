# unit_test/f19/test_f19_claim_payload.py
"""F19 / F-03 (found live in Mode B): F18 nested ``worker_slots`` inside the claimed
``job``; the worker validates ``job`` as a strict ``NodeJob`` so every remote job
failed with ``extra_forbidden`` (run 80159e9d). ``worker_slots`` now sits beside
``job`` and the worker ignores unknown job keys.
"""
from __future__ import annotations

import pytest

from app.core.distributed.models import NodeJob, WorkerInfo
from app.core.distributed.queue import _reset_job_queue
from app.core.distributed.registry import _reset_worker_registry, get_worker_registry



@pytest.fixture(autouse=True)
def _no_mtls(monkeypatch):
    # Another suite test can leave mTLS material in os.environ; worker routes
    # would then demand a client cert. These tests exercise the plain-token path.
    monkeypatch.setenv("GRAPHYN_MTLS_ENABLED", "0")

@pytest.fixture
def env(tmp_path, monkeypatch, real_threads):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_API_TOKENS", "op:op-tok")
    for k in ("GRAPHYN_AUTH_REQUIRED", "GRAPHYN_API_TOKEN", "GRAPHYN_POOL_MAX_CLAIMED", "GRAPHYN_WORKER_TRUST_REQUIRED"):
        monkeypatch.delenv(k, raising=False)
    _reset_worker_registry()
    q = _reset_job_queue(use_memory=True, lease_ttl_s=60.0)
    yield q
    _reset_worker_registry()
    _reset_job_queue(use_memory=True)


def test_claimed_job_validates_as_strict_nodejob(api_client, env):
    get_worker_registry().register(WorkerInfo(worker_id="w1", plugins=["python_code"], max_claimed=2))
    env.enqueue(NodeJob(job_id="j1", run_id="r1", node_id="n1", node_type="python_code"))
    r = api_client.post("/api/v1/jobs/claim", json={"worker_id": "w1"}, headers={"Authorization": "Bearer op-tok"})
    assert r.status_code == 200, r.text
    body = r.json()
    job = NodeJob.model_validate(body["job"])  # strict: raises on any extra key
    assert job.job_id == "j1"
    assert "worker_slots" not in body["job"]
    assert body["worker_slots"]["max_slots"] == 2 and body["worker_slots"]["used_slots"] == 1


def test_worker_ignores_unknown_job_keys():
    from app.cli.cmd_worker import _job_model_payload

    raw = NodeJob(job_id="j2", run_id="r1", node_id="n1", node_type="trainer").model_dump(mode="json")
    raw["worker_slots"] = {"max_slots": None, "used_slots": 1, "free_slots": None}
    raw["future_field"] = 1
    assert NodeJob.model_validate(_job_model_payload(raw)).job_id == "j2"


def test_openapi_claim_response_documents_top_level_slots():
    from app.api.queue_schemas import ClaimedJob, ClaimResponse

    assert "worker_slots" in ClaimResponse.model_fields
    assert "worker_slots" not in ClaimedJob.model_fields
