"""Users + RBAC: login, sessions, personal tokens, role permissions, project
membership isolation, gate approver roles, legacy break-glass token, MCP."""
from __future__ import annotations

import json

import pytest

from app.core.trust.users import UserStoreError, get_user_store, reset_user_store


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    yield


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_LEGACY_TOKEN_DISABLED", raising=False)
    reset_user_store()
    yield get_user_store()
    reset_user_store()


def _login(client, username, password="correct-horse-1"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ── store ──────────────────────────────────────────────────────────────────────


def test_store_users_tokens_and_last_admin(store):
    a = store.create_user("alice", "correct-horse-1", roles=["admin"])
    with pytest.raises(UserStoreError):
        store.create_user("alice", "correct-horse-1")
    with pytest.raises(UserStoreError):
        store.create_user("bob", "short")
    with pytest.raises(UserStoreError):
        store.create_user("bob", "correct-horse-1", roles=["root"])
    assert store.authenticate("alice", "wrong-password") is None
    assert store.authenticate("ALICE", "correct-horse-1").id == a.id
    token, cred = store.issue_credential("api", user_id=a.id, name="ci", ttl_s=60)
    assert token.startswith("gxu_") and cred.id in token
    got = store.resolve_token(token)
    assert got and got[0].id == cred.id and got[1].username == "alice"
    assert store.resolve_token(token[:-2] + "xx") is None
    store.revoke_credential(cred.id)
    assert store.resolve_token(token) is None
    with pytest.raises(UserStoreError) as exc:
        store.update_user(a.id, roles=["viewer"])
    assert exc.value.status_code == 409  # last admin
    # Disabling ends sessions / API tokens.
    b = store.create_user("bob", "correct-horse-1", roles=["builder"])
    tok_b, _ = store.issue_credential("session", user_id=b.id, ttl_s=60)
    store.update_user(b.id, disabled=True)
    assert store.resolve_token(tok_b) is None
    raw = store.path.read_bytes()
    assert b"correct-horse-1" not in raw and token.split("_")[-1].encode() not in raw


# ── API ────────────────────────────────────────────────────────────────────────


def test_login_me_logout_and_lockout(api_client, store):
    store.create_user("alice", "correct-horse-1", roles=["builder"], approver_roles=["qa-lead"])
    h = _login(api_client, "alice")
    me = api_client.get("/api/v1/me", headers=h).json()
    assert me["actor"] == "alice" and me["actor_verified"] and me["kind"] == "user"
    assert me["roles"] == ["builder"] and "runs.execute" in me["permissions"] and me["auth_method"] == "session"
    assert api_client.post("/api/v1/auth/logout", headers=h).status_code == 200
    assert api_client.get("/api/v1/me", headers=h).status_code == 401
    for _ in range(5):
        assert api_client.post("/api/v1/auth/login", json={"username": "alice", "password": "nope-nope-1"}).status_code == 401
    assert api_client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse-1"}).status_code == 429
    status = api_client.get("/api/v1/system/auth-status").json()
    assert status["users_configured"] is True and status["token_configured"] is True


def test_role_permissions_enforced(api_client, store):
    store.create_user("admin1", "correct-horse-1", roles=["admin"])
    store.create_user("vic", "correct-horse-1", roles=["viewer"])
    store.create_user("aud", "correct-horse-1", roles=["auditor"])
    hv = _login(api_client, "vic")
    ha = _login(api_client, "aud")
    hadm = _login(api_client, "admin1")
    # viewer: reads ok, writes / audit / user admin denied
    assert api_client.get("/api/v1/nodes", headers=hv).status_code == 200
    assert api_client.post("/api/v1/projects", json={"name": "p1"}, headers=hv).status_code == 403
    assert api_client.get("/api/v1/audit", headers=hv).status_code == 403
    assert api_client.get("/api/v1/users", headers=hv).status_code == 403
    assert api_client.post("/api/v1/plugins/install", json={"source": "x"}, headers=hv).status_code == 403
    # auditor reads the audit log; admin manages users
    assert api_client.get("/api/v1/audit", headers=ha).status_code == 200
    r = api_client.post(
        "/api/v1/users",
        json={"username": "bob", "password": "correct-horse-1", "roles": ["builder"]},
        headers=hadm,
    )
    assert r.status_code == 200, r.text
    assert r.json()["roles"] == ["builder"]
    events = api_client.get("/api/v1/audit", headers=ha, params={"limit": 50}).json()
    rows = events.get("events") if isinstance(events, dict) else events
    created = [e for e in rows if e.get("action") == "user.create"]
    assert created and created[0]["actor"] == "admin1" and created[0]["principal"]["kind"] == "user"
    assert created[0]["principal"]["credential_id"]


def test_project_membership_isolation(api_client, store, tmp_workspace):
    from app.domain.project_manager import ProjectManager

    pm = ProjectManager()
    for name in ("alpha", "beta"):
        try:
            pm.create(name)
        except Exception:
            pass
    store.create_user("admin1", "correct-horse-1", roles=["admin"])
    b = store.create_user("bob", "correct-horse-1", roles=["viewer"])
    store.set_membership("alpha", b.id, "builder")
    hb = _login(api_client, "bob")
    names = [p.get("name") for p in api_client.get("/api/v1/projects", params={"envelope": 0}, headers=hb).json()]
    assert "alpha" in names and "beta" not in names
    assert api_client.get("/api/v1/projects/beta", headers=hb).status_code == 403
    assert api_client.get("/api/v1/projects/alpha", headers=hb).status_code == 200
    # project builder role grants write inside alpha only
    assert api_client.put("/api/v1/projects/alpha/spec", json={"content": "x"}, headers=hb).status_code != 403
    assert api_client.put("/api/v1/projects/beta/spec", json={"content": "x"}, headers=hb).status_code == 403
    # members API: viewer cannot add members; admin can
    assert api_client.put(f"/api/v1/projects/alpha/members/{b.id}", json={"role": "owner"}, headers=hb).status_code == 403
    hadm = _login(api_client, "admin1")
    r = api_client.put(f"/api/v1/projects/beta/members/{b.id}", json={"role": "viewer"}, headers=hadm)
    assert r.status_code == 200 and r.json()[0]["username"] == "bob"


def test_run_body_project_checked(api_client, store):
    b = store.create_user("bob", "correct-horse-1", roles=["viewer"])
    store.set_membership("alpha", b.id, "builder")
    hb = _login(api_client, "bob")
    graph = {"schema_version": "1.2", "metadata": {"name": "g", "project": "beta", "seed": 1}, "nodes": [{"id": "a", "node_type": "set_map", "config": {}}], "edges": []}
    r = api_client.post("/api/v1/pipelines/run-async", json={"graph": graph, "project": "beta"}, headers=hb)
    assert r.status_code == 403 and "beta" in r.text


def test_personal_tokens(api_client, store):
    store.create_user("bob", "correct-horse-1", roles=["builder"])
    hb = _login(api_client, "bob")
    r = api_client.post("/api/v1/me/tokens", json={"name": "ci", "ttl_days": 7}, headers=hb)
    assert r.status_code == 200
    tok = r.json()["token"]
    ht = {"Authorization": f"Bearer {tok}"}
    me = api_client.get("/api/v1/me", headers=ht).json()
    assert me["actor"] == "bob" and me["auth_method"] == "api_token"
    listed = api_client.get("/api/v1/me/tokens", headers=hb).json()
    assert listed and "token" not in listed[0] and listed[0]["name"] == "ci"
    assert api_client.delete(f"/api/v1/me/tokens/{listed[0]['id']}", headers=hb).status_code == 200
    assert api_client.get("/api/v1/me", headers=ht).status_code == 401


def test_legacy_token_break_glass(api_client, store, monkeypatch):
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "legacy-shared-token")
    h = {"Authorization": "Bearer legacy-shared-token"}
    assert api_client.get("/api/v1/me", headers=h).json()["roles"] == ["admin"]
    r = api_client.post("/api/v1/auth/bootstrap", json={"username": "root1", "password": "correct-horse-1"}, headers=h)
    assert r.status_code == 200
    assert api_client.post("/api/v1/auth/bootstrap", json={"username": "x2", "password": "correct-horse-1"}, headers=h).status_code == 409
    assert api_client.get("/api/v1/users", headers=h).status_code == 200
    monkeypatch.setenv("GRAPHYN_LEGACY_TOKEN_DISABLED", "1")
    assert api_client.get("/api/v1/users", headers=h).status_code == 401


