# unit_test/f19/test_f19_openapi_cancel.py
"""F19 — carried F18 items: OpenAPI schemas for queue/slot/quota endpoints and
consistent RT-CANCEL-003 ``run_cancelled`` (409) for every post-cancel commit path.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import queue_schemas as qs
from app.core.distributed.models import NodeJob, WorkerInfo
from app.core.distributed.queue import JobCancelled, _reset_job_queue
from app.core.distributed.registry import _reset_worker_registry, get_worker_registry

DOCUMENTED = [
    ("get", "/api/v1/workers"),
    ("patch", "/api/v1/workers/{worker_id}"),
    ("get", "/api/v1/jobs/queue"),
    ("post", "/api/v1/jobs/claim"),
    ("get", "/api/v1/jobs/{job_id}"),
    ("post", "/api/v1/jobs/{job_id}/complete"),
    ("post", "/api/v1/jobs/{job_id}/cancel"),
    ("get", "/api/v1/orgs/{org_id}/usage"),
    ("get", "/api/v1/orgs/{org_id}/quotas"),
    ("put", "/api/v1/orgs/{org_id}/quotas"),
]



@pytest.fixture(autouse=True)
def _no_mtls(monkeypatch):
    # Another suite test can leave mTLS material in os.environ; worker routes
    # would then demand a client cert. These tests exercise the plain-token path.
    monkeypatch.setenv("GRAPHYN_MTLS_ENABLED", "0")

@pytest.fixture(autouse=True)
def _threads(real_threads):
    yield


@pytest.fixture
def q(monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    _reset_worker_registry()
    queue = _reset_job_queue(use_memory=True, lease_ttl_s=60.0)
    yield queue
    _reset_worker_registry()
    _reset_job_queue(use_memory=True)


def _documented_keys(model, data: dict, where: str) -> None:
    undocumented = sorted(set(data) - set(model.model_fields))
    assert not undocumented, f"{where}: undocumented keys {undocumented}"
    model.model_validate(data)


def test_f18_endpoints_publish_response_schemas(api_client):
    spec = api_client.get("/openapi.json").json()
    for method, path in DOCUMENTED:
        op = spec["paths"][path][method]
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema and schema != {}, f"{method.upper()} {path} has an empty schema"
    names = set(spec["components"]["schemas"])
    assert {"JobQueueView", "WorkerRow", "OrgQuotaView", "OrgUsageView", "ClaimResponse"} <= names


def test_live_responses_match_documented_models(api_client, q):
    reg = get_worker_registry()
    reg.register(WorkerInfo(worker_id="f19-w1", plugins=["x"]))
    q.enqueue(NodeJob(job_id="f19-j1", run_id="r1", node_id="n", node_type="x"))
    q.enqueue(NodeJob(job_id="f19-j2", run_id="r1", node_id="n2", node_type="x"))

    rows = api_client.get("/api/v1/workers").json()
    assert rows
    for row in rows:
        _documented_keys(qs.WorkerRow, row, "GET /workers")

    view = api_client.get("/api/v1/jobs/queue").json()
    _documented_keys(qs.JobQueueView, view, "GET /jobs/queue")
    for row in view["queue"]:
        _documented_keys(qs.QueueRow, row, "queue row")
    for row in view["worker_slots"]:
        _documented_keys(qs.WorkerSlotRow, row, "worker_slots row")

    claim = api_client.post("/api/v1/jobs/claim", json={"worker_id": "f19-w1"}).json()
    _documented_keys(qs.ClaimResponse, claim, "POST /jobs/claim")
    _documented_keys(qs.ClaimedJob, claim["job"], "claimed job")
    job_id, gen = claim["job"]["job_id"], int(claim["job"].get("lease_generation") or 0)

    status = api_client.get(f"/api/v1/jobs/{job_id}").json()
    _documented_keys(qs.JobStatusView, status, "GET /jobs/{id}")

    done = api_client.post(
        f"/api/v1/jobs/{job_id}/complete",
        json={"job_id": job_id, "status": "succeeded", "worker_id": "f19-w1", "lease_generation": gen},
    )
    assert done.status_code == 200, done.text
    _documented_keys(qs.JobCompleteResponse, done.json(), "POST /jobs/{id}/complete")

    # Org endpoints need a signed-in user; validate the exact payloads their
    # handlers return (MeterStore.public()) against the documented models.
    from app.core.trust.metering import get_meter_store

    store = get_meter_store()
    _documented_keys(qs.OrgQuotaView, store.get_quota("org_default").public(), "quotas")
    usage = {"usage": store.usage("org_default").public(), "quota": store.get_quota("org_default").public()}
    _documented_keys(qs.OrgUsageView, usage, "usage view")
    _documented_keys(qs.OrgUsage, usage["usage"], "usage")


def test_complete_after_cancel_is_409_run_cancelled(api_client, q):
    reg = get_worker_registry()
    reg.register(WorkerInfo(worker_id="f19-w2", plugins=["x"]))
    q.enqueue(NodeJob(job_id="f19-c1", run_id="r2", node_id="n", node_type="x"))
    claimed = q.claim(reg.get("f19-w2"))
    gen = int(claimed.lease_generation or 0)
    assert api_client.post("/api/v1/jobs/f19-c1/cancel").status_code == 200

    blob = api_client.post(
        "/api/v1/artifacts/blob",
        params={"key": f"jobs/f19-c1/g{gen}/output", "worker_id": "f19-w2"},
        content=b"late bytes",
    )
    assert blob.status_code == 409, blob.text
    assert blob.json()["error"]["code"] == "run_cancelled"

    r = api_client.post(
        "/api/v1/jobs/f19-c1/complete",
        json={
            "job_id": "f19-c1",
            "status": "succeeded",
            "worker_id": "f19-w2",
            "lease_generation": gen,
            "output_refs": {"output": "artifact://local/late"},
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "run_cancelled"
    assert api_client.get("/api/v1/jobs/f19-c1").json()["job"]["status"] == "cancelled"


def test_queue_complete_after_cancel_raises_coded_error(q):
    from app.core.distributed.models import JobResult

    reg = get_worker_registry()
    reg.register(WorkerInfo(worker_id="f19-w3", plugins=["x"]))
    q.enqueue(NodeJob(job_id="f19-c2", run_id="r3", node_id="n", node_type="x"))
    claimed = q.claim(reg.get("f19-w3"))
    q.cancel("f19-c2")
    with pytest.raises(JobCancelled) as ei:
        q.complete(JobResult(job_id="f19-c2", status="succeeded", worker_id="f19-w3",
                             lease_generation=claimed.lease_generation))
    assert ei.value.code == "run_cancelled"
    assert isinstance(ei.value, ValueError)  # old "already terminal" handlers still apply


def test_artifact_commit_forbidden_maps_to_run_cancelled():
    from app.api.errors import register_exception_handlers
    from app.core.runs.run_journal import ArtifactCommitForbidden

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise ArtifactCommitForbidden("Cannot commit artifact for cancelled run r9")

    r = TestClient(app).get("/boom")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "run_cancelled"
    assert ArtifactCommitForbidden.code == "run_cancelled"
