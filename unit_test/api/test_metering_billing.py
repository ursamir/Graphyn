"""Wave 3: org quotas, meter events, billing webhook HMAC."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.core.trust.metering import get_meter_store, reset_meter_store
from app.core.trust.orgs import DEFAULT_ORG_ID, get_org_store, reset_org_store
from app.core.trust.users import get_user_store, reset_user_store


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    yield


@pytest.fixture
def client_store(tmp_path, monkeypatch, api_client):
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.setenv("GRAPHYN_BILLING_WEBHOOK_SECRET", "billing-secret")
    reset_user_store()
    reset_org_store()
    reset_meter_store()
    store = get_user_store()
    yield api_client, store
    reset_user_store()
    reset_org_store()
    reset_meter_store()


def _login(client, username, password="correct-horse-1"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_quotas_and_usage(client_store):
    client, store = client_store
    store.create_user("alice", "correct-horse-1", roles=["admin"])
    h = _login(client, "alice")
    q = client.put(
        f"/api/v1/orgs/{DEFAULT_ORG_ID}/quotas",
        json={"max_projects": 2, "max_seats": 3, "max_runs_per_day": 5},
        headers=h,
    )
    assert q.status_code == 200, q.text
    assert q.json()["max_projects"] == 2
    usage = client.get(f"/api/v1/orgs/{DEFAULT_ORG_ID}/usage", headers=h)
    assert usage.status_code == 200 and "usage" in usage.json() and "quota" in usage.json()


def test_project_quota_enforced(client_store, tmp_workspace):
    client, store = client_store
    store.create_user("alice", "correct-horse-1", roles=["admin"])
    h = _login(client, "alice")
    client.put(f"/api/v1/orgs/{DEFAULT_ORG_ID}/quotas", json={"max_projects": 1}, headers=h)
    r1 = client.post("/api/v1/projects", json={"name": "p1"}, headers=h)
    assert r1.status_code == 200, r1.text
    r2 = client.post("/api/v1/projects", json={"name": "p2"}, headers=h)
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "quota_exceeded"


def test_billing_webhook_hmac(client_store):
    client, store = client_store
    store.create_user("alice", "correct-horse-1", roles=["admin"])
    body = json.dumps(
        {"type": "invoice.paid", "data": {"object": {"metadata": {"org_id": DEFAULT_ORG_ID}}}}
    ).encode()
    sig = "sha256=" + hmac.new(b"billing-secret", body, hashlib.sha256).hexdigest()
    bad = client.post("/api/v1/billing/webhook", content=body, headers={"X-Graphyn-Signature": "sha256=dead"})
    assert bad.status_code == 401
    ok = client.post("/api/v1/billing/webhook", content=body, headers={"X-Graphyn-Signature": sig})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    events = get_meter_store().list_events(DEFAULT_ORG_ID)
    assert any(e["event_type"].startswith("billing.") for e in events)
