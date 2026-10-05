"""Inbound webhook trigger (POST /hooks/{ws}/{pipeline}) + hook management API."""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest

from app.core.nodes import registry as global_registry

PLUGIN_NODES = Path(__file__).resolve().parents[2] / "PluginPackage/Common/webhook_trigger/nodes.py"


def _load_webhook_class():
    spec = importlib.util.spec_from_file_location("graphyn_test_webhook_trigger_nodes", PLUGIN_NODES)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.WebhookTriggerNode


@pytest.fixture
def hook_env(tmp_path, monkeypatch):
    """Workspace with project 'acme' and pipeline 'onpush' (webhook_trigger → sink)."""
    from app.core.config import datasets_output_dir
    from app.core.pipelines import hooks as core
    from app.core.pipelines.project_pipelines import put_pipeline

    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    cls = _load_webhook_class()
    already = "webhook_trigger" in global_registry
    if not already:
        global_registry.register("webhook_trigger", cls, cls.metadata)
    core._reset_replay_cache()
    core._reset_rate_limits()
    spawned: list = []
    monkeypatch.setattr(core, "_spawn", lambda fn, name: spawned.append(fn))
    project_dir = datasets_output_dir() / "acme"
    project_dir.mkdir(parents=True)
    graph = {
        "schema_version": "1.3",
        "metadata": {"name": "onpush", "seed": 0},
        "nodes": [{"id": "hook", "node_type": "webhook_trigger", "config": {}}],
        "edges": [],
    }
    put_pipeline(project_dir, "onpush", graph, project_name="acme")
    yield {"ws": ws, "project_dir": project_dir}
    if not already:
        global_registry.unregister("webhook_trigger")


def _enable(client, *, rotate=True, **body):
    payload = {"enabled": True, "env": "draft", **body}
    r = client.put("/api/v1/projects/acme/pipelines/onpush/hook", json=payload)
    assert r.status_code == 200, r.text
    if rotate:
        r = client.post("/api/v1/projects/acme/pipelines/onpush/hook/rotate")
        assert r.status_code == 200, r.text
        return r.json()
    return r.json()


def _signed_headers(secret: str, body: bytes, ts: int | None = None) -> dict:
    from app.core.pipelines.hooks import sign_payload

    ts = int(ts if ts is not None else time.time())
    return {
        "Content-Type": "application/json",
        "X-Graphyn-Timestamp": str(ts),
        "X-Graphyn-Signature": sign_payload(secret, ts, body),
    }


def _meta(ws: Path, run_id: str) -> dict:
    return json.loads((ws / "runs" / run_id / "meta.json").read_text())


def _audit(ws: Path) -> list[dict]:
    path = ws / "audit" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_hook_crud_and_rotate_returns_secret_once(api_client, hook_env):
    r = api_client.get("/api/v1/projects/acme/pipelines/onpush/hook")
    assert r.status_code == 200
    assert r.json()["exists"] is False
    rotated = _enable(api_client)
    assert rotated["secret"].startswith("whsec_")
    assert rotated["secret_shown_once"] is True
    assert rotated["url_path"] == "/api/v1/hooks/acme/onpush"
    got = api_client.get("/api/v1/projects/acme/pipelines/onpush/hook").json()
    assert got["enabled"] is True and got["has_secret"] is True
    assert "secret" not in got
    assert got["secret_connection_id"] == rotated["secret_connection_id"]
    # Second rotation keeps the same connection, new secret.
    again = api_client.post("/api/v1/projects/acme/pipelines/onpush/hook/rotate").json()
    assert again["secret"] != rotated["secret"]
    assert again["secret_connection_id"] == rotated["secret_connection_id"]
    actions = [e.get("action") for e in _audit(hook_env["ws"])]
    assert "hook.create" in actions and "hook.rotate" in actions
    d = api_client.delete("/api/v1/projects/acme/pipelines/onpush/hook")
    assert d.status_code == 200
    assert api_client.get("/api/v1/projects/acme/pipelines/onpush/hook").json()["exists"] is False


def test_hook_unknown_pipeline_404(api_client, hook_env):
    r = api_client.put("/api/v1/projects/acme/pipelines/nope/hook", json={"enabled": True})
    assert r.status_code == 404


