"""Wave 4: KMS/BYOK local+envelope, residency, compliance export."""
from __future__ import annotations

import io
import zipfile

import pytest

from app.core.trust.kms import (
    KmsError,
    LocalEnvelopeKeyProvider,
    kms_status,
    resolve_data_key,
)
from app.core.trust.residency import ResidencyError, check_org_region, residency_status
from app.core.trust.compliance import build_compliance_bundle, retention_policy
from app.core.trust.orgs import DEFAULT_ORG_ID, get_org_store, reset_org_store
from app.core.trust.users import get_user_store, reset_user_store


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    yield


def test_local_kms_credentials_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_KMS_BACKEND", "local")
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_CREDENTIALS_KEY", "test-passphrase-for-creds")
    (tmp_path / "home").mkdir()
    key = resolve_data_key("credentials")
    assert isinstance(key, bytes) and len(key) == 32
    assert kms_status()["cloud_kms_shipped"] is False


def test_envelope_kms_mints_dek(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_KMS_BACKEND", "envelope")
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_KMS_CMK", "customer-cmk-passphrase")
    (tmp_path / "home").mkdir()
    k1 = resolve_data_key("credentials")
    k2 = resolve_data_key("credentials")
    assert k1 == k2 and len(k1) == 32
    blob = resolve_data_key("blob")
    assert len(blob) == 32 and blob != k1


def test_cloud_kms_refuses_stub(monkeypatch):
    monkeypatch.setenv("GRAPHYN_KMS_BACKEND", "aws")
    with pytest.raises(KmsError, match="not shipped"):
        resolve_data_key("credentials")


def test_residency_fail_closed(monkeypatch):
    monkeypatch.setenv("GRAPHYN_RESIDENCY_ENFORCE", "1")
    monkeypatch.setenv("GRAPHYN_RESIDENCY_REGION", "eu-west-1")
    check_org_region("eu-west-1")  # ok
    with pytest.raises(ResidencyError):
        check_org_region("us-east-1")
    monkeypatch.setenv("GRAPHYN_RESIDENCY_ENFORCE", "0")
    check_org_region("us-east-1")  # warn only
    st = residency_status()
    assert st["node_region"] == "eu-west-1"


def test_org_region_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    reset_user_store()
    reset_org_store()
    store = get_user_store()
    u = store.create_user("bob", "correct-horse-1", roles=["admin"])
    org_store = get_org_store()
    org = org_store.create_org(
        "acme", "Acme", owner_user_id=u.id, region="ap-south-1"
    )
    assert org.region == "ap-south-1"
    assert org.public()["region"] == "ap-south-1"
    after = org_store.update_org(org.id, region="eu-west-1")
    assert after.region == "eu-west-1"
    reset_user_store()
    reset_org_store()


def test_compliance_bundle_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("GRAPHYN_AUDIT_RETENTION_DAYS", "30")
    pol = retention_policy()
    assert pol["retention_days"] == 30
    blob = build_compliance_bundle(limit=10)
    assert blob[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "policy/retention.json" in names
        assert "policy/kms_status.json" in names
        assert "audit/events.jsonl" in names


@pytest.fixture
def client_store(tmp_path, monkeypatch, api_client):
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    (tmp_path / "home").mkdir()
    reset_user_store()
    reset_org_store()
    yield api_client, get_user_store()
    reset_user_store()
    reset_org_store()


def _login(client, username, password="correct-horse-1"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_compliance_api(client_store):
    client, store = client_store
    store.create_user("alice", "correct-horse-1", roles=["admin"])
    h = _login(client, "alice")
    st = client.get("/api/v1/compliance/status", headers=h)
    assert st.status_code == 200, st.text
    assert "kms" in st.json() and "residency" in st.json()
    ex = client.get("/api/v1/compliance/export", headers=h)
    assert ex.status_code == 200, ex.text
    assert ex.headers.get("content-type", "").startswith("application/zip")
    assert ex.content[:2] == b"PK"
    # region via API
    p = client.patch(
        f"/api/v1/orgs/{DEFAULT_ORG_ID}",
        json={"region": "us-east-1"},
        headers=h,
    )
    assert p.status_code == 200, p.text
    assert p.json()["region"] == "us-east-1"
