# Platform Build Handoff — Graphyn Pipeline Engine

> **Purpose:** Session continuity document. Start the next session by reading
> this file. It contains everything needed to continue building the platform
> without re-reading the full codebase.
>
> **Project root:** `/home/meritech/Desktop/newAudio3`
> **Run commands:** `venv/bin/python`, `venv/bin/pytest`, `venv/bin/uvicorn`

---

## 1. What This System Is

Graphyn is a **general-purpose AI/workflow execution platform** — not an audio
tool. Audio is one domain running on it. The platform would be identical if the
domain were video, finance, or documents. This distinction drives every
architectural decision going forward.

**Four interfaces share one execution engine:**

| Interface | Entry Point |
|---|---|
| REST API | `app/api/main.py` → `http://localhost:8001/api/v1/` |
| Python SDK | `app/core/sdk.py` → `Pipeline`, `PipelineNode` |
| CLI | `app/cli/main.py` |
| MCP Server | `app/mcp/server.py` (stdio JSON-RPC) |

**All 29 production nodes live in `PluginPackage/`** as manifest-based plugin
packages. The engine is domain-agnostic — it knows nothing about audio.

---

## 2. What Was Done This Session

### Phase 1 — Deep Analysis (complete)

Three documents were produced and are the source of truth for all future work:

| Document | Location | Purpose |
|---|---|---|
| Deep Technical Review | `docs/DEEP_TECH_REVIEW.md` | 25 bugs, security issues, performance bottlenecks, scalability limits — all with root cause and impact |
| System Design | `docs/SYSTEM_DESIGN.md` | Complete layer-by-layer breakdown of every module, data flows, architectural patterns, extension points, known inconsistencies |
| Responsibility Analysis | (in conversation) | Bounded context discovery — identified 18 platform capabilities, 6 true bounded contexts, stability classifications, dependency direction violations |

### Phase 2 — Critical Bug Fixes (complete)

All 9 tasks in `.kiro/specs/platform-critical-fixes/tasks.md` are checked off.

**Five bugs fixed:**

| Bug | File(s) Changed | What Was Fixed |
|---|---|---|
| Duplicate `run_pipeline_ir_async` | `pipeline.py` | Deleted dead first definition — was silently shadowed |
| Dual `run_id` | `pipeline.py` | `run_id = str(uuid.uuid4())` → `run_id = run.run_id` — observer events now match persisted run metadata |
| `ResumeError` circular import | `errors.py`, `pipeline.py`, `run_manager.py` | Moved `ResumeError` to `nodes/errors.py`, replaced deferred imports with top-level import |
| `_infer_artifact_type` in wrong layer | `artifact_store.py`, `pipeline.py`, `executor.py` | Moved domain function to `artifact_store.py` where it belongs |
| `Pipeline.validate()` broken | `sdk.py` | Added missing `registry` argument — method was always raising `TypeError` |

---

## 3. The Platform Build Plan

The goal is to transform this from a monolithic codebase into a platform with
clean bounded contexts that can support independent teams, package extraction,
and semantic versioning.

### The Correct Bounded Contexts (discovered from code analysis)

Six bounded contexts were identified. Each has a single reason to change:

```
┌─────────────────────────────────────────────────────────────────────┐
│  BC1: GRAPH LANGUAGE          (app/core/ir/)                        │
│  "What is a valid graph?"                                           │
│  Stability: VERY STABLE — ready for package extraction NOW          │
│  Dependencies: none (stdlib + pydantic only)                        │
├─────────────────────────────────────────────────────────────────────┤
│  BC2: NODE CONTRACT           (app/core/nodes/base.py, ports.py,    │
│                                config.py, retry.py)                 │
│  "What is a node? What can flow between nodes?"                     │
│  Stability: VERY STABLE — ready for extraction after BC1            │
│  Dependencies: BC1 only                                             │
├─────────────────────────────────────────────────────────────────────┤
│  BC3: NODE CATALOG            (app/core/nodes/registry.py,          │
│                                discovery.py, metadata.py)           │
│  "What nodes are available and what can they do?"                   │
│  Stability: EVOLVING — capability fields still growing              │
│  Dependencies: BC1, BC2                                             │
├─────────────────────────────────────────────────────────────────────┤
│  BC4: EXECUTION PLANNER       (PipelineGraph, topo sort, waves —    │
│                                currently inside pipeline.py)        │
│  "In what order should nodes execute?"                              │
│  Stability: STABLE — needs extraction from pipeline.py first        │
│  Dependencies: BC1, BC2, BC3                                        │
├─────────────────────────────────────────────────────────────────────┤
│  BC5: EXECUTION RUNTIME       (run_pipeline_ir_async, NodeExecutor, │
│                                conditions, events, cache —          │
│                                currently inside pipeline.py)        │
│  "How does a node execute and how is a run orchestrated?"           │
│  Stability: EVOLVING — new runtime features land here               │
│  Dependencies: BC1, BC2, BC3, BC4                                   │
├─────────────────────────────────────────────────────────────────────┤
│  BC6: OBSERVABILITY & STORAGE (run_manager.py, logger.py,           │
│                                artifact_store.py, provenance.py)   │
│  "What happened during a run and where are the outputs?"            │
│  Stability: STABLE (storage) / EVOLVING (control plane)             │
│  Dependencies: BC1 only                                             │
└─────────────────────────────────────────────────────────────────────┘
```

