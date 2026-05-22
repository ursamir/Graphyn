# Requirements Document — Graph IR + SDK Consolidation (Phase 1)

## Introduction

This document captures the requirements for **Phase 1** of a six-phase roadmap to evolve the platform into a general-purpose AI/workflow execution platform.

Phase 1 introduces a formal **Graph Intermediate Representation (IR)** — a versioned, validated, runtime-agnostic JSON schema — and consolidates the SDK so that all interfaces (CLI, REST API, MCP, Frontend) delegate to a single SDK runtime backed by the IR. The existing YAML pipeline format is demoted to a serialization shim with a migration path to IR JSON.

The 441 existing passing tests must not regress. All current public APIs (`Pipeline`, `PipelineNode`, CLI commands, REST endpoints) must remain functional throughout this phase.

---

## Sub-Document Index

| Sub-Document | Description |
|---|---|
| [req-01-graph-ir.md](req-01-graph-ir.md) | Graph IR model, Pydantic schema, versioning, validation, deterministic replay |
| [req-02-sdk-consolidation.md](req-02-sdk-consolidation.md) | SDK surface (`Pipeline`/`PipelineNode`), IR-backed internals, serialization methods |
| [req-03-executor-wiring.md](req-03-executor-wiring.md) | DAG executor changes, IR-native execution path, event streaming compatibility |
| [req-04-yaml-compat.md](req-04-yaml-compat.md) | YAML compatibility shim, migration utility, CLI and API updates |
| [req-05-node-capability-metadata.md](req-05-node-capability-metadata.md) | `NodeMetadata` capability field extensions for Phase 2 readiness |
| [req-06-roadmap.md](req-06-roadmap.md) | Full 6-phase roadmap preserved for future reference |

---

## Glossary

- **IR** — Intermediate Representation. The canonical, runtime-agnostic JSON graph object defined in `app/core/ir/`.
- **IR_Loader** — The component responsible for deserializing and validating IR JSON documents.
- **IR_Schema** — The Pydantic model hierarchy (`GraphIR`, `IRNode`, `IREdge`, `IRParameter`, `IRMetadata`) that defines the IR structure.
- **SDK** — The Python SDK (`app/core/sdk.py`). Exposes `Pipeline` and `PipelineNode` as the primary programmatic interface.
- **Pipeline** — The SDK class representing a complete executable graph. Internals are backed by an IR graph object after this phase.
- **PipelineNode** — The SDK class representing a single node within a `Pipeline`.
- **DAG_Executor** — The `run_pipeline()` function and supporting classes in `app/core/pipeline.py`.
- **PipelineGraph** — The DAG builder and topological sorter in `app/core/pipeline.py`.
- **YAML_Shim** — The compatibility layer that parses legacy YAML pipeline configs and converts them to IR objects, emitting a `DeprecationWarning`.
- **Migration_Utility** — The `app/core/ir/migrate.py` script that converts a YAML pipeline config file to an IR JSON file.
- **NodeMetadata** — The Pydantic model in `app/core/nodes/metadata.py` describing a node's identity, ports, and display properties.
- **CompatibilityChecker** — The component in `app/core/nodes/compat.py` that validates port-to-port type compatibility.
- **AutoDiscovery** — The registry scanner in `app/core/nodes/discovery.py` that populates the `NodeRegistry` at startup.
- **RunManager** — The component in `app/core/run_manager.py` that manages run lifecycle, metadata, and log persistence.
- **PipelineLogger** — The structured NDJSON event logger in `app/core/logger.py`.
- **CLI** — The command-line interface at `app/cli/main.py` (`audiobuilder` command).
- **REST_API** — The FastAPI application at `app/api/main.py` with routers under `/api/v1/`.
- **Schema_Version** — A string field (e.g. `"1.0"`) embedded in every IR document that identifies the IR schema version.
- **Seed** — An integer value embedded in the IR that seeds all random operations, enabling deterministic replay.

---

## Current Architecture (Preserved — Must Not Regress)

The following components exist today and must remain fully functional after Phase 1:

| Component | Location | Status |
|---|---|---|
| `Node` base class | `app/core/nodes/base.py` | Preserved |
| `NodeMetadata`, `InputPort`, `OutputPort`, `NodeConfig` | `app/core/nodes/` | Extended |
| `CompatibilityChecker` | `app/core/nodes/compat.py` | Preserved |
| AutoDiscovery registry | `app/core/nodes/discovery.py` | Preserved |
| `PipelineGraph`, `NodeExecutor` | `app/core/pipeline.py` | Extended |
| `run_pipeline()` | `app/core/pipeline.py` | Extended |
| YAML pipeline format | `pipeline.yaml` files | Demoted to shim |
| `Pipeline`, `PipelineNode` | `app/core/sdk.py` | Internals rewritten |
| REST API routers | `app/api/routers/` | Extended |
| CLI commands (`run`, `validate`, `runs`) | `app/cli/main.py` | Extended |
| `RunManager`, `PipelineLogger` | `app/core/` | Preserved |
| NDJSON event streaming | `app/core/logger.py` | Preserved |
| 441 passing tests | `tests/` | Must not regress |
