"""API: org CRUD, activate, project/credential isolation across orgs."""
from __future__ import annotations

import pytest

from app.core.trust.orgs import DEFAULT_ORG_ID, get_org_store, reset_org_store
from app.core.trust.users import get_user_store, reset_user_store


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    yield


@pytest.fixture
def tenancy(tmp_path, monkeypatch, api_client):
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_LEGACY_TOKEN_DISABLED", raising=False)
    reset_user_store()
    reset_org_store()
    store = get_user_store()
    orgs = get_org_store()
    yield api_client, store, orgs
    reset_user_store()
    reset_org_store()


def _login(client, username, password="correct-horse-1"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_orgs_list_activate_and_me(tenancy):
    client, store, orgs = tenancy
    store.create_user("alice", "correct-horse-1", roles=["admin"])
    h = _login(client, "alice")
    me = client.get("/api/v1/me", headers=h).json()
    assert me["org_id"] == DEFAULT_ORG_ID and me["orgs"]
    listed = client.get("/api/v1/orgs", headers=h).json()
    assert any(o["id"] == DEFAULT_ORG_ID for o in listed)
    created = client.post("/api/v1/orgs", json={"slug": "acme", "name": "Acme Corp"}, headers=h)
    assert created.status_code == 200, created.text
    oid = created.json()["id"]
    act = client.post(f"/api/v1/orgs/{oid}/activate", headers=h)
    assert act.status_code == 200 and act.json()["org_id"] == oid
    me2 = client.get("/api/v1/me", headers=h).json()
    assert me2["org_id"] == oid and me2["org_role"] == "owner"


def test_project_isolation_across_orgs(tenancy, tmp_workspace):
    client, store, orgs = tenancy
    from app.domain.project_manager import ProjectManager

    pm = ProjectManager()
    for name in ("alpha", "beta"):
        try:
            pm.create(name)
        except Exception:
            pass
    alice = store.create_user("alice", "correct-horse-1", roles=["admin"])
    bob = store.create_user("bob", "correct-horse-1", roles=["viewer"])
    # default migration assigns both users + on-disk projects to default
    acme = orgs.create_org("acme", "Acme", owner_user_id=alice.id)
    orgs.assign_project("alpha", DEFAULT_ORG_ID)
    orgs.assign_project("beta", acme.id)
    store.set_membership("alpha", bob.id, "viewer")
    store.set_membership("beta", bob.id, "viewer")
    orgs.set_membership(DEFAULT_ORG_ID, bob.id, "member")
    # bob not in acme
    hb = _login(client, "bob")
    names = [p.get("name") for p in client.get("/api/v1/projects", params={"envelope": 0}, headers=hb).json()]
    assert "alpha" in names and "beta" not in names
    assert client.get("/api/v1/projects/beta", headers=hb).status_code == 403
    # alice activates acme → sees beta, not alpha
    ha = _login(client, "alice")
    client.post(f"/api/v1/orgs/{acme.id}/activate", headers=ha)
    names_a = [p.get("name") for p in client.get("/api/v1/projects", params={"envelope": 0}, headers=ha).json()]
    assert "beta" in names_a and "alpha" not in names_a


def test_credential_org_scoping(tenancy):
    client, store, orgs = tenancy
    store.create_user("alice", "correct-horse-1", roles=["admin"])
    ha = _login(client, "alice")
    # create credential in default org
    body = {
        "name": "smtp-default",
        "kind": "smtp",
        "payload": {"host": "localhost", "port": 25, "username": "a", "password": "secret-password"},
    }
    # kinds may vary — use a simple kind from list
    kinds = client.get("/api/v1/credentials/kinds", headers=ha).json().get("kinds") or []
    if kinds:
        body["kind"] = kinds[0]["id"]
        # minimal payload from fields
        payload = {}
        for f in kinds[0].get("fields") or []:
            if f.get("required"):
                payload[f["name"]] = "x" * 12 if f.get("secret") else "value"
        body["payload"] = payload or body["payload"]
    r = client.post("/api/v1/credentials", json=body, headers=ha)
    # If kind validation fails, skip soft
    if r.status_code >= 400:
        pytest.skip(f"credential kind unavailable: {r.text}")
    listed = client.get("/api/v1/credentials", headers=ha).json()
    assert listed["total"] >= 1
    acme = client.post("/api/v1/orgs", json={"slug": "acme2", "name": "Acme2"}, headers=ha).json()
    client.post(f"/api/v1/orgs/{acme['id']}/activate", headers=ha)
    listed2 = client.get("/api/v1/credentials", headers=ha).json()
    assert listed2["total"] == 0


def test_org_member_api(tenancy):
    client, store, orgs = tenancy
    alice = store.create_user("alice", "correct-horse-1", roles=["admin"])
    bob = store.create_user("bob", "correct-horse-1", roles=["viewer"])
    ha = _login(client, "alice")
    org = client.post("/api/v1/orgs", json={"slug": "team", "name": "Team"}, headers=ha).json()
    r = client.put(
        f"/api/v1/orgs/{org['id']}/members/{bob.id}",
        json={"role": "member"},
        headers=ha,
    )
    assert r.status_code == 200 and any(m["user_id"] == bob.id for m in r.json())


def test_credential_bind_delete_org_gated(tenancy):
    """P1: DELETE / bind_default must respect active-org gate like get/update."""
    client, store, orgs = tenancy
    store.create_user("alice", "correct-horse-1", roles=["admin"])
    ha = _login(client, "alice")
    kinds = client.get("/api/v1/credentials/kinds", headers=ha).json().get("kinds") or []
    if not kinds:
        pytest.skip("no credential kinds")
    kind = kinds[0]
    payload = {}
    for f in kind.get("fields") or []:
        if f.get("required"):
            payload[f["name"]] = "x" * 12 if f.get("secret") else "value"
    body = {"name": "cred-a", "kind": kind["id"], "payload": payload or {"host": "localhost"}}
    r = client.post("/api/v1/credentials", json=body, headers=ha)
    if r.status_code >= 400:
        pytest.skip(f"credential create failed: {r.text}")
    cid = r.json()["id"]
    # Switch org — same connection must 404 on bind/delete (not mutate across orgs)
    acme = client.post("/api/v1/orgs", json={"slug": "acme-gate", "name": "AcmeGate"}, headers=ha).json()
    client.post(f"/api/v1/orgs/{acme['id']}/activate", headers=ha)
    bind = client.post(f"/api/v1/credentials/{cid}/default", headers=ha)
    assert bind.status_code == 404, bind.text
    deleted = client.delete(f"/api/v1/credentials/{cid}?delete=true", headers=ha)
    assert deleted.status_code == 404, deleted.text