### The Stabilization Roadmap

**Step 1 — Separate domain from platform** (next priority)

Three files in `app/core/` are domain services, not platform services. They
know about audio, HuggingFace, and ML projects. Move them:

```
app/core/ingestion.py        → app/domain/ingestion.py
app/core/project_manager.py  → app/domain/project_manager.py
app/core/quality_checker.py  → app/domain/quality_checker.py
```

Then fix the two domain leaks in platform infrastructure:

- `pipeline_cache.py` imports `AudioSample` directly — replace with a pluggable
  serializer/hasher strategy
- `artifact_store.py` contains `_serialize_audio_samples()` with WAV writing —
  replace with a serializer registry that the domain registers into at startup

**Step 2 — Split `pipeline.py` into its true responsibilities**

`pipeline.py` is 1,510 lines containing 5 distinct responsibilities:

```
app/core/pipeline.py → split into:

app/core/planner.py          (PipelineGraph, topo sort, waves, _ir_to_pipeline_config)
app/core/node_executor.py    (NodeExecutor)
app/core/checkpoint.py       (_write_checkpoint, _load_checkpoint_outputs)
app/core/orchestrator.py     (run_pipeline_ir_async, run_pipeline_ir)
app/core/pipeline.py         (kept as re-export shim for backward compat)
```

**Step 3 — Split `run_manager.py` into its true responsibilities**

`run_manager.py` mixes three things with different futures:

```
app/core/run_manager.py → split into:

app/core/run_journal.py      (persistence: save_graph_ir, save_metadata, save_logs,
                              mark_failed, mark_cancelled, _write_meta)
app/core/run_control.py      (control plane: _ACTIVE_RUNS, register_active_run,
                              get_active_run, pause/resume/cancel)
app/core/run_manager.py      (kept as re-export shim for backward compat)
```

`run_control.py` is the module that needs to become distributed (Redis-backed)
for multi-worker deployments. `run_journal.py` stays as a filesystem writer.

**Step 4 — Fix the two hardcoded workspace paths**

```python
# app/api/routers/system.py — WRONG:
WORKSPACE_ROOT = Path("workspace").resolve()

# app/api/routers/pipelines.py — WRONG:
TEMPLATES_DIR = Path("workspace/configs/templates")

# Both should use:
from app.core.config import project_dir, runs_dir, cache_dir
```

**Step 5 — Write scoped steering files for ownership**

After Steps 1–4, create `.kiro/steering/` files for each bounded context so
that a person or agent working on one module only sees what they need.

### Package Extraction (after stabilization)

Only two bounded contexts are ready for package extraction now:

- `app/core/ir/` → `graphyn-graph-language` package (zero internal deps, stable)
- `app/core/nodes/base.py + ports.py + config.py + retry.py` → `graphyn-node-contract`

Everything else needs Steps 1–4 to complete first. Extracting packages before
stabilization locks in the current mixed responsibilities.

---

## 4. Remaining Known Issues (from Deep Tech Review)

These are not yet fixed. Prioritize in this order:

### Security (fix before any production deployment)

| Issue | File | Fix |
|---|---|---|
| Auth token read at import time | `app/mcp/auth.py` line 12, `app/api/main.py` line 30 | Read token inside `check_auth()` / `_auth_dep()` on every call |
| Webhook SSRF — no private IP blocking | `app/core/webhook.py` | Reject RFC 1918 / loopback addresses in `save()` |
| Ingest URL — no download size limit | `app/core/ingestion.py` | Use `httpx` streaming with max byte counter |
| CORS `allow_headers=["*"]` with credentials | `app/api/main.py` | Enumerate specific headers |

### Architecture (fix as part of platform build)

