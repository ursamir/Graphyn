# req-06 — Full 6-Phase Roadmap

## Introduction

This document preserves the full six-phase roadmap for evolving the platform into a general-purpose AI/workflow execution platform. It is included in the spec for future reference and to provide context for design decisions made in Phase 1.

Each phase builds on the foundations established by the previous phases. Phase 1 (this spec) is the prerequisite for all subsequent phases.

---

## Strategic Vision

The platform shall evolve from an audio-focused dataset pipeline tool into a **general-purpose AI/workflow execution platform** capable of powering:

- AI pipelines
- ML training and inference workflows
- Edge AI workflows
- Multimodal processing graphs
- Automation workflows
- Agent-generated workflows
- Plugin ecosystems

The system shall remain SDK-first, CLI-first, API-first, MCP-native, and frontend-optional.

The primary strategic asset shall become a **standardized executable workflow graph ecosystem** — not merely a frontend application, an audio processing tool, or a node editor.

The long-term moat shall be:
- Graph and runtime specification
- SDK ecosystem
- Plugin ecosystem
- Typed execution model
- MCP operability
- Agent-native workflows

---

## Phase 1 — Graph IR + SDK Consolidation (THIS PHASE)

**Goal:** Establish the canonical graph representation and consolidate all interfaces behind a single SDK runtime.

**Deliverables:**
- Formal Graph IR: JSON, versioned, validated, runtime-agnostic (`app/core/ir/`)
- SDK rewrite: `Pipeline`/`PipelineNode` internals backed by IR (public API unchanged)
- DAG executor wired to consume IR natively (`run_pipeline_ir()`)
- YAML shim with deprecation warning + migration utility (`audiobuilder migrate`)
- All interfaces (CLI, REST API) delegate to SDK

**Foundation for:** All subsequent phases. The IR defined here is the graph contract that Phases 2–6 build upon.

---

## Phase 2 — MCP + Agent-Native Architecture

**Goal:** Make the platform natively operable by AI agents via the Model Context Protocol (MCP).

**Deliverables:**
- MCP layer as first-class architecture (not an adapter)
- Node schemas, graph schemas, and capability metadata exposed as MCP-compatible interfaces
- Agents can: discover nodes, generate workflows, validate graphs, execute pipelines, inspect artifacts — without UI
- Node system and graph IR designed specifically for machine operability

**Depends on:** Phase 1 (IR + capability metadata from req-05 are the foundation for MCP schema exposure).

**Key design constraint from Phase 1:** The `IRCapabilityMetadata` fields added in req-05 (`requires_gpu`, `supports_cpu`, `supports_edge`, `deterministic`, `cacheable`, `streaming_support`, `realtime_support`) are specifically designed to be machine-readable for this phase.

---

## Phase 3 — Advanced Runtime

**Goal:** Extend the execution runtime with advanced execution modes.

**Deliverables:**
- Async runtime
- Parallel execution
- Resumability
- Partial execution
- Conditional branching
- Event-driven execution

**Depends on:** Phase 1 (IR is the graph contract; the runtime extensions operate on IR objects).

**Key design constraint from Phase 1:** The IR must be runtime-agnostic (req-01, Requirement 1.11) so that Phase 3 can introduce new execution backends without changing the IR schema.

---

## Phase 4 — Provenance + Artifact System

**Goal:** Elevate artifacts and execution lineage to first-class platform entities.

**Deliverables:**
- Artifacts as first-class entities
- Lineage tracking, metadata, reproducibility, versioning, caching
- `RunManager` evolves into a full provenance layer
- Critical for: ML workflows, agent memory, graph optimization, deployment traceability

**Depends on:** Phase 1 (IR's deterministic replay requirement, req-01 Requirement 1.10, is the foundation for reproducibility).

**Key design constraint from Phase 1:** The `GraphIR` stored in `{run_dir}/graph.json` (req-03, Requirement 3.6) is the artifact that Phase 4's provenance layer will index and query.

---

## Phase 5 — Plugin Ecosystem

**Goal:** Evolve the existing AutoDiscovery plugin architecture into a full plugin ecosystem.

**Deliverables:**
- Plugin manifests
- Dependency isolation
- Version constraints
- Remote plugins
- Marketplace architecture

**Depends on:** Phase 3 (stabilized runtime is required before plugins can safely extend execution behavior).

**Key design constraint from Phase 1:** The `NodeMetadata` capability fields added in req-05 are the foundation for plugin capability discovery in Phase 5.

---

## Phase 6 — Edge AI Expansion

**Goal:** Enable deployment of workflows to edge hardware targets.

**Deliverables:**
- Hardware deployment ecosystem
- Quantization, model conversion, hardware optimization
- Deployment packaging, inference benchmarking
- Targets: Raspberry Pi, NVIDIA Jetson, Coral TPU, TFLite, ONNX Runtime, TensorRT

**Depends on:** Phase 4 (artifact system is required for deployment packaging and model versioning).

**Key design constraint from Phase 1:** The `supports_edge` capability field in `IRCapabilityMetadata` (req-05) is the Phase 1 hook that Phase 6 will use to filter and schedule edge-compatible nodes.

---

## Cross-Phase Design Constraints

The following constraints from Phase 1 have explicit implications for future phases and must be respected in all implementation decisions:

| Constraint | Phase 1 Requirement | Impacts |
|---|---|---|
| IR is runtime-agnostic | req-01, Req 1.11 | Phase 3 (new backends), Phase 6 (edge backends) |
| IR carries schema version | req-01, Req 1.7 | All phases (forward compatibility) |
| IR supports deterministic replay | req-01, Req 1.10 | Phase 4 (provenance), Phase 3 (resumability) |
| Capability metadata in IR | req-05, Req 5.2 | Phase 2 (MCP), Phase 5 (plugins), Phase 6 (edge) |
| SDK is single source of truth | req-02, Req 2.9 | Phase 2 (MCP delegates to SDK), Phase 3 (SDK exposes new runtime modes) |
| NDJSON event streaming preserved | req-03, Req 3.5 | Phase 2 (MCP event streams), Phase 3 (distributed monitoring) |
| GraphIR stored per run | req-03, Req 3.6 | Phase 4 (provenance layer indexes run graphs) |
