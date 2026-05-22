# Design 05 — Correctness Properties

## Overview

This sub-document defines the correctness properties for the MCP layer and specifies which properties are suitable for property-based testing (PBT) and which require example-based or integration tests.

The property-based testing library is **Hypothesis** (already used in Phase 1 tests). Each property test runs a minimum of 100 iterations.

---

## PBT Applicability Assessment

The MCP layer is a **thin delegation shell** over existing SDK/core components. Most MCP tool handlers are 10–30 lines of code that:
1. Parse arguments
2. Call an existing SDK/core function
3. Return the result or a structured error

**PBT IS appropriate** for the following categories of MCP behavior:
- **Filtering correctness**: category and capability filters must return only matching nodes — input variation (different filter values) reveals edge cases
- **Cross-interface consistency**: MCP and REST API must return identical data for the same node types — input variation (different node types) reveals inconsistencies
- **Round-trip correctness**: generated graphs must survive serialize/deserialize — input variation (different node lists) reveals serialization bugs
- **Exception safety**: run inspection must never raise unhandled exceptions — input variation (different run IDs) reveals edge cases

**PBT is NOT appropriate** for:
- Tool dispatch and auth (specific behaviors, not universal properties)
- Error branch testing (specific inputs, not universal)
- Infrastructure checks (startup, CLI, transport)

---

## Property-Based Tests (Hypothesis)

### Property 1: Category filter correctness

*For any* category string provided to `list_nodes`, all returned nodes SHALL have a `category` field exactly equal to the provided string.

**Validates: Requirements 2.3**

```python
# Feature: mcp-agent-native, Property 1: Category filter returns only matching nodes
from hypothesis import given, settings
from hypothesis import strategies as st
from app.mcp.handlers.discovery import list_nodes_handler
from app.core.registry_runtime import get_registry

@given(category=st.sampled_from(
    list({m.category for m in get_registry().list_nodes()})
))
@settings(max_examples=100)
def test_category_filter_correctness(category):
    result = list_nodes_handler({"category": category})
    assert "error" not in result
    for node in result["nodes"]:
        assert node["category"] == category, (
            f"Node {node['node_type']} has category {node['category']!r}, "
            f"expected {category!r}"
        )
```

---

### Property 2: Capability filter correctness

*For any* capability filter dict (with valid keys and boolean values) provided to `list_nodes`, all returned nodes SHALL have capability metadata satisfying every key-value pair in the filter.

**Validates: Requirements 2.4, 7.2, 7.3, 7.4**

```python
# Feature: mcp-agent-native, Property 2: Capability filter returns only matching nodes
from hypothesis import given, settings
from hypothesis import strategies as st

_CAPABILITY_KEYS = [
    "requires_gpu", "supports_cpu", "supports_edge",
    "deterministic", "cacheable", "streaming_support", "realtime_support",
]

@given(
    capability_filter=st.fixed_dictionaries(
        {},
        optional={k: st.booleans() for k in _CAPABILITY_KEYS},
    )
)
@settings(max_examples=100)
def test_capability_filter_correctness(capability_filter):
    if not capability_filter:
        return  # skip empty filter (trivially true)

    result = list_nodes_handler({"capability_filter": capability_filter})
    assert "error" not in result

    for node in result["nodes"]:
        cap = node["capability_metadata"]
        for key, expected_value in capability_filter.items():
            assert cap[key] == expected_value, (
                f"Node {node['node_type']} has {key}={cap[key]}, "
                f"expected {expected_value}"
            )
```

---

### Property 3: Node discovery consistency

*For any* node type registered in the NodeRegistry, the `capability_metadata` returned by `list_nodes` SHALL be field-for-field identical to the `capability_metadata` returned by `GET /api/v1/nodes` for the same node type.

**Validates: Requirements 2.11**