def test_gate_role_must_be_held(api_client, store, tmp_workspace, monkeypatch):
    import app.api.routers.gates as gates_router

    store.create_user("ann", "correct-horse-1", roles=["approver"], approver_roles=["qa-lead"])
    store.create_user("vic", "correct-horse-1", roles=["viewer"])
    seen = {}

    def fake_decide(run_path, node_id, **kw):
        seen.update(kw)
        return {"gate_id": "g", "decision": {"role": kw["role"], "role_verified": kw["role_verified"]}}

    monkeypatch.setattr("app.core.runs.gates.decide_gate", fake_decide)
    monkeypatch.setattr("app.core.runs.gates.gate_approver_roles", lambda *_a: ["qa-lead"])
    monkeypatch.setattr(gates_router, "_run_dir", lambda rid: tmp_workspace / "runs" / rid)
    ha = _login(api_client, "ann")
    hv = _login(api_client, "vic")
    url = "/api/v1/runs/r1/gates/n1/decision"
    assert api_client.post(url, json={"decision": "approve"}, headers=hv).status_code == 403
    assert api_client.post(url, json={"decision": "approve", "role": "ml-lead"}, headers=ha).status_code == 403
    r = api_client.post(url, json={"decision": "approve"}, headers=ha)
    assert r.status_code == 200, r.text
    assert seen["role"] == "qa-lead" and seen["role_verified"] is True and seen["user_id"]


