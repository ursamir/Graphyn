"""API /jobs complete + cancel: double-complete / double-cancel do not corrupt queue."""
from __future__ import annotations

import pytest

from app.core.distributed.models import JobResult, NodeJob, WorkerInfo
from app.core.distributed.queue import _reset_job_queue, get_job_queue
from app.core.distributed.registry import _reset_worker_registry, get_worker_registry


@pytest.fixture
def isolated_queue(monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    _reset_worker_registry()
    q = _reset_job_queue(use_memory=True, lease_ttl_s=60.0)
    yield q
    _reset_worker_registry()
    _reset_job_queue(use_memory=True)


def test_api_double_complete_returns_409_without_corrupting(api_client, isolated_queue):
    q = isolated_queue
    reg = get_worker_registry()
    reg.register(WorkerInfo(worker_id="api-w1", plugins=["x"]))
    q.enqueue(NodeJob(job_id="api-dc1", run_id="r", node_id="n", node_type="x"))
    claimed = q.claim(reg.get("api-w1"))
    assert claimed is not None
    gen = int(claimed.lease_generation or 0)

    body = {
        "job_id": "api-dc1",
        "status": "succeeded",
        "worker_id": "api-w1",
        "lease_generation": gen,
        "output_refs": {"out": "artifact://local/ok"},
    }
    first = api_client.post("/api/v1/jobs/api-dc1/complete", json=body)
    assert first.status_code == 200, first.text
    assert first.json()["job"]["status"] == "succeeded"

    # Second complete with different status must 409; queue stays succeeded.
    body2 = {
        **body,
        "status": "failed",
        "error": "should-not-overwrite",
        "output_refs": {},
    }
    second = api_client.post("/api/v1/jobs/api-dc1/complete", json=body2)
    assert second.status_code == 409
    assert "already terminal" in second.json()["detail"]

    status = api_client.get("/api/v1/jobs/api-dc1")
    assert status.status_code == 200
    payload = status.json()
    assert payload["job"]["status"] == "succeeded"
    assert payload["result"]["status"] == "succeeded"
    assert payload["result"].get("error") in (None, "")


def test_api_double_cancel_is_idempotent(api_client, isolated_queue):
    q = isolated_queue
    q.enqueue(NodeJob(job_id="api-can1", run_id="r", node_id="n", node_type="x"))

    first = api_client.post("/api/v1/jobs/api-can1/cancel")
    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"

    second = api_client.post("/api/v1/jobs/api-can1/cancel")
    assert second.status_code == 200
    assert second.json()["status"] == "cancelled"

    status = api_client.get("/api/v1/jobs/api-can1")
    assert status.status_code == 200
    assert status.json()["job"]["status"] == "cancelled"
    assert status.json()["result"]["status"] == "cancelled"


def test_api_concurrent_cancel_and_status(api_client, isolated_queue):
    """Optional lightweight: cancel then status stay consistent via TestClient."""
    q = isolated_queue
    q.enqueue(NodeJob(job_id="api-cs1", run_id="r", node_id="n", node_type="x"))
    cancel = api_client.post("/api/v1/jobs/api-cs1/cancel")
    status = api_client.get("/api/v1/jobs/api-cs1")
    assert cancel.status_code == 200
    assert status.status_code == 200
    assert status.json()["job"]["status"] == "cancelled"
    # Queue singleton used by API matches fixture.
    assert get_job_queue().is_cancelled("api-cs1")