```python
# Feature: mcp-agent-native, Property 3: Node discovery consistency with REST API
from hypothesis import given, settings
from hypothesis import strategies as st
from app.mcp.handlers.discovery import list_nodes_handler
from app.core.registry_runtime import get_registry

@given(
    node_type=st.sampled_from(
        [m.node_type for m in get_registry().list_nodes()]
    )
)
@settings(max_examples=100)
def test_node_discovery_consistency(node_type):
    from app.api.routers.nodes import list_nodes as api_list_nodes

    # MCP path
    mcp_result = list_nodes_handler({"node_type": node_type})
    assert "error" not in mcp_result
    mcp_cap = mcp_result["capability_metadata"]

    # REST API path
    api_result = api_list_nodes()
    api_node = next(
        (n for n in api_result if n["node_type"] == node_type), None
    )
    assert api_node is not None, f"Node {node_type} not found in REST API response"
    api_cap = api_node.get("capability_metadata", {})

    assert mcp_cap == api_cap, (
        f"Capability mismatch for {node_type}: MCP={mcp_cap}, API={api_cap}"
    )
```

---

### Property 4: Graph generation round-trip

*For any* valid node list, the GraphIR document produced by `generate_graph` SHALL satisfy `load_ir(dump_ir(graph)).model_dump(mode="json") == graph_dict`.

**Validates: Requirements 3.12**

```python
# Feature: mcp-agent-native, Property 4: Graph generation round-trip
from hypothesis import given, settings
from hypothesis import strategies as st
from app.mcp.handlers.graph import generate_graph_handler
from app.core.ir.loader import load_ir, dump_ir
from app.core.registry_runtime import get_registry

def _node_type_strategy():
    registry = get_registry()
    return st.sampled_from([m.node_type for m in registry.list_nodes()])

@given(
    node_types=st.lists(_node_type_strategy(), min_size=1, max_size=5),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=100)
def test_graph_generation_round_trip(node_types, seed):
    arguments = {
        "nodes": [{"node_type": nt} for nt in node_types],
        "seed": seed,
    }

    graph_dict = generate_graph_handler(arguments)
    if "error" in graph_dict:
        return  # skip invalid configs (e.g. required config fields missing)

    graph = load_ir(graph_dict)
    round_trip_dict = dump_ir(graph)

    assert graph_dict == round_trip_dict, (
        f"Round-trip mismatch for nodes={node_types}"
    )
```

---

### Property 5: Validation and execution consistency

*For any* GraphIR document for which `validate_graph` returns `valid: true`, the `execute_pipeline` tool SHALL accept the document and return a `run_id` without returning a validation error.

**Validates: Requirements 4.14**

```python
# Feature: mcp-agent-native, Property 5: Validation and execution consistency
from hypothesis import given, settings
from hypothesis import strategies as st
from app.mcp.handlers.graph import generate_graph_handler, validate_graph_handler
from app.mcp.handlers.execution import execute_pipeline_handler
from app.core.registry_runtime import get_registry

@given(
    node_types=st.lists(
        st.sampled_from([m.node_type for m in get_registry().list_nodes()]),
        min_size=1,
        max_size=3,
    )
)
@settings(max_examples=100)
def test_validation_execution_consistency(node_types):
    graph_dict = generate_graph_handler({
        "nodes": [{"node_type": nt} for nt in node_types],
    })
    if "error" in graph_dict:
        return  # skip invalid configs

    validation_result = validate_graph_handler({"graph": graph_dict})
    if not validation_result.get("valid"):
        return  # skip invalid graphs

    # If validate_graph says valid, execute_pipeline must accept it
    execution_result = execute_pipeline_handler({"graph": graph_dict})
    assert "run_id" in execution_result, (
        f"execute_pipeline rejected a graph that validate_graph accepted: "
        f"{execution_result}"
    )
    assert execution_result.get("status") == "started"
```

---

### Property 6: Run inspection exception safety