| Issue | File | Fix |
|---|---|---|
| `TEMPLATES_DIR` hardcoded relative path | `app/api/routers/pipelines.py` | Use `project_dir() / "configs" / "templates"` |
| `system.py` cleanup uses hardcoded `Path("workspace")` | `app/api/routers/system.py` | Use `runs_dir()`, `cache_dir()` from config |
| Observer events fire twice per node | `app/core/pipeline.py` `NodeExecutor` | Remove direct observer calls from executor (node lifecycle hooks already call them) |
| Checkpoint only saves first list port | `app/core/pipeline.py` `_write_checkpoint` | Iterate all ports, not just first list |
| Graph hash computed twice per run | `app/core/pipeline.py` | Use `run._graph_hash` after `save_graph_ir()` |
| `ArtifactStore` serialization inside global lock | `app/core/artifact_store.py` | Serialize outside lock, hold lock only for index update |
| Unbounded streaming queue | `app/api/routers/pipelines.py` | Use `Queue(maxsize=N)` |

### Code Quality (fix when touching the relevant file)

| Issue | File | Fix |
|---|---|---|
| `PipelineNode._ir_node` always `_0` suffix | `app/core/sdk.py` | Use `to_ir_node(node_index)` result |
| `AudioClassifierNode` input port `data_type=list` | `PluginPackage/Audio/audio_classifier/nodes.py` | Use `list[AudioSample] \| list[FeatureArray]` |
| `TrainerNode` / `ModelBuilderNode` `data_type=object` | `PluginPackage/Common/trainer/nodes.py` | Define proper typed ports |
| `document_processor` plugin directory empty | `PluginPackage/Audio/document_processor/` | Implement or remove |
| `audio_exporter` missing `__init__.py` | `PluginPackage/Audio/audio_exporter/` | Add `__init__.py` |
| `asyncio.get_event_loop()` deprecated | `app/mcp/server.py` | Use `asyncio.get_running_loop()` |
| `WebhookService` missing `__init__` | `app/core/webhook.py` | Add `__init__` with `self._config_cache = None` |
| `setup.py` open version ranges | `setup.py` | Pin to match `requirements.txt` |

---

## 5. Key Files to Know

| File | What It Does | Stability |
|---|---|---|
| `app/core/ir/models.py` | GraphIR Pydantic models — the graph language | VERY STABLE |
| `app/core/ir/loader.py` | load_ir, dump_ir, version checking | VERY STABLE |
| `app/core/nodes/base.py` | Node base class, SISO wrapper, lifecycle hooks | VERY STABLE |
| `app/core/nodes/registry.py` | Thread-safe singleton node registry | STABLE |
| `app/core/nodes/discovery.py` | AutoDiscovery — scans dirs, registers nodes | STABLE |
| `app/core/pipeline.py` | God module — DAG builder + executor + orchestrator | EVOLVING (being split) |
| `app/core/run_manager.py` | Run lifecycle + control plane + artifact facade | EVOLVING (being split) |
| `app/core/artifact_store.py` | Content-addressed artifact storage | STABLE (after domain leak removed) |
| `app/core/provenance.py` | Lineage tracking — clean, no domain knowledge | STABLE |
| `app/core/sdk.py` | Composition root — wires all services for one execution | EVOLVING |
| `app/core/config.py` | All env vars and path resolution — zero internal deps | VERY STABLE |
| `app/core/plugins/manager.py` | Plugin install/uninstall/enable/disable | STABLE |
| `PluginPackage/` | 29 domain nodes — consumers of the platform | EVOLVING |

---

## 6. What to Do Next Session

**Recommended starting point:** Step 1 of the stabilization roadmap —
separate domain from platform.

Start by creating the spec:

```
Feature name: domain-platform-separation
Type: refactor
Scope:
  - Move app/core/ingestion.py → app/domain/ingestion.py
  - Move app/core/project_manager.py → app/domain/project_manager.py
  - Move app/core/quality_checker.py → app/domain/quality_checker.py
  - Remove AudioSample import from pipeline_cache.py (pluggable hasher)
  - Remove _serialize_audio_samples from artifact_store.py (serializer registry)
  - Fix two hardcoded Path("workspace") in system.py and pipelines.py
```

This is the highest-leverage change because it makes the platform genuinely
domain-agnostic, which is the prerequisite for everything else.

---

## 7. Architecture Decision Log

| Decision | Rationale |
|---|---|
| Keep monorepo, no microservices | Coupling is too tight for service extraction now; stabilize first |
| Bounded contexts before packages | Package extraction before stable contracts locks in current mixed responsibilities |
| `ResumeError` in `nodes/errors.py` | Subclasses `RuntimeError` not `NodeSystemError` — it's a runtime error, not a structural one |
| `_infer_artifact_type` in `artifact_store.py` | Domain type inference belongs with the artifact system, not the orchestration loop |
| Pluggable serializer for `artifact_store` | Platform must not know about WAV format — domain registers its serializer at startup |
| `run_control.py` separate from `run_journal.py` | Control plane needs to become distributed; persistence stays filesystem-based |