def test_signed_webhook_starts_run_with_payload(api_client, hook_env):
    secret = _enable(api_client)["secret"]
    body = json.dumps({"event": "push", "ref": "main"}).encode()
    headers = _signed_headers(secret, body)
    headers["X-GitHub-Event"] = "push"
    headers["Cookie"] = "nope=1"
    r = api_client.post("/api/v1/hooks/acme/onpush?ref=main", content=body, headers=headers)
    assert r.status_code == 202, r.text
    ack = r.json()
    assert ack["status"] == "pending" and ack["env"] == "draft"
    meta = _meta(hook_env["ws"], ack["run_id"])
    assert meta["trigger"] == "webhook"
    assert meta["actor"].startswith("webhook:")
    assert meta["actor_verified"] is True
    assert meta["pipeline_name"] == "onpush"
    assert meta["input_keys"] == ["hook.body", "hook.headers", "hook.query"]
    assert len(meta["inputs_sha256"]) == 64
    wh = meta["webhook"]
    assert wh["auth"] == "hmac"
    assert wh["payload_bytes"] == len(body)
    import hashlib

    assert wh["payload_sha256"] == hashlib.sha256(body).hexdigest()
    events = _audit(hook_env["ws"])
    received = [e for e in events if e.get("action") == "webhook.received"]
    assert received and received[-1]["meta"]["run_id"] == ack["run_id"]
    assert any(e.get("action") == "run.start" and e.get("resource_id") == ack["run_id"] for e in events)


def test_header_filter_drops_credentials():
    from app.core.pipelines.hooks import filter_headers

    out = filter_headers({"authorization": "x", "cookie": "y", "x-graphyn-signature": "z",
                          "content-type": "application/json", "x-custom": "1"}, ["x-custom"])
    assert out == {"content-type": "application/json", "x-custom": "1"}


def test_bad_signature_and_stale_timestamp_rejected(api_client, hook_env):
    secret = _enable(api_client)["secret"]
    body = b'{"a":1}'
    bad = _signed_headers("wrong-secret", body)
    assert api_client.post("/api/v1/hooks/acme/onpush", content=body, headers=bad).status_code == 401
    stale = _signed_headers(secret, body, ts=int(time.time()) - 3600)
    r = api_client.post("/api/v1/hooks/acme/onpush", content=body, headers=stale)
    assert r.status_code == 401
    assert any(e.get("action") == "webhook.rejected" for e in _audit(hook_env["ws"]))


def test_replayed_signature_rejected(api_client, hook_env):
    secret = _enable(api_client)["secret"]
    body = b'{"a":1}'
    headers = _signed_headers(secret, body)
    assert api_client.post("/api/v1/hooks/acme/onpush", content=body, headers=headers).status_code == 202
    assert api_client.post("/api/v1/hooks/acme/onpush", content=body, headers=headers).status_code == 409


def test_unauthenticated_and_disabled(api_client, hook_env):
    _enable(api_client)
    assert api_client.post("/api/v1/hooks/acme/onpush", content=b"{}").status_code == 401
    api_client.put("/api/v1/projects/acme/pipelines/onpush/hook", json={"enabled": False})
    assert api_client.post("/api/v1/hooks/acme/onpush", content=b"{}").status_code == 404


