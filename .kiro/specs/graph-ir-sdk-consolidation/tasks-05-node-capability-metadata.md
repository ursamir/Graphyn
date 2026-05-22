# Tasks 05 — Node Capability Metadata (`app/core/nodes/metadata.py`, `app/api/routers/nodes.py`)

## Scope

Extend `NodeMetadata` with seven capability fields (all optional with sensible defaults),
and update the `/api/v1/nodes` response to include a `capability_metadata` object.
No changes to `AutoDiscovery` are required — it already copies all `NodeMetadata` fields.

**Design reference:** [design-05-node-capability-metadata.md](design-05-node-capability-metadata.md)
**Requirements:** Req 5.1 – 5.5 ([req-05-node-capability-metadata.md](req-05-node-capability-metadata.md))
**Depends on:** tasks-01 (IR package, for `IRCapabilityMetadata` reference)

This task group can run in parallel with tasks-02 and tasks-03.

---

## Tasks

- [x] 21. Extend `NodeMetadata` in `app/core/nodes/metadata.py` with capability fields
  - Add seven optional `bool` fields after the existing `output_ports` field:
    ```python
    requires_gpu: bool = False
    supports_cpu: bool = True
    supports_edge: bool = False
    deterministic: bool = True
    cacheable: bool = True
    streaming_support: bool = False
    realtime_support: bool = False
    ```
  - Add docstrings to each field as specified in design-05
  - Do NOT import `IRCapabilityMetadata` here — declare fields directly to avoid circular imports
  - Existing `@field_validator` for `node_type`, `label`, `description`, `category` is unchanged
  - _Requirements: 5.1.1, 5.1.2, 5.1.3, 5.5.1_

  - [x]* 21.1 Write unit tests for `NodeMetadata` capability fields
    - `test_node_metadata_capability_defaults` — all seven fields have correct defaults when not specified
    - `test_node_metadata_capability_override` — fields can be set to non-default values
    - `test_node_metadata_existing_nodes_unaffected` — existing `NodeMetadata` constructions still work
    - _Requirements: 5.1.1, 5.5.1, 5.5.2_

- [x] 22. Update `_node_response()` in `app/api/routers/nodes.py` to include `capability_metadata`
  - Add `"capability_metadata"` key to the returned dict:
    ```python
    "capability_metadata": {
        "requires_gpu": meta.requires_gpu,
        "supports_cpu": meta.supports_cpu,
        "supports_edge": meta.supports_edge,
        "deterministic": meta.deterministic,
        "cacheable": meta.cacheable,
        "streaming_support": meta.streaming_support,
        "realtime_support": meta.realtime_support,
    },
    ```
  - All existing keys in `_node_response()` are preserved unchanged
  - _Requirements: 5.4.1, 5.4.2_

  - [x]* 22.1 Write unit test for capability metadata in API response
    - `test_capability_metadata_in_api_response` — GET `/api/v1/nodes/{node_type}` response
      includes `capability_metadata` dict with all seven fields
    - `test_capability_metadata_list_nodes` — GET `/api/v1/nodes` response includes
      `capability_metadata` for every node in the list
    - _Requirements: 5.4.1, 5.4.2_

- [x] 23. Add `_resolve_capability()` helper to `app/core/pipeline.py`
  - Implement the capability resolution helper as specified in design-05:
    ```python
    def _resolve_capability(ir_node, registry) -> IRCapabilityMetadata:
    ```
  - Precedence: `IRNode.capability_metadata` > `NodeMetadata` capability fields from registry
  - Falls back to `IRCapabilityMetadata()` defaults for unknown node types
  - This helper is for future scheduling use (Phase 2) — not called by the executor in Phase 1
  - _Requirements: 5.2.3, 5.2.4_

- [x] 24. Checkpoint — verify capability metadata
  - Run `venv/bin/pytest tests/ -x --tb=short -q` — all existing tests must pass
  - Verify `NodeMetadata` has all seven capability fields:
    `venv/bin/python -c "from app.core.nodes.metadata import NodeMetadata; m = NodeMetadata(node_type='x', label='x', description='x', category='x'); print(m.requires_gpu, m.supports_cpu)"`
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- All seven capability fields have defaults — existing node implementations require NO changes (Req 5.5.1)
- Existing tests that construct `NodeMetadata` directly continue to work (Req 5.5.2)
- Plugin nodes that declare `NodeMetadata` without capability fields get defaults automatically (Req 5.5.3)
- `AutoDiscovery` requires no changes — it already copies all `NodeMetadata` fields to the registry (Req 5.3.1, 5.3.2)
- The `streaming_support` auto-detection enhancement (checking `cls._is_streaming()`) is optional — node authors can declare `streaming_support=True` explicitly
- `IRCapabilityMetadata` (in `app/core/ir/models.py`) and `NodeMetadata` capability fields have the same names and defaults — single source of truth (Req 5.2.2)
