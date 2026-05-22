# Design — Test Patterns & Templates

> **Parent:** `design.md`

One template per test category. Copy-paste and adapt.

---

## Pattern 1: Pure Unit Test (no fixtures needed)

For stateless functions with no I/O.

```python
# unit_test/core/test_conditions.py
import pytest
from app.core.conditions import evaluate_condition, ConditionEvaluationError

def test_len_gt_true():
    assert evaluate_condition("len(output['output']) > 2", {"output": [1, 2, 3]}) is True

def test_len_gt_false():
    assert evaluate_condition("len(output['output']) > 2", {"output": [1]}) is False

def test_import_raises():
    with pytest.raises(ConditionEvaluationError, match="Disallowed"):
        evaluate_condition("import os", {})

def test_unknown_name_raises():
    with pytest.raises(ConditionEvaluationError, match="Disallowed name"):
        evaluate_condition("x > 1", {})
```

---

## Pattern 2: Registry Test (uses `fresh_registry`)

```python
# unit_test/core/nodes/test_registry.py
import pytest
from app.core.nodes.errors import NodeNotFoundError

def test_register_and_lookup(fresh_registry, minimal_node_cls, minimal_meta):
    fresh_registry.register("_minimal_test_node", minimal_node_cls, minimal_meta)
    assert "_minimal_test_node" in fresh_registry
    assert fresh_registry.get_class("_minimal_test_node") is minimal_node_cls

def test_unregister(fresh_registry, minimal_node_cls, minimal_meta):
    fresh_registry.register("_minimal_test_node", minimal_node_cls, minimal_meta)
    fresh_registry.unregister("_minimal_test_node")
    assert "_minimal_test_node" not in fresh_registry

def test_get_unregistered_raises(fresh_registry):
    with pytest.raises(NodeNotFoundError):
        fresh_registry.get_class("nonexistent")

def test_unregister_noop(fresh_registry):
    fresh_registry.unregister("nonexistent")  # must not raise
```

---

## Pattern 3: Plugin Install Test (uses `tmp_plugin_dir` + `fresh_registry`)

```python
# unit_test/plugins/audio/test_audio_conditioner.py
import pytest
from app.core.plugins.manager import PluginManager

def test_registers_node_type(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry)
    mgr.install("PluginPackage/Audio/audio_conditioner/", plugins_dir=tmp_plugin_dir)
    assert "audio_conditioner" in fresh_registry

def test_metadata_correct(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry)
    mgr.install("PluginPackage/Audio/audio_conditioner/", plugins_dir=tmp_plugin_dir)
    meta = fresh_registry.get_metadata("audio_conditioner")
    assert meta.label
    assert meta.category
    assert meta.version

def test_node_constructs(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry)
    mgr.install("PluginPackage/Audio/audio_conditioner/", plugins_dir=tmp_plugin_dir)
    cls = fresh_registry.get_class("audio_conditioner")
    node = cls(config={}, seed=0)
    assert node is not None

def test_process_returns_list(tmp_plugin_dir, fresh_registry, make_audio_sample):
    mgr = PluginManager(registry=fresh_registry)
    mgr.install("PluginPackage/Audio/audio_conditioner/", plugins_dir=tmp_plugin_dir)
    cls = fresh_registry.get_class("audio_conditioner")
    node = cls(config={}, seed=0)
    result = node.process({"input": [make_audio_sample()]})
    assert isinstance(result["output"], list)
    assert len(result["output"]) == 1
```

---

## Pattern 4: API Router Test (uses `api_client`)

```python
# unit_test/api/test_system_router.py
def test_health_ok(api_client):
    resp = api_client.get("/api/v1/system/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert "timestamp" in resp.json()

def test_health_timestamp_utc(api_client):
    resp = api_client.get("/api/v1/system/health")
    ts = resp.json()["timestamp"]
    assert ts.endswith("+00:00")
```

For tests that need mocked services:

```python
# unit_test/api/test_artifacts_router.py
from unittest.mock import patch, MagicMock
from app.core.artifact_store import ArtifactNotFoundError

def test_get_artifact_404(api_client):
    with patch("app.api.routers.artifacts.ArtifactStore") as MockStore:
        MockStore.return_value.get.side_effect = ArtifactNotFoundError("abc")
        resp = api_client.get("/api/v1/artifacts/abc")
    assert resp.status_code == 404

def test_invalid_artifact_id_400(api_client):
    resp = api_client.get("/api/v1/artifacts/bad!id")
    assert resp.status_code == 400
```

---

## Pattern 5: MCP Handler Test (thread-patched)

The `patch_threads` autouse fixture already patches `ThreadPoolExecutor.submit`.
For `execute_pipeline_handler`, also patch `run_pipeline_ir` explicitly:

