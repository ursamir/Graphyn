# unit_test/f19/test_f19_ship_signing.py
"""F19 / F-14 — ship packages are signed by default and runtime/format is validated.

Before: ``unsigned_allowed`` defaulted to True, every package got the
``dev-unsigned`` placeholder signature, and a package with runtime ``tflite``
could hold ``model.keras``. Now: Ed25519 signature by default (verifiable with
the published public key), runtime ↔ model format checked from file content,
unsigned packages cannot be promoted to prod, tampering is detected.
"""
from __future__ import annotations

import base64
import stat
import zipfile
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_int8.tflite"
PROJ = "f19-ship"


@pytest.fixture(autouse=True)
def _threads(real_threads):
    """TestClient needs real threads (the root conftest stubs Thread.start)."""
    yield


@pytest.fixture
def ship_ws(tmp_workspace: Path):
    from app.api import idempotency as idem
    from app.domain.project_manager import ProjectManager

    idem._MEMORY.clear()
    ProjectManager().create(PROJ)
    art = tmp_workspace / "artifacts" / "f19ship"
    art.mkdir(parents=True)
    (art / "model.tflite").write_bytes(FIXTURE.read_bytes())
    (art / "labels.txt").write_text("a\nb\nc\n")
    k = tmp_workspace / "artifacts" / "f19keras"
    k.mkdir(parents=True)
    with zipfile.ZipFile(k / "model.keras", "w") as zf:  # .keras files are zip archives
        zf.writestr("config.json", "{}")
    fake = tmp_workspace / "artifacts" / "f19fake"
    fake.mkdir(parents=True)
    (fake / "model.tflite").write_bytes(b"definitely not a flatbuffer")
    return tmp_workspace


def _create(api_client, key: str, model_path: str, runtime: str, **extra):
    return api_client.post(
        f"/api/v1/projects/{PROJ}/ship/packages",
        headers={"Idempotency-Key": key, "X-Actor": "builder"},
        json={"model_path": model_path, "target": {"runtime": runtime}, **extra},
    )


TFL = "workspace/artifacts/f19ship/model.tflite"


def test_package_is_ed25519_signed_and_verifiable(api_client, ship_ws):
    from cryptography.hazmat.primitives import serialization

    from app.core.mlops.ship_signing import signed_payload

    r = _create(api_client, "f19-s1", TFL, "tflite")
    assert r.status_code == 201, r.text
    man = r.json()["manifest"]
    sig = man["signatures"][0]
    assert sig["alg"] == "ed25519" and sig["key_id"].startswith("ed25519:") and sig["value"]
    assert man["unsigned_allowed"] is False and man["model_ref"]["format"] == "tflite"
    pid = r.json()["package_id"]

    v = api_client.get(f"/api/v1/projects/{PROJ}/ship/packages/{pid}/verify").json()
    assert v == {"signed": True, "valid": True, "checksum_ok": True, "key_id": sig["key_id"], "reason": ""}

    # Independent verification with only the published public key.
    key = api_client.get(f"/api/v1/projects/{PROJ}/ship/signing-key").json()
    assert key["key_id"] == sig["key_id"]
    pub = serialization.load_pem_public_key(key["public_key_pem"].encode())
    pub.verify(base64.b64decode(sig["value"]), signed_payload(man))

    dl = api_client.get(f"/api/v1/projects/{PROJ}/ship/packages/{pid}/download")
    assert dl.status_code == 200 and f"keyid={sig['key_id']}" in dl.headers["X-Graphyn-Signature"]
    assert zipfile.ZipFile(__import__("io").BytesIO(dl.content)).read("model/model.tflite") == FIXTURE.read_bytes()

    # Key file is private.
    from app.core.mlops.ship_signing import signing_key_path

    assert stat.S_IMODE(signing_key_path().stat().st_mode) == 0o600

    ok = api_client.post(
        f"/api/v1/projects/{PROJ}/ship/packages/{pid}/promote",
        headers={"Idempotency-Key": "f19-s1-prod", "X-Actor": "builder"},
        json={"to_env": "prod", "approve": True},
    )
    assert ok.status_code == 200, ok.text


