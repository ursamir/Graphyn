# Distributed Execution

> Source of truth for multi-machine Graphyn orchestration.  
> Complements [ARCHITECTURE.md](./ARCHITECTURE.md) and [PIPELINE_EXECUTION.md](./PIPELINE_EXECUTION.md).  
> Status: **implementing** (P0 foundation → P1 two-box MVP → P2 operable).

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
1. Build waves (reuse `PipelineGraph`)
2. For each node in wave: resolve placement → if local worker slot, run `NodeExecutor`; else enqueue job and wait
3. Materialize inputs: serialize upstream outputs → store → `input_refs`
4. On completion: hydrate `output_refs` → in-memory port values for downstream **on the control plane** (or pass refs through if downstream is also remote — P1 may hydrate always for simplicity)
5. Mirror events into `PipelineLogger` / run journal

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
- Checkpoints: write checkpoint blobs to artifact store so resume can continue on another worker (P2)
- Isolated plugin timeouts stay via `GRAPHYN_PLUGIN_ISOLATED_TIMEOUT`

---

## 9. UI (P2)

- **Workers** page under Admin (online, GPU, labels, last heartbeat)
- Builder: optional placement chip on selected node
- Run detail: per-node `worker_id` in provenance / status strip

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
- [x] Real claim/complete loop; remote `NodeExecutor` on worker (local-ref / in-process path; full artifact hydrate still P1+)
- [x] Scheduler uses tags + `requires_gpu`
- [ ] Example: pin `trainer`/`evaluator` to GPU worker; rest local
- [ ] Document Server-99 + second host runbook

### P2 — Operable
- [ ] Persistent registry (Redis or disk) for multi-API-worker control
- [ ] Cancel to worker; lease reclaim
- [ ] UI Workers + run placement column
- [ ] Plugin list advertised; refuse job if node_type missing

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