```python
# unit_test/mcp/test_handler_execution.py
from unittest.mock import patch
from app.mcp.handlers.execution import execute_pipeline_handler
from app.mcp.handlers.graph import generate_graph_handler

def _valid_graph():
    result = generate_graph_handler({"nodes": [{"node_type": "audio_conditioner"}]})
    assert "error" not in result
    return result

def test_valid_graph_returns_run_id():
    graph = _valid_graph()
    with patch("app.mcp.handlers.execution.run_pipeline_ir"):
        result = execute_pipeline_handler({"graph": graph})
    assert "run_id" in result
    assert result["status"] == "started"

def test_invalid_graph_returns_valid_false():
    result = execute_pipeline_handler({"graph": {"bad": "data"}})
    assert result["valid"] is False
    assert len(result["errors"]) > 0
```

---

## Pattern 6: CLI Test (Click test runner)

```python
# unit_test/cli/test_cli.py
from click.testing import CliRunner
from app.cli.main import cli

def test_list_nodes_exits_zero():
    runner = CliRunner()
    result = runner.invoke(cli, ["list-nodes"])
    assert result.exit_code == 0
    assert len(result.output) > 0

def test_validate_unknown_node_exits_nonzero(tmp_path):
    import json
    from app.core.ir.loader import CURRENT_IR_VERSION
    graph = {
        "schema_version": CURRENT_IR_VERSION,
        "metadata": {"name": "t", "seed": 0},
        "nodes": [{"id": "n0", "node_type": "nonexistent_xyz", "config": {}}],
        "edges": [],
    }
    p = tmp_path / "bad.graph.json"
    p.write_text(json.dumps(graph))
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "--graph", str(p)])
    assert result.exit_code != 0
```

---

## Pattern 7: Property-Based Test (Hypothesis)

```python
# unit_test/core/nodes/test_retry.py
import math
from hypothesis import given, settings
from hypothesis import strategies as st
from app.core.nodes.retry import RetryPolicy

@given(
    backoff_s=st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False),
    multiplier=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    attempt=st.integers(min_value=1, max_value=9),
)
@settings(max_examples=100)
def test_wait_monotonic(backoff_s, multiplier, attempt):
    p = RetryPolicy(max_attempts=10, backoff_seconds=backoff_s, backoff_multiplier=multiplier)
    assert p.wait_before_attempt(attempt) >= p.wait_before_attempt(attempt - 1)
```

---

## Pattern 8: Filesystem Test (uses `tmp_workspace`)

```python
# unit_test/core/test_artifact_store.py
from app.core.artifact_store import ArtifactStore, ArtifactNotFoundError

def test_register_and_get(tmp_workspace):
    store = ArtifactStore(base_dir=str(tmp_workspace))
    record = store.register("run1", "node1", "audio_conditioner", "generic", {"key": "val"})
    assert record.artifact_id
    assert record.content_hash

    fetched = store.get(record.artifact_id)
    assert fetched.artifact_id == record.artifact_id

def test_get_nonexistent_raises(tmp_workspace):
    store = ArtifactStore(base_dir=str(tmp_workspace))
    with pytest.raises(ArtifactNotFoundError):
        store.get("nonexistent")

def test_deduplication(tmp_workspace):
    store = ArtifactStore(base_dir=str(tmp_workspace))
    r1 = store.register("run1", "n1", "audio_conditioner", "generic", {"x": 1})
    r2 = store.register("run2", "n2", "audio_conditioner", "generic", {"x": 1})
    assert r1.artifact_id == r2.artifact_id  # same content → same ID
```

---

## Pattern 9: Thread-Safety Test (overrides `patch_threads`)

For `test_ingestion.py` Req 21 criterion 2 — needs real threads:

```python
# unit_test/core/test_ingestion.py
import threading
import pytest
from app.core.ingestion import IngestionJob

@pytest.mark.usefixtures()  # does NOT use patch_threads
def test_append_progress_thread_safe(monkeypatch):
    # Temporarily undo the autouse patch for this test only
    import concurrent.futures, threading as _threading
    real_submit = concurrent.futures.ThreadPoolExecutor.submit
    real_start = _threading.Thread.start

    job = IngestionJob(job_id="x", status="running")
    threads = []
    for _ in range(10):
        t = threading.Thread(target=lambda: [job.append_progress({"i": i}) for i in range(10)])
        threads.append(t)
    for t in threads:
        real_start(t)
    for t in threads:
        t.join(timeout=5.0)

    assert len(job.read_progress()) == 100
```

> **Note:** This test bypasses `patch_threads` by calling `real_start` directly.
> It must join all threads before the test ends to avoid leaking threads.
