# Graphyn — Agent Guide

General-purpose AI/workflow execution platform (**graphyn-sdk**). Four interfaces share `app/core/`:

| Interface | Entry |
|---|---|
| REST API | `venv/bin/uvicorn app.api.main:app --reload --port 8001` → `/api/v1/` |
| Python SDK | `app/core/sdk.py` |
| CLI | `venv/bin/python -m app.cli.main` |
| MCP | `graphyn mcp` / `python -m app.mcp.server` |
| UI | `graphyn-ui/` — Vite React console (`npm run dev`) |

**Docker UI-only deploy:** never recreate `graphyn-api` for frontend changes — API plugin boot can take **15+ minutes**. Use `docker compose build graphyn-ui && docker compose up -d --no-deps graphyn-ui` (or `npm run dev` against a running API).

Canonical docs: `docs/README.md`. Start: `docs/GETTING_STARTED.md`. Architecture: `docs/ARCHITECTURE.md`. Kiro steering: `.kiro/steering/frontend-*.md` only (backend steering removed in `6f0cd7f`; `docs/` is canonical).

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
- **Full-capability host/worker** — all bundled packs installed; can execute advertised node types.
- **Specialized worker** — subset of plugins + labels/pools (gpu, gpu-lab); scheduler matches IR placement / capability.

User-facing steps: docs/GETTING_STARTED.md. Protocol details: docs/DISTRIBUTED_EXECUTION.md. Do not invent a third backend.

## Hard Rules

1. **Python via venv only:** `venv/bin/python`, `venv/bin/pip`, `venv/bin/pytest`, `venv/bin/uvicorn`.
2. **Platform never imports `app/domain/`.** Domain registers into platform registries at startup.
3. **Platform never imports `AudioSample` for storage.** Use `ArtifactSerializerRegistry`.
4. **Execution entry:** `get_backend().execute()` — not direct `orchestrator` calls from interfaces.
5. **`resolve_capability`** from `app.core.host.registry_runtime`, never from `orchestrator`.
6. **Plugins live in `PluginPackage/`.** Never edit `plugins/` (install target).
7. **YAML is deprecated.** Prefer `.graph.json`; migrate with `graphyn migrate`.
8. **After code changes:** update the matching `docs/` file (code-area → doc table in `.cursor/rules/update-protocol.mdc`), plus `.kiro/steering/frontend-{canvas,features}.md` for `graphyn-ui/` changes. `.kiro/steering/` is **tracked** (`.gitignore` excludes `.kiro/*` but un-ignores `.kiro/steering/**`).
9. **`app/` modules:** keep the 7-field architectural contract docstring (see file-header rule).

## Layout

```
app/api/          FastAPI routers
app/cli/          argparse CLI (`main.py` dispatch; `cmd_*.py` per command group)
app/mcp/          MCP stdio server (77 tools; +`accept_proposal` when GRAPHYN_MCP_HUMAN_APPROVAL=1 — 78 `register("` calls in `app/mcp/tool_registry.py`)
app/core/         Kernel (config, errors, logger, sdk) plus packages:
                  ir/, nodes/, plugins/, execution/, runs/, artifacts/,
                  notify/, persist/, paths/, trust/, templates/, pipelines/,
                  mlops/, ml/, host/, distributed/, agentic/, credentials/
app/domain/       Ingestion, ProjectManager, QualityChecker
app/models/       PortDataType implementations
PluginPackage/    Source plugins — 9 packs / 156 plugin.toml: Agents, Audio, Common, MLOps, RAG,
                  TinyML, Vision; Video + WakeWord experimental (WakeWord partly without
                  manifests). Every PluginPackage/*/*/plugin.toml is auto-installed at startup.
plugins/          Optional local override via GRAPHYN_PLUGINS_DIR (default install: ~/.graphyn/plugins/installed/)
graphyn-ui/       React + Vite console — Build/Observe/Library/Deploy/Admin IA
unit_test/        Pytest suite
examples/         End-to-end demos
docs/             Public docs (GETTING_STARTED, PRODUCT_VISION, architecture, refs)
.kiro/steering/   Frontend steering (frontend-canvas.md, frontend-features.md)
```

## Bounded Contexts (BC)

| BC | Name | Location |
|---|---|---|
| BC1 | Graph Language | `app/core/ir/` |
| BC2 | Node Contract | `app/core/nodes/{base,ports,config,retry,metadata}.py` |
| BC3 | Node Catalog | `registry`, `discovery`, `app/core/plugins/` |
| BC4 | Execution Planner | `app/core/execution/planner.py` |
| BC5 | Execution Runtime | `app/core/execution/` (`orchestrator`, `node_executor`, `executor`, `conditions`, `events`) |
| BC6 | Observability & Storage | `app/core/runs/`, `app/core/artifacts/`, `app/core/notify/`, `logger.py` |


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
