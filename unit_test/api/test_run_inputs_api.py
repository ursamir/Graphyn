"""G3 run inputs over the REST API + cron schedules API."""
from __future__ import annotations

from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode

from unit_test.core._runtime_fixes_nodes import rt_env  # noqa: F401


def _g() -> GraphIR:
    return GraphIR(
        schema_version="1.3",
        metadata=IRMetadata(name="p", seed=0),
        nodes=[
            IRNode(id="a", node_type="rtfix_source", config={"value": 1}),
            IRNode(id="b", node_type="rtfix_add", config={"inc": 1}),
        ],
        edges=[IREdge(src_id="a", src_port="output", dst_id="b", dst_port="input")],
    )


def test_api_run_async_accepts_inputs(api_client, rt_env, monkeypatch):
    import json

    from app.api.routers import pipelines as pipelines_router

    submitted: list = []
    monkeypatch.setattr(pipelines_router._PIPELINE_RUN_EXECUTOR, "submit", lambda fn: submitted.append(fn))

    from app.core.ir.loader import dump_ir

    payload = {"graph": dump_ir(_g()), "inputs": {"b": {"input": [{"rt": True, "v": 1}]}}}
    r = api_client.post("/api/v1/pipelines/run-async", json=payload)
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    meta = json.loads((rt_env / "runs" / run_id / "meta.json").read_text())
    assert meta["input_keys"] == ["b.input"]
    bad = api_client.post("/api/v1/pipelines/run-async",
                          json={"graph": dump_ir(_g()), "inputs": {"ghost": {"input": 1}}})
    assert bad.status_code == 422
    monkeypatch.setenv("GRAPHYN_RUN_INPUTS_MAX_BYTES", "64")
    too_big = api_client.post("/api/v1/pipelines/run-async", json={
        "graph": dump_ir(_g()), "inputs": {"b": {"input": "x" * 200}},
    })
    assert too_big.status_code == 413


def test_api_schedule_accepts_cron(api_client, tmp_workspace):
    r = api_client.post("/api/v1/system/schedules", json={
        "name": "n1", "project": "p", "pipeline": "q", "cron": "0 3 * * *",
    })
    assert r.status_code in (200, 201), r.text
    assert r.json().get("cron") == "0 3 * * *" or r.json().get("schedule", {}).get("cron") == "0 3 * * *"
    bad = api_client.post("/api/v1/system/schedules", json={
        "name": "n2", "project": "p", "pipeline": "q", "cron": "bogus",
    })
    assert bad.status_code == 422


def test_inputs_are_retained_and_replay_reinjects_them(api_client, rt_env, monkeypatch):
    """A run started with inputs replays with exactly those inputs (sha256-checked)."""
    import hashlib
    import json

    from app.api.routers import pipelines as pipelines_router
    from app.core.ir.loader import dump_ir
    from app.core.runs import run_replay

    monkeypatch.setattr(pipelines_router._PIPELINE_RUN_EXECUTOR, "submit", lambda fn: None)
    payload = {"graph": dump_ir(_g()), "inputs": {"b": {"input": [{"rt": True, "v": 7}]}}}
    run_id = api_client.post("/api/v1/pipelines/run-async", json=payload).json()["run_id"]
    run_dir = rt_env / "runs" / run_id
    meta = json.loads((run_dir / "meta.json").read_text())
    blob = (run_dir / "inputs.json").read_bytes()
    assert hashlib.sha256(blob).hexdigest() == meta["inputs_sha256"] and meta["inputs_retained"] is True
    (run_dir / "graph.json").write_text(json.dumps(dump_ir(_g())))

    captured: dict = {}

    class _Backend:
        def execute(self, graph, run_manager=None, input_overrides=None):
            captured["inputs"] = input_overrides

    monkeypatch.setattr("app.core.execution.runtime_backend.get_backend", lambda: _Backend())
    res = run_replay.start_replay(run_dir, actor="qa", submit=lambda fn: fn())
    assert captured["inputs"] == {"b": {"input": [{"rt": True, "v": 7}]}}
    new_meta = json.loads((rt_env / "runs" / res["run_id"] / "meta.json").read_text())
    assert new_meta["inputs_sha256"] == meta["inputs_sha256"]

    # Tampered retained inputs → refused, never silently replayed.
    (run_dir / "inputs.json").write_text('{"b": {"input": [1]}}')
    try:
        run_replay.start_replay(run_dir, actor="qa", submit=lambda fn: fn())
        raise AssertionError("expected ReplayInputsUnavailable")
    except run_replay.ReplayInputsUnavailable:
        pass
    # Not retained → 409 over the API (no silent replay without the payload).
    (run_dir / "inputs.json").unlink()
    r = api_client.post(f"/api/v1/runs/{run_id}/replay", json={})
    assert r.status_code == 409 and "replay_inputs_unavailable" in r.text
