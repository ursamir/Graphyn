"""Wave 6 / F17: agent principals, scoped tokens, MCP RBAC, billing status."""
from __future__ import annotations


import pytest

from app.core.trust.agents import get_agent_store, reset_agent_store
from app.core.trust.identity import identity_from_credentials
from app.core.trust.metering import get_meter_store, reset_meter_store
from app.core.trust.orgs import DEFAULT_ORG_ID, get_org_store, reset_org_store
from app.core.trust.users import get_user_store, reset_user_store
from app.mcp.auth import check_auth, resolve_mcp_actor


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    yield


@pytest.fixture
def client_store(tmp_path, monkeypatch, api_client):
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    (tmp_path / "home").mkdir()
    reset_user_store()
    reset_org_store()
    reset_agent_store()
    reset_meter_store()
    yield api_client, get_user_store()
    reset_user_store()
    reset_org_store()
    reset_agent_store()
    reset_meter_store()


def _login(client, username, password="correct-horse-1"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_agent_crud_mint_and_identity(client_store):
    client, store = client_store
    store.create_user("alice", "correct-horse-1", roles=["admin"])
    h = _login(client, "alice")
    created = client.post(
        "/api/v1/agents",
        json={"slug": "ci-bot", "name": "CI Bot", "roles": ["builder", "viewer"]},
        headers=h,
    )
    assert created.status_code == 200, created.text
    agent = created.json()
    assert agent["kind"] == "agent" and agent["slug"] == "ci-bot"
    assert "builder" in agent["roles"]

    minted = client.post(
        f"/api/v1/agents/{agent['id']}/tokens",
        json={"name": "mcp-1"},
        headers=h,
    )
    assert minted.status_code == 200, minted.text
    token = minted.json()["token"]
    assert token.startswith("gxa_")

    ident = identity_from_credentials(token)
    assert ident["kind"] == "agent"
    assert ident["actor"] == "agent:ci-bot"
    assert ident["actor_verified"] is True
    assert "builder" in ident["roles"]

    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["kind"] == "agent"
    assert body["agent_slug"] == "ci-bot"
    assert "pipelines.write" in body["permissions"] or "read" in body["permissions"]

    # MCP auth allows agent with builder role for read-ish tools
    err = check_auth({"_meta": {"auth_token": token}, "project": None}, tool_name="list_pipelines")
    assert err is None
    actor = resolve_mcp_actor({"_meta": {"auth_token": token}})
    assert actor["actor"] == "agent:ci-bot" and actor.get("kind") == "agent"

    # Forbidden: agent without plugins.admin cannot install_plugin
    err2 = check_auth({"_meta": {"auth_token": token}}, tool_name="install_plugin")
    assert err2 and err2["error_type"] == "forbidden"

    # Revoke
    cid = minted.json()["credential_id"]
    rev = client.delete(f"/api/v1/agents/{agent['id']}/tokens/{cid}", headers=h)
    assert rev.status_code == 200
    assert identity_from_credentials(token).get("token_mapped") is False


def test_billing_status_admin(client_store):
    client, store = client_store
    store.create_user("alice", "correct-horse-1", roles=["admin"])
    h = _login(client, "alice")
    st = client.get("/api/v1/billing/status", headers=h)
    assert st.status_code == 200, st.text
    data = st.json()
    assert "secret_configured" in data
    assert "Not shipped" in data["checkout_ui"]
    assert data["endpoint"].endswith("/billing/webhook")


def test_agent_store_direct(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    reset_user_store()
    reset_agent_store()
    get_user_store()  # ensure db
    ag = get_agent_store().create_agent("ops", "Ops", roles=["operator"], org_id=DEFAULT_ORG_ID)
    token, info = get_agent_store().mint_token(ag.id, name="t1")
    assert info["token"].startswith("gxa_")
    ident = identity_from_credentials(token)
    assert ident["org_id"] == DEFAULT_ORG_ID or ident.get("org_id")


def test_disabled_agent_token_rejected_not_operator(client_store):
    """P0: disable (or delete) agent → gxa_ is inactive; never elevates to operator."""
    import sqlite3

    from app.core.trust.identity import token_accepted
    from app.core.trust.agents import get_agent_store

    client, store = client_store
    store.create_user("alice", "correct-horse-1", roles=["admin"])
    h = _login(client, "alice")
    created = client.post(
        "/api/v1/agents",
        json={"slug": "ci-bot", "name": "CI Bot", "roles": ["builder", "operator"]},
        headers=h,
    )
    assert created.status_code == 200, created.text
    agent = created.json()
    minted = client.post(
        f"/api/v1/agents/{agent['id']}/tokens",
        json={"name": "live"},
        headers=h,
    )
    assert minted.status_code == 200, minted.text
    token = minted.json()["token"]
    assert token.startswith("gxa_")
    assert token_accepted(token) is True
    assert identity_from_credentials(token)["kind"] == "agent"

    # Disable → credential inactive (401), not break-glass operator
    dis = client.patch(
        f"/api/v1/agents/{agent['id']}",
        json={"disabled": True},
        headers=h,
    )
    assert dis.status_code == 200 and dis.json()["disabled"] is True
    assert token_accepted(token) is False
    ident = identity_from_credentials(token)
    assert ident.get("token_mapped") is False
    assert ident.get("kind") != "agent"
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401, me.text
    err = check_auth({"_meta": {"auth_token": token}}, tool_name="list_pipelines")
    assert err and err["error_type"] == "unauthorized"

    # Missing/deleted agent row → same inactive treatment (no operator elevation)
    ag = get_agent_store().create_agent("gone-bot", "Gone", roles=["builder"])
    tok2, _ = get_agent_store().mint_token(ag.id, name="t")
    assert token_accepted(tok2) is True
    db_path = get_agent_store().path
    with sqlite3.connect(str(db_path)) as c:
        c.execute("DELETE FROM agents WHERE id=?", (ag.id,))
        c.commit()
    reset_agent_store()
    assert get_agent_store().get_agent(ag.id) is None
    assert token_accepted(tok2) is False
    assert identity_from_credentials(tok2).get("kind") != "agent"
    me2 = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tok2}"})
    assert me2.status_code == 401
    err2 = check_auth({"_meta": {"auth_token": tok2}}, tool_name="list_pipelines")
    assert err2 and err2["error_type"] == "unauthorized"