def test_mcp_tool_permissions(store, monkeypatch):
    from app.mcp.auth import check_auth, mcp_tool_permission

    assert mcp_tool_permission("list_runs") == "read"
    assert mcp_tool_permission("execute_pipeline") == "runs.execute"
    assert mcp_tool_permission("save_pipeline") == "pipelines.write"
    v = store.create_user("vic", "correct-horse-1", roles=["viewer"])
    tok, _ = store.issue_credential("api", user_id=v.id, ttl_s=60)
    args = {"_meta": {"auth_token": tok}}
    assert check_auth(args, "list_runs") is None
    assert check_auth(args, "execute_pipeline")["error_type"] == "forbidden"
    assert check_auth({**args, "project": "other"}, "list_runs")["error_type"] == "forbidden"


def test_route_policy_covers_every_mutation():
    """Every non-GET route resolves to an explicit permission (no fail-closed 'admin' surprises)."""
    from app.api.main import app
    from app.core.trust.rbac import required_permission

    unmapped = []
    for r in app.routes:
        for m in getattr(r, "methods", None) or []:
            if m in ("GET", "HEAD", "OPTIONS"):
                continue
            path = getattr(r, "path", "")
            if not path.startswith("/api/v1/"):
                continue
            concrete = path.replace("{", "").replace("}", "").replace(":path", "")
            if required_permission(m, concrete) == "admin":
                unmapped.append(f"{m} {path}")
    assert not unmapped, unmapped


def test_audit_chain_filters_and_export(api_client, store, tmp_path, monkeypatch):
    from app.core.trust.audit import audit_events_path, list_audit, record_audit, verify_audit_chain

    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws"))
    store.create_user("aud", "correct-horse-1", roles=["auditor"])
    store.create_user("bob", "correct-horse-1", roles=["builder"])
    hb = _login(api_client, "bob")
    ha = _login(api_client, "aud")
    api_client.post("/api/v1/auth/logout", headers=hb)
    record_audit(actor="system", action="schedule.tick", resource_type="schedule", resource_id="s1")
    assert verify_audit_chain()["ok"] and verify_audit_chain()["checked"] >= 4
    bob = store.get_user_by_username("bob")
    mine = list_audit(user_id=bob.id)
    assert mine and all(e["principal"]["user_id"] == bob.id for e in mine)
    assert [e["action"] for e in list_audit(actor="BOB")] == ["auth.logout", "auth.login"]
    r = api_client.get("/api/v1/audit/export", params={"format": "csv", "actor": "bob"}, headers=ha)
    assert r.status_code == 200 and r.headers["X-Graphyn-Audit-Chain"] == "ok"
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("timestamp,actor") and len(lines) == 3 and bob.id in lines[1]
    assert api_client.get("/api/v1/audit/export", headers=hb).status_code == 401  # logged out
    assert list_audit(action="audit.export")[0]["actor"] == "aud"
    # Tamper: edit one byte of an old line → chain breaks.
    path = audit_events_path()
    rows = path.read_text().splitlines()
    rows[1] = rows[1].replace('"auth.login"', '"auth.logix"', 1)
    path.write_text("\n".join(rows) + "\n")
    v = api_client.get("/api/v1/audit/verify", headers=ha).json()
    assert v["ok"] is False and v["first_break"]["line"] == 2
