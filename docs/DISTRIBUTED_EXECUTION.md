# Distributed Execution

> Source of truth for multi-machine Graphyn orchestration.  
> Complements [ARCHITECTURE.md](./ARCHITECTURE.md) and [PIPELINE_EXECUTION.md](./PIPELINE_EXECUTION.md).  
> Status: **implementing** (P0–P2 operable; P3 scale later).

---

## 1. Goal

Run one GraphIR pipeline across **two or more physical machines**, placing each node on an appropriate worker (e.g. GPU trainer on Server-99, light nodes on a laptop/API host).

**Non-goals for P0–P1**
- Kubernetes autoscaling / multi-tenant SaaS
- Replacing `LocalPythonBackend` for single-machine runs
- Using Redis as a blob store for audio/models

---

## 2. Target topology

```
┌──────────────────────────── Control plane ────────────────────────────┐
│  UI / API / SDK / CLI / MCP                                           │
│           │                                                           │
│           ▼                                                           │
│  get_backend() → DistributedBackend | LocalPythonBackend              │
│           │                                                           │
│           ▼                                                           │
│  Planner (topo + waves) → Scheduler (placement) → Job queue           │
│           │                        ▲                                  │
│           │                        │ heartbeats / claim / events      │
│           ▼                        │                                  │
│  Run journal + log aggregator  Worker registry                        │
│           │                                                           │
│           ▼                                                           │
│  Artifact store client  ──URI──►  shared object store / NFS / local   │
└───────────────────────────────────────────────────────────────────────┘
                    │                          │
                    ▼                          ▼
            ┌──────────────┐           ┌──────────────┐
            │ Worker A     │           │ Worker B     │
            │ graphyn      │           │ graphyn      │
            │   worker     │           │   worker     │
            │ plugins+venv │           │ GPU + TF     │
            │ NodeExecutor │           │ NodeExecutor │
            └──────────────┘           └──────────────┘
```

- **Control plane** plans and schedules; may also run a local worker for CPU/light nodes.
- **Workers** advertise capabilities, claim jobs, execute nodes, upload output artifacts, stream events.
- **Data plane** crosses machines only via **artifact URIs**, never via live Python objects or host-local absolute paths.

---

## 3. Contracts

### 3.1 Graph IR — placement (`IRNode.placement`)

Optional on each node (schema 1.2+; omitted → auto):

```json
{
  "id": "trainer_0",
  "node_type": "trainer",
  "config": {},
  "placement": {
    "mode": "auto",
    "worker": null,
    "pool": null,
    "tags": ["gpu"],
    "require_gpu": true,
    "min_vram_mib": 4096
  }
}
```

| Field | Meaning |
|---|---|
| `mode` | `auto` \| `local` \| `worker` \| `pool` |
| `worker` | Exact worker id when `mode=worker` |
| `pool` | Logical pool name (e.g. `gpu-lab`) |
| `tags` | Soft/hard label match (`gpu`, `edge`, `cpu`) |
| `require_gpu` | Hard constraint (also inferred from capability metadata) |
| `min_vram_mib` | Hard VRAM floor |

**Resolution order:** explicit `worker` → `pool` → tags + capability → least-loaded eligible worker → fail closed if none.

Capability metadata (`requires_gpu`, `supports_edge`, …) remains the **default hint** when `placement` is absent.

### 3.2 Artifact URI

Anything that crosses a machine boundary is referenced as:

```
artifact://{store}/{key}
```

Examples:
- `artifact://local/sha256/ab/cd/abcdef…`
- `artifact://file/workspace/artifacts/models/run123/model.keras` (single-host / NFS)
- `artifact://s3/bucket/key` (future)

Control and workers resolve URIs through `ArtifactStore` / store drivers. Port payloads are serialized with `ArtifactSerializerRegistry` before upload.

### 3.3 Job protocol

A **node job** is the unit of remote work (extends today’s isolated plugin job JSON):

