"""F19 (F-08 / F-20): separation of duties on prod promotion + real principals."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.mlops.model_registry import approve_prod, get_model, register_model, request_prod
from app.core.mlops.promotion_policy import (
    SeparationOfDutiesError,
    get_promotion_policy,
    set_promotion_policy,
)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    run_id = "run-sod1"
    art = tmp_path / "artifacts" / "demo" / "runs" / run_id
    art.mkdir(parents=True)
    (art / "model.bin").write_bytes(b"x")
    rdir = tmp_path / "runs" / run_id
    rdir.mkdir(parents=True)
    (rdir / "meta.json").write_text(json.dumps({"run_id": run_id, "status": "succeeded"}))
    register_model("kws", run_id=run_id, slug="demo", stage="staging", actor="alice", base_dir=tmp_path)
    return tmp_path


def _audit(ws: Path) -> list[dict]:
    p = ws / "audit" / "events.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []


def test_requester_cannot_approve_own_prod_request(ws):
    request_prod("kws", actor="alice", base_dir=ws)
    with pytest.raises(SeparationOfDutiesError, match="cannot also approve"):
        approve_prod("kws", actor="alice", base_dir=ws)
    with pytest.raises(SeparationOfDutiesError):
        approve_prod("kws", actor="ALICE", base_dir=ws)  # case-insensitive principal match
    assert "prod" not in (get_model("kws", base_dir=ws).get("stages") or {})
    denied = [e for e in _audit(ws) if e.get("action") == "model.approve_prod" and e.get("result") == "denied"]
    assert denied and denied[0]["actor"] == "alice"
    done = approve_prod("kws", actor="bob", base_dir=ws)
    assert "prod" in done["stages"]
    ok = [e for e in _audit(ws) if e.get("action") == "model.approve_prod" and e.get("result") == "success"]
    assert ok[-1]["meta"]["separation_of_duties"] == "enforced"


def test_anonymous_approver_or_requester_refused(ws):
    request_prod("kws", actor="unidentified", base_dir=ws)
    with pytest.raises(SeparationOfDutiesError, match="no identified requester"):
        approve_prod("kws", actor="bob", base_dir=ws)
    with pytest.raises(SeparationOfDutiesError, match="identified approver"):
        approve_prod("kws", actor="unidentified", base_dir=ws)


def test_sod_waiver_only_by_explicit_audited_policy(ws):
    assert get_promotion_policy(ws)["require_separation_of_duties"] is True
    with pytest.raises(ValueError, match="reason"):
        set_promotion_policy(require_separation_of_duties=False, actor="root-admin", reason="", base_dir=ws)
    with pytest.raises(SeparationOfDutiesError):
        set_promotion_policy(require_separation_of_duties=False, actor="unidentified", reason="x", base_dir=ws)
    pol = set_promotion_policy(require_separation_of_duties=False, actor="root-admin", reason="single-operator lab", base_dir=ws)
    assert pol["require_separation_of_duties"] is False and pol["updated_by"] == "root-admin"
    request_prod("kws", actor="alice", base_dir=ws)
    approve_prod("kws", actor="alice", base_dir=ws)  # allowed: waived by policy
    evs = _audit(ws)
    change = [e for e in evs if e.get("action") == "model.promotion_policy.update"][-1]
    assert change["actor"] == "root-admin"
    appr = [e for e in evs if e.get("action") == "model.approve_prod" and e.get("result") == "success"][-1]
    assert appr["meta"]["sod_waived"] is True and appr["meta"]["sod_waived_by"] == "root-admin"


def test_api_sod_with_named_tokens_and_shared_token(real_threads, api_client, ws, monkeypatch):
    monkeypatch.setenv("GRAPHYN_API_TOKENS", "alice:tok-alice,bob:tok-bob")
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "shared")
    A = {"Authorization": "Bearer tok-alice"}
    B = {"Authorization": "Bearer tok-bob"}
    S = {"Authorization": "Bearer shared", "X-Actor": "bob"}  # X-Actor is only a claim
    r = api_client.post("/api/v1/models/kws/request-prod", headers=A, json={})
    assert r.status_code == 200, r.text
    r = api_client.post("/api/v1/models/kws/approve-prod", headers=A)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "separation_of_duties"
    r = api_client.post("/api/v1/models/kws/approve-prod", headers=B)
    assert r.status_code == 200, r.text
    # shared token: one principal ("operator") on both sides → refused, even with a forged X-Actor
    register_model("kws2", run_id="run-sod1", slug="demo", stage="staging", actor="alice", base_dir=ws)
    assert api_client.post("/api/v1/models/kws2/request-prod", headers=S, json={}).status_code == 200
    r = api_client.post("/api/v1/models/kws2/approve-prod", headers=S)
    assert r.status_code == 403, r.text
    pol = api_client.get("/api/v1/models/promotion-policy", headers=A).json()
    assert pol["require_separation_of_duties"] is True and pol["source"] == "default"
    r = api_client.put("/api/v1/models/promotion-policy", headers=A,
                       json={"require_separation_of_duties": False})
    assert r.status_code == 422  # reason required


def test_promotion_policy_openapi_schema_not_empty(real_threads, api_client):
    spec = api_client.get("/openapi.json").json()
    op = spec["paths"]["/api/v1/models/promotion-policy"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema.get("$ref", "").endswith("PromotionPolicyOut")


def test_shared_token_actor_is_real_principal(monkeypatch):
    from app.core.trust.identity import identity_from_credentials

    monkeypatch.setenv("GRAPHYN_API_TOKEN", "shared-secret")
    ident = identity_from_credentials("shared-secret", "mallory")
    assert ident["actor"] == "operator" and ident["actor_verified"] is True
    assert ident["claimed_actor"] == "mallory" and ident["credential_id"].startswith("legacy:")
    assert "shared-secret" not in json.dumps(ident)
    monkeypatch.setenv("GRAPHYN_API_TOKEN_ACTOR", "unidentified")  # generic names are refused
    assert identity_from_credentials("shared-secret")["actor"] == "operator"