*For any* run ID returned by `inspect_run`'s list operation, a subsequent invocation of `inspect_run` with that `run_id` SHALL return a dict containing either run metadata or a structured error — it SHALL NOT raise an unhandled exception.

**Validates: Requirements 5.11**

```python
# Feature: mcp-agent-native, Property 6: Run inspection exception safety
from hypothesis import given, settings
from hypothesis import strategies as st
from app.mcp.handlers.artifacts import inspect_run_handler

@given(flags=st.fixed_dictionaries(
    {},
    optional={
        "logs": st.booleans(),
        "graph": st.booleans(),
        "checkpoints": st.booleans(),
        "status_only": st.booleans(),
    }
))
@settings(max_examples=100)
def test_run_inspection_exception_safety(flags):
    # List all runs
    list_result = inspect_run_handler({})
    run_ids = [r["run_id"] for r in list_result.get("runs", [])]

    if not run_ids:
        return  # no runs to inspect

    # Sample a run ID from the list
    run_id = run_ids[0]

    # Inspect with random flags — must never raise
    arguments = {"run_id": run_id, **flags}
    result = inspect_run_handler(arguments)

    assert isinstance(result, dict), "inspect_run must return a dict"
    if result.get("error"):
        assert "error_type" in result
        assert "message" in result
```

---

### Property 7: Capability summary consistency

*For any* GraphIR document, the `any_requires_gpu`, `all_support_cpu`, `all_support_edge`, and `all_deterministic` values returned by `get_graph_capability_summary` SHALL equal the values computed by applying the two-step resolution rule to each node's capability metadata as returned by `list_nodes` for the same node types.

**Validates: Requirements 7.9**

```python
# Feature: mcp-agent-native, Property 7: Capability summary consistency
from hypothesis import given, settings
from hypothesis import strategies as st
from app.mcp.handlers.graph import generate_graph_handler, get_graph_capability_summary_handler
from app.mcp.handlers.discovery import list_nodes_handler
from app.core.registry_runtime import get_registry

@given(
    node_types=st.lists(
        st.sampled_from([m.node_type for m in get_registry().list_nodes()]),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=100)
def test_capability_summary_consistency(node_types):
    graph_dict = generate_graph_handler({
        "nodes": [{"node_type": nt} for nt in node_types],
    })
    if "error" in graph_dict:
        return  # skip invalid configs

    summary = get_graph_capability_summary_handler({"graph": graph_dict})
    if "error" in summary:
        return  # skip if any node type is unregistered

    # Compute expected values from list_nodes
    capabilities = []
    for nt in node_types:
        node_info = list_nodes_handler({"node_type": nt})
        if "error" in node_info:
            return  # skip if node not found
        capabilities.append(node_info["capability_metadata"])

    assert summary["any_requires_gpu"] == any(c["requires_gpu"] for c in capabilities)
    assert summary["all_support_cpu"] == all(c["supports_cpu"] for c in capabilities)
    assert summary["all_support_edge"] == all(c["supports_edge"] for c in capabilities)
    assert summary["all_deterministic"] == all(c["deterministic"] for c in capabilities)
```

---

## Testable Properties (Example-Based)

### Property 1: Auth enforcement

**For any** tool invocation when `GRAPHYN_API_TOKEN` is set, if `_meta.auth_token` is absent or incorrect, the tool SHALL return `error_type: "unauthorized"` without executing the tool logic.

**Test type:** Example-based unit test  
**Validates:** Requirements 1.9, 1.10, 8.9

```python
def test_auth_required_when_token_set(monkeypatch):
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "secret123")
    # Reload auth module to pick up env var
    import importlib
    import app.mcp.auth
    importlib.reload(app.mcp.auth)

    from app.mcp.auth import check_auth

    # Missing token
    result = check_auth({})
    assert result["error_type"] == "unauthorized"

    # Wrong token
    result = check_auth({"_meta": {"auth_token": "wrong"}})
    assert result["error_type"] == "unauthorized"

    # Correct token
    result = check_auth({"_meta": {"auth_token": "secret123"}})
    assert result is None
```

