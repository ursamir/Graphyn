# Requirements — Provenance + Artifact System (Phase 4)

## Introduction

Phase 4 elevates artifacts and execution lineage to first-class platform entities. Phases 1–3 established the Graph IR, MCP layer, and advanced runtime (parallel execution, resumability, partial execution, conditional branching, event-driven execution, runtime control). Phase 4 builds directly on those foundations: the `GraphIR` stored in `{run_dir}/graph.json` (Phase 1, req-03 §3.6) becomes the reproducibility key, and `RunManager` evolves from a run-lifecycle manager into a full provenance layer.

The system must track what was produced (artifacts), how it was produced (provenance), and whether it can be reproduced (graph hash + input hashes). This is critical for ML workflows, agent memory, graph optimization, and deployment traceability.

**Regression constraint:** All 919 existing tests must continue to pass. No existing public API may be removed or have its signature changed in a breaking way.

## Glossary

- **Artifact** — A typed, versioned output produced by a node execution. May be an `AudioSample` list, `ModelArtifact`, `TFLiteArtifact`, `PredictionResult`, `FeatureArray`, or any future `PortDataType`.
- **ArtifactRecord** — The metadata envelope for a stored artifact: ID, content hash, type, run/node context, timestamps, and a pointer to the serialized data on disk.
- **ArtifactStore** — The content-addressed registry that stores and retrieves `ArtifactRecord` objects and their associated data files.
- **ProvenanceRecord** — A record linking an artifact to the exact run, node, graph, and input artifacts that produced it.
- **Lineage** — The full upstream dependency tree of an artifact: its `ProvenanceRecord` plus the `ProvenanceRecord` of every input artifact, recursively.
- **content_hash** — A SHA-256 digest of the canonical serialized form of an artifact's data. Two artifacts with identical `content_hash` values are considered identical.
- **graph_hash** — A SHA-256 digest of the canonical JSON serialization of a `GraphIR` (via `dump_ir()`). Two runs with the same `graph_hash` used the same graph structure.
- **ArtifactCollection** — The return type of `Pipeline.run()` in Phase 4. Wraps a list of `ArtifactRecord` objects and provides dict-like access for backward compatibility.
- **Replay** — Re-executing a pipeline using the `graph.json` stored from a prior run, producing a new run with fresh artifacts.
- **RunManager** — Existing class in `app/core/run_manager.py`. Phase 4 extends it with artifact registration and provenance summary methods.
- **Workspace** — The `workspace/` directory tree. Phase 4 adds `workspace/artifacts/` and `workspace/provenance/` subdirectories.

## Sub-Document Index

| File | Scope |
|---|---|
| `req-01-artifact-store.md` | `ArtifactStore`, `ArtifactRecord`, content-addressed storage, workspace layout |
| `req-02-provenance.md` | `ProvenanceRecord`, lineage tracking, reproducibility queries |
| `req-03-run-manager-evolution.md` | `RunManager` extensions: artifact registration, graph hash, provenance summary |
| `req-04-sdk-artifact-collection.md` | `ArtifactCollection`, `Pipeline.run()` return type, backward compatibility |
| `req-05-api-cli.md` | REST API `/api/v1/artifacts/`, CLI `audiobuilder artifacts` subcommand |
| `req-06-mcp-tools.md` | MCP provenance tools: `list_artifacts`, `get_artifact_lineage`, `replay_run` |
| `req-07-property-tests.md` | All 5 property-based test specifications |

## Cross-Phase Constraints

The following Phase 1–3 constraints are binding on Phase 4:

| Constraint | Origin | Phase 4 Impact |
|---|---|---|
| `GraphIR` stored per run in `graph.json` | Phase 1, req-03 §3.6 | `graph_hash` is computed from this file; it is the reproducibility key |
| IR is runtime-agnostic | Phase 1, req-01 §1.11 | `ArtifactStore` must not import from `pipeline.py` or node implementations |
| SDK is single source of truth | Phase 1, req-02 §2.9 | CLI and REST API must delegate artifact operations to `ArtifactStore` |
| `RunManager` owns run lifecycle | Phase 3 | Phase 4 extends `RunManager`; it does not replace it |
| 919 tests must not regress | Phase 1–3 | All new code is additive; no existing signatures change |
| `PipelineCache` uses SHA-256 content addressing | Phase 1 | `ArtifactStore` adopts the same pattern for consistency |
