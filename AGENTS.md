# Graphyn — Agent Guide

General-purpose AI/workflow execution platform (**graphyn-sdk**). Four interfaces share `app/core/`:

| Interface | Entry |
|---|---|
| REST API | `venv/bin/uvicorn app.api.main:app --reload --port 8001` → `/api/v1/` |
| Python SDK | `app/core/sdk.py` |
| CLI | `venv/bin/python -m app.cli.main` |
| MCP | `graphyn mcp` / `python -m app.mcp.server` |
| UI | `graphyn-ui/` — Vite React console (`npm run dev`) |

Canonical docs: `docs/README.md`. Start: `docs/GETTING_STARTED.md`. Architecture: `docs/ARCHITECTURE.md`. Kiro steering (detailed): `.kiro/steering/`.

**How to run:** Mode A (single machine, default local backend) vs Mode B
(`GRAPHYN_BACKEND=distributed` + workers). User steps in `docs/GETTING_STARTED.md`.
Contracts (IR `placement`, artifact URIs, worker CLI) in `docs/DISTRIBUTED_EXECUTION.md`.

## Vision

Build, run, and manage typed DAG pipelines — domain-agnostic via plugins (audio ML is a first-party pack, not the product identity). Graph IR (`.graph.json`) is the single pipeline language. Interfaces execute via `get_backend().execute(graph)`.


## Operating modes (read before starting processes)

| Mode | Env | Behavior |
|---|---|---|
| **A — Single machine** | leave GRAPHYN_BACKEND unset | LocalPythonBackend; one API host runs all nodes; install full plugin set here |
| **B — Multi machine** | GRAPHYN_BACKEND=distributed | Control plane schedules; workers use CLI worker start with control-url, labels, pool |

Capability models:
- **Full-capability host/worker** — Audio + Common installed; can execute advertised node types.
- **Specialized worker** — subset of plugins + labels/pools (gpu, gpu-lab); scheduler matches IR placement / capability.

User-facing steps: docs/GETTING_STARTED.md. Protocol details: docs/DISTRIBUTED_EXECUTION.md. Do not invent a third backend.

## Hard Rules

1. **Python via venv only:** `venv/bin/python`, `venv/bin/pip`, `venv/bin/pytest`, `venv/bin/uvicorn`.
2. **Platform never imports `app/domain/`.** Domain registers into platform registries at startup.
3. **Platform never imports `AudioSample` for storage.** Use `ArtifactSerializerRegistry`.
4. **Execution entry:** `get_backend().execute()` — not direct `orchestrator` calls from interfaces.
5. **`resolve_capability`** from `registry_runtime.py`, never from `orchestrator`.
6. **Plugins live in `PluginPackage/`.** Never edit `plugins/` (install target).
7. **YAML is deprecated.** Prefer `.graph.json`; migrate with `graphyn migrate`.
8. **After code changes:** update matching `.kiro/steering/` file and matching `docs/` file (see update protocol rule).
9. **`app/` modules:** keep the 7-field architectural contract docstring (see file-header rule).

## Layout

```
app/api/          FastAPI routers
app/cli/          argparse CLI
app/mcp/          MCP stdio server (29 tools)
app/core/         IR, nodes framework, orchestrator, plugins, artifacts,
                  distributed/, agentic/, trace, audit, experiments
app/domain/       Ingestion, ProjectManager, QualityChecker
app/models/       PortDataType implementations
PluginPackage/    Source plugins (Audio + Common; WakeWord/Video are experimental/non-manifest)
plugins/          Optional local override via GRAPHYN_PLUGINS_DIR (default install: ~/.graphyn/plugins/installed/)
graphyn-ui/       React + Vite console — Build/Observe/Library/Deploy/Admin IA
unit_test/        Pytest suite
examples/         End-to-end demos
docs/             Public docs (GETTING_STARTED, PRODUCT_VISION, architecture, refs)
.kiro/steering/   Detailed agent steering by area
```

## Bounded Contexts (BC)

| BC | Name | Location |
|---|---|---|
| BC1 | Graph Language | `app/core/ir/` |
| BC2 | Node Contract | `app/core/nodes/{base,ports,config,retry,metadata}.py` |
| BC3 | Node Catalog | `registry`, `discovery`, `app/core/plugins/` |
| BC4 | Execution Planner | `planner.py` |
| BC5 | Execution Runtime | `orchestrator`, `node_executor`, `executor`, `conditions`, `events` |
| BC6 | Observability & Storage | `checkpoint`, `artifact_*`, `run_*`, `provenance`, `pipeline_cache`, `logger` |


## Dependencies (authoritative model)

- **Source of truth:** `setup.py` (`install_requires` + `extras_require`).
- **Deploy pins:** `requirements.txt` (must cover every `install_requires` name).
- **Validate:** `venv/bin/python scripts/check_deps.py` (optional `--inventory`).
- **Clean install:** `venv/bin/pip install -e ".[dev]"` then import `app` / `pytest`.
- **Extras:** `mcp`, `redis`, `events` (watchfiles), `vad` (webrtcvad), `hf`, `tf`, `dev`, `all`.
- **Do not** add a runtime import under `app/` without declaring it in `setup.py`.
- **CI smoke:** `scripts/ci_smoke.sh` (+ `scripts/ui_build.sh` for the console). A GitHub Actions workflow can wrap these when the push credential has `workflow` scope.

## Quick Commands

Mode A: start API without GRAPHYN_BACKEND; run UI; run graphs via CLI (see docs/GETTING_STARTED.md).

Mode B: set GRAPHYN_BACKEND=distributed on the control plane; on workers run worker start with --control-url / --labels / --pool.

Tests: venv/bin/pytest unit_test/  (or GRAPHYN_SKIP_PLUGIN_LOAD=1 for faster isolation).

## Security notes (plugins)

`GRAPHYN_PLUGIN_ALLOWED_SOURCES` uses structural URL matching (host + path-segment boundary), not `str.startswith`. Redirect downloads re-validate every hop fail-closed.