def test_bearer_token_alternative(api_client, hook_env, monkeypatch):
    _enable(api_client)
    monkeypatch.setenv("GRAPHYN_API_TOKENS", "ci-bot:tok-ci")
    r = api_client.post("/api/v1/hooks/acme/onpush", content=b'{"x":1}',
                        headers={"Authorization": "Bearer tok-ci", "Content-Type": "application/json"})
    assert r.status_code == 202, r.text
    meta = _meta(hook_env["ws"], r.json()["run_id"])
    assert meta["webhook"]["auth"] == "bearer"
    assert meta["actor_verified"] is True
    bad = api_client.post("/api/v1/hooks/acme/onpush", content=b"{}",
                          headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


def test_idempotency_key_returns_original_run(api_client, hook_env):
    secret = _enable(api_client)["secret"]
    body = b'{"n":1}'
    h1 = {**_signed_headers(secret, body, ts=int(time.time())), "Idempotency-Key": "evt-1"}
    first = api_client.post("/api/v1/hooks/acme/onpush", content=body, headers=h1)
    assert first.status_code == 202
    h2 = {**_signed_headers(secret, body, ts=int(time.time()) - 1), "Idempotency-Key": "evt-1"}
    second = api_client.post("/api/v1/hooks/acme/onpush", content=body, headers=h2)
    assert second.status_code == 200
    assert second.json()["run_id"] == first.json()["run_id"]
    assert second.json()["idempotent_replay"] is True


def test_identical_signed_retry_with_key_returns_original_run(api_client, hook_env):
    """A sender's retry is byte-identical (same signature + key) → original run, not 409."""
    secret = _enable(api_client)["secret"]
    body = b'{"n":2}'
    h = {**_signed_headers(secret, body, ts=int(time.time())), "Idempotency-Key": "evt-2"}
    first = api_client.post("/api/v1/hooks/acme/onpush", content=body, headers=h)
    assert first.status_code == 202
    again = api_client.post("/api/v1/hooks/acme/onpush", content=body, headers=h)
    assert again.status_code == 200
    assert again.json()["run_id"] == first.json()["run_id"]
    assert again.json()["idempotent_replay"] is True


def test_identical_signed_replay_without_key_is_rejected(api_client, hook_env):
    secret = _enable(api_client)["secret"]
    body = b'{"n":3}'
    h = _signed_headers(secret, body, ts=int(time.time()))
    assert api_client.post("/api/v1/hooks/acme/onpush", content=body, headers=h).status_code == 202
    replay = api_client.post("/api/v1/hooks/acme/onpush", content=body, headers=h)
    assert replay.status_code == 409


def test_body_cap_and_rate_limit(api_client, hook_env, monkeypatch):
    secret = _enable(api_client)["secret"]
    monkeypatch.setenv("GRAPHYN_WEBHOOK_MAX_BYTES", "16")
    big = b'{"x":"' + b"a" * 64 + b'"}'
    r = api_client.post("/api/v1/hooks/acme/onpush", content=big, headers=_signed_headers(secret, big))
    assert r.status_code == 413
    monkeypatch.delenv("GRAPHYN_WEBHOOK_MAX_BYTES")
    monkeypatch.setenv("GRAPHYN_WEBHOOK_RATE_BURST", "2")
    monkeypatch.setenv("GRAPHYN_WEBHOOK_RATE_PER_MIN", "1")
    codes = []
    for i in range(3):
        b = json.dumps({"i": i}).encode()
        codes.append(api_client.post("/api/v1/hooks/acme/onpush", content=b,
                                     headers=_signed_headers(secret, b)).status_code)
    assert codes == [202, 202, 429]


def test_env_query_must_be_allowed(api_client, hook_env):
    secret = _enable(api_client)["secret"]
    body = b"{}"
    r = api_client.post("/api/v1/hooks/acme/onpush?env=prod", content=body,
                        headers=_signed_headers(secret, body))
    assert r.status_code == 403


def test_pipeline_without_webhook_trigger_is_refused(api_client, hook_env):
    from app.core.pipelines.project_pipelines import put_pipeline

    put_pipeline(hook_env["project_dir"], "plain", {
        "schema_version": "1.3",
        "metadata": {"name": "plain", "seed": 0},
        "nodes": [{"id": "hook", "node_type": "webhook_trigger", "config": {}}],
        "edges": [],
    }, project_name="acme")
    # Overwrite with a graph that has a non-trigger node only.
    put_pipeline(hook_env["project_dir"], "plain", {
        "schema_version": "1.3",
        "metadata": {"name": "plain", "seed": 0},
        "nodes": [],
        "edges": [],
    }, project_name="acme")
    api_client.put("/api/v1/projects/acme/pipelines/plain/hook", json={"enabled": True, "env": "draft"})
    secret = api_client.post("/api/v1/projects/acme/pipelines/plain/hook/rotate").json()["secret"]
    body = b"{}"
    r = api_client.post("/api/v1/hooks/acme/plain", content=body, headers=_signed_headers(secret, body))
    assert r.status_code == 422
    assert "webhook_trigger" in r.text
