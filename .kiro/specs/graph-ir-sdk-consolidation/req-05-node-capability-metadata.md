# req-05 — Node Capability Metadata

## Introduction

This document defines requirements for extending `NodeMetadata` with capability fields that describe a node's hardware requirements, execution characteristics, and runtime compatibility. These fields are optional with sensible defaults and are designed to be machine-readable for Phase 2 (MCP + Agent-Native Architecture).

The IR node spec (`IRNode`) includes a reference to capability metadata so that the IR is self-describing with respect to execution requirements.

---

## Glossary

See [requirements.md](requirements.md) for the full glossary. Terms used here:

- **NodeMetadata**, **IRNode**, **IR**, **AutoDiscovery**

Additional terms:

- **IRCapabilityMetadata** — A Pydantic model embedded in `IRNode` that carries capability hints for a node instance within a specific graph.
- **NodeCapabilityMetadata** — A Pydantic model embedded in `NodeMetadata` that carries capability declarations for a node class.

---

## Requirements

### Requirement 5.1 — NodeMetadata Capability Fields

**User Story:** As a node author, I want to declare my node's hardware and execution capabilities in `NodeMetadata`, so that schedulers, agents, and deployment planners can make informed decisions without inspecting node internals.

#### Acceptance Criteria

1. THE `NodeMetadata` model SHALL be extended with the following optional fields, all with sensible defaults:
   - `requires_gpu`: `bool` — whether the node requires a GPU to execute (default: `False`)
   - `supports_cpu`: `bool` — whether the node can execute on CPU (default: `True`)
   - `supports_edge`: `bool` — whether the node is suitable for edge deployment (default: `False`)
   - `deterministic`: `bool` — whether the node produces identical outputs for identical inputs and seed (default: `True`)
   - `cacheable`: `bool` — whether the node's outputs can be safely cached (default: `True`)
   - `streaming_support`: `bool` — whether the node supports streaming execution via `process_stream` (default: `False`)
   - `realtime_support`: `bool` — whether the node can process data in real-time (default: `False`)
2. THE existing `NodeMetadata` fields (`node_type`, `label`, `description`, `category`, `version`, `tags`, `input_ports`, `output_ports`) SHALL remain unchanged.
3. THE new capability fields SHALL be serializable to JSON via `NodeMetadata.model_dump(mode="json")`.
4. WHEN a `NodeMetadata` is constructed without specifying capability fields, THE defaults SHALL apply and the model SHALL be valid.

---

### Requirement 5.2 — Capability Metadata in IR

**User Story:** As a platform developer, I want the IR node spec to optionally carry capability metadata, so that the IR document is self-describing with respect to execution requirements.

#### Acceptance Criteria

1. THE `IRNode` model SHALL include an optional field `capability_metadata: IRCapabilityMetadata | None` (default: `None`).
2. THE `IRCapabilityMetadata` model SHALL contain the same fields as the capability fields added to `NodeMetadata` in Requirement 5.1.
3. WHEN `IRNode.capability_metadata` is `None`, THE `DAG_Executor` SHALL proceed with execution using the node class's declared `NodeMetadata` capability fields as the authoritative source.
4. WHEN `IRNode.capability_metadata` is set, THE `IRCapabilityMetadata` values SHALL take precedence over the node class's `NodeMetadata` capability fields for that specific node instance in that graph.
5. THE `IRCapabilityMetadata` model SHALL be importable from `app.core.ir`.

---

### Requirement 5.3 — AutoDiscovery Capability Population

**User Story:** As a platform developer, I want `AutoDiscovery` to populate capability metadata from node class declarations, so that the registry reflects each node's capabilities without manual registration.

#### Acceptance Criteria

1. WHEN `AutoDiscovery` registers a node class, THE `NodeMetadata` stored in the registry SHALL include the capability fields declared on that node class's `metadata` attribute.
2. WHEN a node class does not declare capability fields on its `metadata`, THE registry SHALL store the default values defined in Requirement 5.1.
3. THE `NodeRegistry.list_nodes()` response SHALL include capability fields in the returned `NodeMetadata` objects.

---

### Requirement 5.4 — Capability Metadata in API Response

**User Story:** As an API consumer, I want node capability metadata included in the node listing response, so that clients can filter and select nodes based on hardware requirements.

#### Acceptance Criteria

1. THE `/api/v1/nodes` endpoint response SHALL include the capability fields for each node in the listing.
2. THE capability fields SHALL be nested under a `capability_metadata` key in each node's response object.
3. WHEN a node does not declare capability fields, THE API response SHALL include the default values.

---

### Requirement 5.5 — Backward Compatibility of NodeMetadata

**User Story:** As a node author, I want existing node implementations to continue working without modification, so that adding capability fields does not break the existing node ecosystem.

#### Acceptance Criteria

1. WHEN an existing node class declares a `metadata` attribute without capability fields, THE `NodeMetadata` model SHALL apply default values for all capability fields without raising a `ValidationError`.
2. THE `NodeMetadata` model SHALL remain backward-compatible with all existing node implementations in `app/core/nodes/audio/` and `app/core/nodes/ml/`.
3. THE `NodeMetadata` model SHALL remain backward-compatible with all existing plugins in `plugins/`.