```json
{
  "job_id": "uuid",
  "run_id": "…",
  "node_id": "trainer_0",
  "node_type": "trainer",
  "config": {},
  "seed": 42,
  "input_refs": { "model": "artifact://…", "dataset": "artifact://…" },
  "placement": { "tags": ["gpu"] },
  "timeout_s": 3600,
  "created_at": "ISO-8601"
}
```

**Result:**

```json
{
  "job_id": "uuid",
  "status": "succeeded",
  "output_refs": { "output": "artifact://…" },
  "events": [],
  "error": null,
  "worker_id": "server99-gpu",
  "duration_s": 98.2
}
```

IPC evolution: isolated `pickle` files stay for **same-machine** isolated plugins; remote jobs use **URI refs + store download/upload**.

### 3.4 Worker registration

```json
{
  "worker_id": "server99-gpu",
  "labels": ["gpu", "lab"],
  "pools": ["gpu-lab"],
  "resources": {
    "gpu": true,
    "gpu_name": "NVIDIA GeForce RTX 5070 Ti",
    "vram_mib_total": 16311,
    "vram_mib_free": 8000,
    "cpus": 16
  },
  "plugins": ["trainer", "evaluator", "model_builder"],
  "graphyn_version": "…",
  "heartbeat_at": "ISO-8601",
  "status": "idle"
}
```

Heartbeats every ~15s; stale after ~45s → scheduler skips worker.

---

## 4. Runtime backends

| Backend id | When |
|---|---|
| `local_python` | Default; current behavior (unchanged) |
| `distributed` | `GRAPHYN_BACKEND=distributed` or explicit `register_backend` |

`DistributedBackend.execute()`:
1. Build waves from GraphIR edges (`compute_ir_waves` — same level algorithm as `PipelineGraph`, no node instantiation required for remote types)
2. For each node in wave order: resolve placement → if local, run `NodeExecutor`; else enqueue job and wait
3. Materialize inputs: pickle+recast → `put_blob` → `input_refs` (see `app/core/distributed/transfer.py`)
4. On completion: hydrate `output_refs` → in-memory port values for downstream **on the control plane** (always hydrate in P1)
5. All-local graphs short-circuit to `LocalPythonBackend` unchanged
6. P1 supports **unconditional** edges only; conditional edges are skipped with a warning

---

## 5. Control-plane APIs

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/workers/register` | Register / refresh worker |
| `POST` | `/api/v1/workers/{id}/heartbeat` | Heartbeat + resource snapshot |
| `GET` | `/api/v1/workers` | List workers |
| `DELETE` | `/api/v1/workers/{id}` | Deregister |
| `POST` | `/api/v1/jobs/claim` | Worker claims next eligible job |
| `POST` | `/api/v1/jobs/{id}/complete` | Report result |
| `POST` | `/api/v1/jobs/{id}/events` | Stream/batch log events |
| `POST` | `/api/v1/jobs/{id}/cancel` | Control → worker cancel signal |

Auth: same Bearer `GRAPHYN_API_TOKEN` as today (worker presents token).

---

## 6. CLI

```bash
# Control plane (existing)
graphyn run --graph pipeline.graph.json

# Worker (new)
graphyn worker start \
  --control-url http://control:8001/api/v1 \
  --worker-id server99-gpu \
  --labels gpu,lab \
  --pool gpu-lab