def test_tampered_archive_or_manifest_is_detected(api_client, ship_ws):
    import json

    from app.domain.project_manager import ProjectManager

    pid = _create(api_client, "f19-s2", TFL, "tflite").json()["package_id"]
    pkg = ProjectManager()._require_project(PROJ) / "ship" / "packages" / pid
    # manifest tamper: claim a different runtime
    mpath = pkg / "manifest.json"
    man = json.loads(mpath.read_text())
    man["runtime"] = "onnx"
    mpath.write_text(json.dumps(man))
    v = api_client.get(f"/api/v1/projects/{PROJ}/ship/packages/{pid}/verify").json()
    assert v["valid"] is False and "does not match" in v["reason"]
    # archive tamper
    man["runtime"] = "tflite"
    mpath.write_text(json.dumps(man))
    assert api_client.get(f"/api/v1/projects/{PROJ}/ship/packages/{pid}/verify").json()["valid"] is True
    (pkg / "package.zip").write_bytes((pkg / "package.zip").read_bytes() + b"x")
    v = api_client.get(f"/api/v1/projects/{PROJ}/ship/packages/{pid}/verify").json()
    assert v["valid"] is False and v["checksum_ok"] is False
    r = api_client.post(
        f"/api/v1/projects/{PROJ}/ship/packages/{pid}/promote",
        headers={"Idempotency-Key": "f19-s2-prod", "X-Actor": "builder"},
        json={"to_env": "prod", "approve": True},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "signature_required"


@pytest.mark.parametrize(
    "path,runtime,needle",
    [
        ("workspace/artifacts/f19keras/model.keras", "tflite", "cannot run a 'keras' model"),
        ("workspace/artifacts/f19fake/model.tflite", "tflite", "not a recognisable model"),
        (TFL, "onnx", "cannot run a 'tflite' model"),
    ],
)
def test_runtime_format_mismatch_rejected(api_client, ship_ws, path, runtime, needle):
    r = _create(api_client, f"f19-mm-{runtime}-{Path(path).parent.name}", path, runtime)
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "runtime_format_mismatch" and needle in body["error"]["message"]


def test_runtime_auto_and_unknown(api_client, ship_ws):
    r = _create(api_client, "f19-auto", TFL, "auto")
    assert r.status_code == 201 and r.json()["manifest"]["runtime"] == "tflite"
    r = _create(api_client, "f19-auto-k", "workspace/artifacts/f19keras/model.keras", "auto")
    assert r.status_code == 201 and r.json()["manifest"]["runtime"] == "keras"
    r = _create(api_client, "f19-bogus", TFL, "coreml")
    assert r.status_code == 422 and "unknown target.runtime" in r.json()["error"]["message"]


def test_unsigned_only_on_opt_in_and_never_prod(api_client, ship_ws, monkeypatch):
    import app.core.mlops.ship_signing as signing

    def boom(*a, **k):
        raise RuntimeError("no key")

    with monkeypatch.context() as m:
        m.setattr(signing, "sign_manifest", boom)
        r = _create(api_client, "f19-uns-0", TFL, "tflite")
        assert r.status_code == 422 and "signing failed" in r.json()["error"]["message"], r.text
        r = _create(api_client, "f19-uns-1", TFL, "tflite", unsigned_allowed=True)
        assert r.status_code == 201, r.text
        assert r.json()["warnings"][0]["code"] == "unsigned"
        assert r.json()["manifest"]["signatures"][0]["key_id"] == "dev-unsigned"
        pid = r.json()["package_id"]
    p = api_client.post(
        f"/api/v1/projects/{PROJ}/ship/packages/{pid}/promote",
        headers={"Idempotency-Key": "f19-uns-prod", "X-Actor": "builder"},
        json={"to_env": "prod", "approve": True},
    )
    assert p.status_code == 422 and p.json()["error"]["code"] == "signature_required", p.text
    s = api_client.post(
        f"/api/v1/projects/{PROJ}/ship/packages/{pid}/promote",
        headers={"Idempotency-Key": "f19-uns-stg", "X-Actor": "builder"},
        json={"to_env": "staging"},
    )
    assert s.status_code == 200, s.text


def test_openapi_has_schemas_for_new_routes(api_client):
    spec = api_client.get("/api/v1/openapi.json")
    if spec.status_code != 200:
        spec = api_client.get("/openapi.json")
    paths = spec.json()["paths"]
    verify = next(v for k, v in paths.items() if k.endswith("/ship/packages/{package_id}/verify"))
    schema = verify["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema.get("$ref", "").endswith("ShipSignatureCheck")