---

### Property 2: Unknown tool error

**For any** tool name not in the registered tool set, the MCP server SHALL return `error_type: "unknown_tool"` with an `available_tools` list.

**Test type:** Example-based unit test  
**Validates:** Requirement 1.4

```python
def test_unknown_tool_error():
    from app.mcp.server import handle_call_tool
    import asyncio

    result = asyncio.run(handle_call_tool("nonexistent_tool", {}))
    content = json.loads(result[0].text)
    assert content["error_type"] == "unknown_tool"
    assert "available_tools" in content
```

---

### Property 3: Node discovery consistency

**For any** node type registered in the NodeRegistry, the `capability_metadata` returned by `list_nodes` SHALL be field-for-field identical to the `capability_metadata` returned by `GET /api/v1/nodes` for the same node type.

**Test type:** Integration test  
**Validates:** Requirement 2.11

```python
def test_node_discovery_consistency():
    from app.mcp.handlers.discovery import list_nodes_handler
    from app.api.routers.nodes import list_nodes as api_list_nodes
    from app.core.registry_runtime import get_registry

    registry = get_registry()
    all_node_types = [m.node_type for m in registry.list_nodes()]

    for node_type in all_node_types:
        # MCP path
        mcp_result = list_nodes_handler({"node_type": node_type})
        mcp_cap = mcp_result["capability_metadata"]

        # REST API path
        api_result = api_list_nodes()
        api_node = next(n for n in api_result if n["node_type"] == node_type)
        api_cap = api_node["capability_metadata"]

        assert mcp_cap == api_cap, f"Capability mismatch for {node_type}"
```

---

### Property 4: Graph generation round-trip

**For any** valid node list, the GraphIR produced by `generate_graph` SHALL satisfy `load_ir(dump_ir(graph)) == graph`.

**Test type:** Example-based unit test (not PBT — the handler is pure delegation)  
**Validates:** Requirement 3.12

```python
def test_graph_generation_round_trip():
    from app.mcp.handlers.graph import generate_graph_handler
    from app.core.ir.loader import load_ir, dump_ir

    arguments = {
        "nodes": [
            {"node_type": "input", "config": {"path": "workspace/datasets/input/speech"}},
            {"node_type": "clean", "config": {"sample_rate": 16000}},
        ],
        "seed": 42,
    }

    graph_dict = generate_graph_handler(arguments)
    assert "error" not in graph_dict

    graph = load_ir(graph_dict)
    round_trip_dict = dump_ir(graph)

    assert graph_dict == round_trip_dict
```

---

### Property 5: Validation consistency

**For any** GraphIR document, if `validate_graph` returns `valid: true`, then `execute_pipeline` SHALL accept the document without returning a validation error.

**Test type:** Integration test  
**Validates:** Requirement 4.14

```python
def test_validation_execution_consistency():
    from app.mcp.handlers.graph import generate_graph_handler, validate_graph_handler
    from app.mcp.handlers.execution import execute_pipeline_handler

    arguments = {
        "nodes": [
            {"node_type": "input", "config": {"path": "workspace/datasets/input/speech"}},
        ],
    }

    graph_dict = generate_graph_handler(arguments)
    validation_result = validate_graph_handler({"graph": graph_dict})
    assert validation_result["valid"] is True

    execution_result = execute_pipeline_handler({"graph": graph_dict})
    assert "run_id" in execution_result
    assert execution_result["status"] == "started"
```

---

### Property 6: Run inspection consistency

**For any** run ID returned by `inspect_run`'s list operation, a subsequent invocation with that `run_id` SHALL return either metadata or a structured error (never an unhandled exception).

**Test type:** Integration test  
**Validates:** Requirement 5.11