```

Env:
- `GRAPHYN_BACKEND=distributed`
- `GRAPHYN_CONTROL_URL=…`
- `GRAPHYN_WORKER_ID=…`
- `GRAPHYN_ARTIFACT_STORE=local|file|s3` (P1+)
- `GRAPHYN_API_TOKEN=…`

---

## 7. Shared storage profiles

| Profile | Use |
|---|---|
| `local` | Single host; URIs map under `workspace/artifacts` (dev) |
| `file` / NFS | Two boxes sharing a mount (LAN MVP) |
| `s3` / MinIO | Decoupled object store (preferred beyond lab) |

P1 two-box path on Server-99: NFS **or** MinIO; default implementation starts with **content-addressed local store + HTTP artifact fetch/put** through the control API so boxes need not share a filesystem.

---

## 8. Failure, cancel, resume

- Job lease with TTL; worker heartbeat renews lease; expired lease → requeue (at-most-once → at-least-once with idempotent artifact keys)
- Cancel: control sets job cancelled; worker polls or receives pub/sub and stops `NodeExecutor` / subprocess
- Checkpoints: write checkpoint blobs to artifact store so resume can continue on another worker (P3)
- Isolated plugin timeouts stay via `GRAPHYN_PLUGIN_ISOLATED_TIMEOUT`
- **P2 durable store:** registry + queue persist under `workspace/distributed/*.json` by default (or Redis when `GRAPHYN_REDIS_URL` is set). In-memory remains the fast path; `GRAPHYN_DISTRIBUTED_STORE=memory` disables durability (tests).
- **P2 cancel → worker:** `POST /jobs/{id}/cancel` marks the job cancelled; claiming workers poll status (CLI / loopback) and stop before/after execute. Heartbeats renew leases; expired leases reclaim to `pending`.

---

## 9. UI (P2)

- **Workers** page under Admin (`#/workers`): id, status, labels/pools, GPU/VRAM, last heartbeat, **stale** badge (>45s)
- Run detail: per-node placement map from `meta.distributed_node_workers` (written by `DistributedBackend` when `run_manager` is available)
- Builder: optional placement chip on selected node (stretch / P3)

---

## 10. Phased delivery

### P0 — Contract (this milestone)
- [x] This design doc
- [x] `IRPlacement` on `IRNode`; IR 1.2 loader accepts 1.1 graphs
- [x] `artifact_uri` helpers + local store keying
- [x] Job / worker / result Pydantic models
- [x] `DistributedBackend` skeleton (falls back to local when no remote workers)
- [x] In-memory worker registry + job queue (process-local)
- [x] API router `/workers`, `/jobs`
- [x] `graphyn worker` CLI skeleton (register + heartbeat loop)
- [x] Unit tests for placement resolution + URI + IR round-trip

### P1 — Two-box MVP
- [x] HTTP artifact put/get through control API
- [x] Real claim/complete loop; remote `NodeExecutor` on worker with artifact URI hydrate/upload
- [x] Scheduler uses tags + `requires_gpu`
- [x] Wave scheduler: local via `NodeExecutor`, remote via job queue + `input_refs`/`output_refs` (no full-graph local rematerialize)
- [x] Example: pin `trainer`/`evaluator` to GPU worker; rest local (`examples/29_distributed_placement/`)
- [x] Document Server-99 + second host runbook (below)

### P2 — Operable
- [x] Persistent registry (Redis or disk) for multi-API-worker control
- [x] Cancel to worker; lease reclaim
- [x] UI Workers + run placement column
- [x] Plugin list advertised; refuse job if node_type missing

### P3 — Scale (later)
- [ ] K8s backend implementing same job protocol
- [ ] Autoscaling pools; OTel spans per job

---

## 11. Mapping to existing code

| Existing | Role in distributed |
|---|---|
| `runtime_backend.py` | Register `DistributedBackend` |
| `planner.py` / waves | Unchanged planning |
| `isolated_executor.py` / `plugins/worker.py` | Same-machine isolation; job JSON inspiration |
| `artifact_store.py` + serializers | Network boundary |
| `resolve_capability` | Default placement hints |
| `run_control.py` Redis | Orthogonal (API process fan-out); may later share Redis for job queue |
| MCP optimization placement | Advisory; scheduler is authoritative |

---

## 12. Acceptance criteria (full goal)

1. Two Graphyn installs: control + GPU worker.
2. One GraphIR run places GPU nodes on the worker and CPU nodes on control (or second worker).
3. Cancel stops the remote node.
4. Artifacts/provenance show which `worker_id` ran each node.
5. Single-machine `LocalPythonBackend` behavior unchanged when `GRAPHYN_BACKEND` unset.

---

## 13. Risks

- **Pickle / PortDataType** across versions — mitigate with serializer registry + versioned artifact envelopes
- **Plugin drift** between hosts — advertise plugin set; fail job if missing
- **Large dataset copy** — prefer shared store / NFS for training data paths; pass path refs when both sides mount the same volume
- **Blackwell / FaceRecognition VRAM** — worker reports free VRAM; honor `min_vram_mib` and existing TF CPU fallbacks

---

## 14. Server-99 two-box runbook (P1)

Goal: control plane on machine A (laptop / API host); GPU worker on Server-99.

### Prerequisites
- Same Graphyn version / plugin set on both hosts (worker advertises `plugins`; missing `node_type` → claim skips / job fails).
- Network: worker can reach control `http://<A>:8001/api/v1` (Bearer `GRAPHYN_API_TOKEN` if set).
- No shared filesystem required — blobs cross the network via `POST/GET /api/v1/artifacts/blob`.

### Machine A — control plane

```bash
export GRAPHYN_BACKEND=distributed
export GRAPHYN_API_TOKEN=secret   # optional but recommended
export GRAPHYN_DISTRIBUTED_JOB_TIMEOUT=3600

# API (workers + blob store)
venv/bin/uvicorn app.api.main:app --host 0.0.0.0 --port 8001

# In another shell — run the example graph
GRAPHYN_BACKEND=distributed \
  venv/bin/python -m app.cli.main run \
  --graph examples/29_distributed_placement/pipeline.graph.json
```

Local / CPU nodes (`placement.mode=local` or unconstrained) execute on A via `NodeExecutor`.
Nodes with `tags:["gpu"]` / `require_gpu:true` enqueue jobs and wait for Server-99.

### Server-99 — GPU worker

```bash
export GRAPHYN_CONTROL_URL=http://<A-IP>:8001/api/v1
export GRAPHYN_API_TOKEN=secret
export GRAPHYN_WORKER_ID=server99-gpu

venv/bin/python -m app.cli.main worker start \
  --control-url "$GRAPHYN_CONTROL_URL" \
  --worker-id "$GRAPHYN_WORKER_ID" \
  --labels gpu,lab \
  --pool gpu-lab
```

The worker heartbeats (~15s), claims eligible jobs, downloads `input_refs`, runs `NodeExecutor`, uploads output blobs, and completes with `output_refs`.

### Same-host smoke (no second box)

```bash
# Terminal 1 — API
GRAPHYN_BACKEND=distributed venv/bin/uvicorn app.api.main:app --port 8001

# Terminal 2 — in-process worker against the same registry is for unit tests;
# for HTTP loopback on one box:
GRAPHYN_CONTROL_URL=http://127.0.0.1:8001/api/v1 \
  venv/bin/python -m app.cli.main worker start \
  --control-url http://127.0.0.1:8001/api/v1 \
  --worker-id local-gpu --labels gpu --once
```

### Env reference (P1)

| Variable | Role |
|---|---|
| `GRAPHYN_BACKEND=distributed` | Select wave scheduler backend |
| `GRAPHYN_CONTROL_URL` | Worker → control base (`…/api/v1`) |
| `GRAPHYN_WORKER_ID` | Stable worker identity |
| `GRAPHYN_API_TOKEN` | Shared Bearer token |
| `GRAPHYN_DISTRIBUTED_JOB_TIMEOUT` | Control wait per remote job (default 120s) |
| `GRAPHYN_DISTRIBUTED_STORE` | `disk` (default), `redis`, or `memory` — registry/queue durability |
| `GRAPHYN_REDIS_URL` | When set, distributed store prefers Redis (same URL as run_control) |
| `GRAPHYN_JOB_LEASE_TTL_S` | Claimed-job lease TTL before reclaim (default 60s) |

