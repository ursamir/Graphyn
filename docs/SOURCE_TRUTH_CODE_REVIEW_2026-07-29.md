# Source-Truth Code Review (2026-07-29)

This report documents the project-wide code review performed with source code as the authority (not docs). It aggregates direct inspection across backend, plugins, frontend, and tests.

## Scope Reviewed

- `app/core`, `app/api`, `app/mcp`, `app/cli`, `app/domain`, `app/models`
- `PluginPackage/Audio`
- `PluginPackage/Common`, `PluginPackage/WakeWord`, `PluginPackage/Video`
- `audiobuilder/src`
- `unit_test`

## Review Method

- Defect-first static code review with priority levels (`P0`, `P1`, `P2`).
- Focus on correctness, security, contract drift, concurrency risks, and test blind spots.
- Cross-checks between frontend contracts and backend route/schema behavior.
- No dependency on documentation claims.

## Findings Summary

- **P0:** frontend-backend contract breaks core UX; WakeWord package/runtime structure broken for plugin usage.
- **P1:** auth/path-security issues, plugin interoperability defects, and multiple API/FE contract mismatches.
- **P2:** runtime observability/concurrency correctness issues and meaningful test coverage gaps.

## Detailed Findings

### P0 — Critical

1. **Frontend default API contract is broken out-of-the-box**
   - Files: `audiobuilder/src/utils/api.ts`, `audiobuilder/src/App.tsx`, `audiobuilder/src/flow/*`, `audiobuilder/src/features/*`
   - Issues:
     - Default API base path omits `/api/v1`.
     - Run endpoint mismatch (`/run-stream` vs backend `/api/v1/pipelines/run`).
     - Template save/load format mismatch (YAML assumptions vs backend graph/IR payloads).
   - Impact: core execution/template workflows fail.

2. **WakeWord package is not plugin-loadable and has import-path breakage**
   - Files: `PluginPackage/WakeWord/__init__.py`, `PluginPackage/WakeWord/cli.py`, `PluginPackage/WakeWord/training/trainer.py`, `PluginPackage/WakeWord/inference/model.py`
   - Issues:
     - Imports reference module paths that do not exist in current tree.
     - No `plugin.toml`/manifest-compatible plugin structure.
   - Impact: runtime import failures; cannot load as Graphyn plugin package.

### P1 — High

1. **Auth bypass for mounted static routes**
   - File: `app/api/main.py`
   - Issue: `/files`, `/input-files`, `/run-files` mounts are outside API dependency auth path.
   - Impact: artifact/file exposure even when token auth is configured.

2. **Path traversal risks in filesystem-backed handlers**
   - Files: `app/mcp/handlers/artifacts.py`, `app/domain/project_manager.py`, `app/api/routers/projects.py`, `app/api/routers/data.py`
   - Issue: incomplete normalization/containment checks for user-controlled path fragments (`run_id`, `version`, source project/version paths).
   - Impact: possible reads/copies outside intended workspace roots.

3. **Common plugin PyTorch artifact interoperability is inconsistent**
   - Files: `PluginPackage/Common/trainer/nodes.py`, `PluginPackage/Common/evaluator/nodes.py`, `PluginPackage/Common/realtime_inference/nodes.py`, `PluginPackage/Common/edge_optimizer/nodes.py`
   - Issue: produced artifact shape (state dict) conflicts with downstream loader/inference/export expectations.
   - Impact: advertised train→evaluate/infer/export flow breaks for PyTorch paths.

4. **Audio quality gate crash path on malformed sample payloads**
   - File: `PluginPackage/Audio/audio_quality_gate/nodes.py`
   - Issue: checks continue into `np.abs(sample.data)`/power ops without sufficient `None`/empty guard enforcement.
   - Impact: hard crashes instead of controlled reject behavior.

5. **Frontend request/response mismatches across project features**
   - Files: `audiobuilder/src/BaseNode.tsx`, `audiobuilder/src/features/projects/ProjectList.tsx`, `audiobuilder/src/features/datasets/DatasetRegistry.tsx`, `audiobuilder/src/features/annotation/*`
   - Issue: endpoint names, payload fields, and response assumptions diverge from backend routers.
   - Impact: validation, project operations, merges, and annotation/dataset flows fail or degrade.

### P2 — Medium

1. **Event-driven execution exception visibility gap**
   - File: `app/core/orchestrator.py`
   - Issue: exception handling around gathered event tasks can mask true failure state.

2. **Parallel output count observability mismatch**
   - File: `app/core/executor.py`
   - Issue: output counting logic differs from sequential semantics.

3. **Replay queue shared-state concurrency risk**
   - File: `app/api/routers/artifacts.py`
   - Issue: global replay future list handling is not guarded for concurrent request mutation.

4. **Run-control multi-worker API contract ambiguity**
   - Files: `app/api/routers/run_control.py`, `app/core/run_control.py`
   - Issue: “active on another worker” path can surface as plain not-found semantics.

5. **Additional plugin/runtime quality defects**
   - Files: `PluginPackage/Audio/stream_processor/nodes.py`, `PluginPackage/Audio/stream_ingest/nodes.py`, `PluginPackage/Audio/environment_simulator/nodes.py`, `PluginPackage/Common/multimodal_fusion/nodes.py`
   - Issues: missing-data crash paths, potentially invalid external API usage, deterministic metadata mismatch.

6. **Test blind spots**
   - File examples: `unit_test/core/test_pipeline_integration.py` and broader `unit_test/core/*`
   - Issues: parallel mode case not truly exercised in one integration test, resume/control lifecycle coverage gaps, and many behavior assertions are too shallow.

## Recommended Fix Order

### P0 (blockers)
- Align frontend API base + endpoints + payload schemas with backend.
- Decide WakeWord status:
  - make it a true Graphyn plugin package (manifest + node contract), or
  - explicitly mark/remove it from plugin claims.

### P1
- Enforce auth on static file serving paths.
- Add centralized path containment validation for all filesystem-bound route inputs.
- Repair Common PyTorch artifact contracts and downstream compatibility.
- Fix frontend request contract drift and checkpoint/template schema handling.

### P2
- Harden event-driven error reporting and replay queue concurrency.
- Unify output metric counting semantics in parallel execution.
- Expand run-control distributed behavior signaling.
- Add focused regression tests for traversal/auth/parallel/resume.

## Artifacts

- Canvas snapshot committed in repo: `docs/graphyn-customer-architecture-review.canvas.tsx`
- Related operational issue list: `docs/KNOWN_ISSUES.md`