```python
def test_run_inspection_consistency():
    from app.mcp.handlers.artifacts import inspect_run_handler

    # List all runs
    list_result = inspect_run_handler({})
    run_ids = [r["run_id"] for r in list_result["runs"]]

    # Inspect each run
    for run_id in run_ids:
        result = inspect_run_handler({"run_id": run_id})
        # Must return either metadata or a structured error
        assert isinstance(result, dict)
        if "error" in result:
            assert "error_type" in result
            assert "message" in result
        else:
            assert "run_id" in result or "status" in result
```

---

### Property 7: Capability summary consistency

**For any** GraphIR document, the `any_requires_gpu`, `all_support_cpu`, `all_support_edge`, and `all_deterministic` values returned by `get_graph_capability_summary` SHALL be derivable by applying the two-step resolution rule to each node's capability metadata as returned by `list_nodes`.

**Test type:** Integration test  
**Validates:** Requirement 7.9

```python
def test_capability_summary_consistency():
    from app.mcp.handlers.graph import generate_graph_handler, get_graph_capability_summary_handler
    from app.mcp.handlers.discovery import list_nodes_handler

    arguments = {
        "nodes": [
            {"node_type": "input", "config": {}},
            {"node_type": "clean", "config": {}},
        ],
    }

    graph_dict = generate_graph_handler(arguments)
    summary = get_graph_capability_summary_handler({"graph": graph_dict})

    # Manually compute expected values
    node_types = [n["node_type"] for n in arguments["nodes"]]
    capabilities = []
    for nt in node_types:
        node_info = list_nodes_handler({"node_type": nt})
        capabilities.append(node_info["capability_metadata"])

    expected_any_requires_gpu = any(c["requires_gpu"] for c in capabilities)
    expected_all_support_cpu = all(c["supports_cpu"] for c in capabilities)
    expected_all_support_edge = all(c["supports_edge"] for c in capabilities)
    expected_all_deterministic = all(c["deterministic"] for c in capabilities)

    assert summary["any_requires_gpu"] == expected_any_requires_gpu
    assert summary["all_support_cpu"] == expected_all_support_cpu
    assert summary["all_support_edge"] == expected_all_support_edge
    assert summary["all_deterministic"] == expected_all_deterministic
```

---

## Test Coverage Summary

| Property | Test Type | Validates |
|---|---|---|
| Auth enforcement | Example-based unit | Req 1.9, 1.10, 8.9 |
| Unknown tool error | Example-based unit | Req 1.4 |
| Node discovery consistency | Integration | Req 2.11 |
| Graph generation round-trip | Example-based unit | Req 3.12 |
| Validation consistency | Integration | Req 4.14 |
| Run inspection consistency | Integration | Req 5.11 |
| Capability summary consistency | Integration | Req 7.9 |

---

## Additional Unit Tests (Not Properties)

Each tool handler requires example-based unit tests for:
- Valid inputs → success response
- Invalid inputs → structured error with correct `error_type`
- All error branches (unknown node type, invalid config, missing artifact, etc.)

Example test structure:

```python
def test_list_nodes_category_filter():
    result = list_nodes_handler({"category": "audio"})
    assert all(n["category"] == "audio" for n in result["nodes"])

def test_list_nodes_unknown_node_type():
    result = list_nodes_handler({"node_type": "nonexistent"})
    assert result["error_type"] == "unknown_node_type"
    assert "available_types" in result

def test_generate_graph_invalid_node_config():
    result = generate_graph_handler({
        "nodes": [{"node_type": "clean", "config": {"sample_rate": "invalid"}}]
    })
    assert result["error_type"] == "invalid_node_config"

def test_inspect_run_unknown_run_id():
    result = inspect_run_handler({"run_id": "nonexistent"})
    assert result["error_type"] == "unknown_run_id"
```

---

## Non-Regression Tests

All 421 Phase 1 tests must pass after Phase 2 implementation (Req 8.7). This is verified by running the existing test suite without modification:

```bash
venv/bin/pytest tests/ -v
```

Expected result: 421 passed, 0 failed.
