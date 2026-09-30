# Distributed Execution

> Source of truth for multi-machine Graphyn orchestration.  
> Complements [ARCHITECTURE.md](./ARCHITECTURE.md) and [PIPELINE_EXECUTION.md](./PIPELINE_EXECUTION.md).  
> Status: **implementing** (P0–P2 operable; P3 scale later).

---

> **First run?** See [GETTING_STARTED.md](./GETTING_STARTED.md) for Mode A vs Mode B. This file owns contracts, APIs, CLI flags, and the multi-host runbook.

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
  "duration_s": 98.2,
  "lease_generation": 0,
  "output_sha256": { "output": "<sha256 hex of the uploaded blob>" }
}
```

- `lease_generation` must be the generation the worker **claimed** (the fencing
  token), never a value re-read from the queue.
- `output_sha256` (optional, sent by current workers) lets the control plane
  verify each downloaded output blob; a mismatch fails the node.
- Jobs also carry `finished_at` (set on complete / cancel / fail) and
  `result_consumed_at` (set when the control plane reads the result). Terminal
  history (`GRAPHYN_JOB_HISTORY_MAX`, default 500) is trimmed oldest-first by
  `finished_at`; the job being completed is never trimmed, and unread results
  are kept until consumed or older than `GRAPHYN_JOB_RESULT_TTL_S` (default
  3600). Per-job events are capped at `GRAPHYN_JOB_EVENTS_MAX` (default 500,
  newest kept).
- `WorkerInfo`, `NodeJob` and `JobResult` are `extra="forbid"`: a peer on an
  older commit rejects the new fields (`finished_at`, `result_consumed_at`,
  `output_sha256`, heartbeat `active_job_ids`). **Upgrade the control plane and
  all workers together** (KNOWN_ISSUES MODEB-VERSION-SKEW-1).

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

**Worker identity.** `--worker-id` / `GRAPHYN_WORKER_ID`; when unset the CLI
auto-generates `<hostname>-<8 hex>`. The legacy shared default `worker-local`
is replaced by an auto id (with a loud warning) in Mode B, since two machines
sharing one id would steal each other's leases.

**Register = new instance.** `POST /workers/register` requeues every job still
claimed under that `worker_id` (bumping `lease_generation`, counting an
attempt) — a restarted process cannot still be running them, and the bumped
generation fences any late complete/upload from the dead instance. A worker
that re-registers mid-job (e.g. after a heartbeat `404` because the control
plane lost its registry) passes `?active_job_ids=j1,j2` to keep those claims.
The response lists `released_job_ids` when any were requeued.

**Heartbeat v2.** Body:

```json
{ "resources": {…}, "status": "busy", "active_jobs": 1, "active_job_ids": ["job-uuid"] }
```

- `status` must be a `WorkerStatus` (`idle` / `busy` / `draining` / `offline`);
  anything else → `422` (never written to the registry).
- `active_job_ids` present → only those leases (claimed by this worker) are
  renewed; a job the worker no longer reports expires and is reclaimed.
- `active_job_ids` omitted → legacy renew-every-claimed-job behaviour, logged
  once per worker as deprecated.
- `404` means the control plane does not know the worker → the CLI worker
  re-registers (with its active job ids) and retries.

---

## 4. Runtime backends

| Backend id | When |
|---|---|
| `local_python` | Default; current behavior (unchanged) |
| `distributed` | `GRAPHYN_BACKEND=distributed` or explicit `register_backend` |

`DistributedBackend.execute()`:
1. Build waves from GraphIR edges (`compute_ir_waves` — same level algorithm as `PipelineGraph`, no node instantiation required for remote types)
2. For each node in wave order: resolve placement → if local, run `NodeExecutor`; else enqueue job and wait
3. Materialize inputs: pickle+recast → `put_blob` → `input_refs` (see `app/core/distributed/transfer.py`).
   Placement: only an explicit IR `placement.mode=worker` pins a job to one
   worker. `pool` / `auto` / capability placements enqueue constraints only
   (`pool`, `tags`, `require_gpu`, `min_vram_mib`) and any eligible worker
   claims — no run-start pin, and resolution bumps a per-run load score so
   multi-node graphs do not hot-spot the least-loaded worker.
4. On completion: hydrate `output_refs` → in-memory port values for downstream **on the control plane** (always hydrate in P1), verifying `output_sha256` when present, then ack the result (`result_consumed_at`)
7. When the run is terminal, its transfer blobs are deleted after
   `GRAPHYN_DISTRIBUTED_BLOB_GRACE_S` (default 30s; `0` = immediately):
   `jobs/<job_id>/…` outputs always; content-addressed inputs only if no other
   non-terminal job references them and nobody re-put them since.
   `GRAPHYN_DISTRIBUTED_KEEP_BLOBS=1` disables this (debugging).
5. All-local graphs short-circuit to `LocalPythonBackend` unchanged
   Remote/mixed graphs follow the same logical-vs-materialized contract as the local orchestrator ([PIPELINE_EXECUTION.md § Run lifecycle](./PIPELINE_EXECUTION.md#run-lifecycle)): outputs are scoped to `artifacts/<slug>/runs/<run_id>/`, `meta.json` `graph_hash` is the **logical** (pre-scoping) hash (`materialized_graph_hash` records the executed one), each node's `NodeJob.seed` is `planner.derive_node_seed(graph_seed, node_type, index, logical_config)` (identical to Mode A), and cache keys use the logical config.
6. Conditional edges are evaluated with the same `evaluate_condition` helper as the local orchestrator (a false condition leaves the destination port unwired). `use_cache=True` consults `PipelineCache` for local and remote nodes. Pausing a run holds new claims for that run id; an in-flight `process()` still finishes unless the run is cancelled. A late `complete()` with the wrong `lease_generation` deletes generation-scoped output blobs (`jobs/{job}/g{n}/…`) and appends `artifacts/distributed_blob_tombstones.jsonl`.

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
| `GET` | `/api/v1/jobs/{id}` | Read-only status (+ `run_paused`); never renews leases (`?worker_id=` accepted, ignored) |
| `POST` | `/api/v1/artifacts/blob[?key=&worker_id=]` | Upload blob (write-once, see §7.1) |
| `GET` | `/api/v1/artifacts/blob/{key}` | Download blob (`sha256/` keys verified before serving; `409` on corruption) |

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
- `GRAPHYN_API_TOKEN=…`

---

## 7. Shared storage profiles

| Profile | Use |
|---|---|
| `local` | Single host; URIs map under `workspace/artifacts` (dev) |
| `file` / NFS | Two boxes sharing a mount (LAN MVP) |
| `s3` / MinIO | Decoupled object store (preferred beyond lab) |

P1 two-box path on Server-99: NFS **or** MinIO; default implementation starts with **content-addressed local store + HTTP artifact fetch/put** through the control API so boxes need not share a filesystem.

### 7.1 Blob key rules (`POST /artifacts/blob`)

| Key | Rule |
|---|---|
| omitted | Server derives `sha256/<ab>/<cd>/<digest>` (content addressed) |
| `sha256/…` explicit | Rejected (`400`) — clients cannot choose content keys |
| `jobs/<job_id>/g<gen>/<port>` | Allowed only when `worker_id` (query or `X-Graphyn-Worker-Id` header) currently holds the job's claim **at exactly generation `<gen>`** (`403` otherwise, e.g. after a reclaim) |
| anything else | Rejected (`400`) |

Blobs are **write-once**: identical bytes to an existing key are an idempotent
`200`; different bytes → `409` (never overwritten). The response includes
`sha256`; `http_put_blob` checks it against the local digest. Hashing and the
disk write run in a threadpool (off the event loop). Downloads
(`get_blob` / `http_get_blob`) verify `sha256/` key digests and the result's
`output_sha256`; a worker whose local copy fails verification refetches over
HTTP, and the HTTP bytes are verified too (fail closed).

**Retention.** Run-end cleanup (§4 step 7) plus a TTL sweep in
`cleanup_workspace` (`POST /system/cleanup`, when `delete_cache`): files under
`artifacts/distributed_blobs` older than `GRAPHYN_DISTRIBUTED_BLOB_TTL_S`
(default 86400) are deleted unless referenced by a non-terminal job.

---

## 8. Failure, cancel, resume

- Job lease with TTL; worker heartbeat (with `active_job_ids`) renews leases, including a daemon thread during long `execute` and while waiting on a paused run. `GET /jobs/{id}` is read-only and does **not** renew. Expired lease → requeue (at-most-once → at-least-once with idempotent artifact keys)
- Worker `complete` is retried with exponential backoff on network errors / `5xx` (`GRAPHYN_WORKER_COMPLETE_RETRIES`, default 6); `4xx` (e.g. `409` fenced / already terminal) is final
- Cancel: control sets job cancelled; worker polls (CLI cancel-watch ~2 Hz during execute) and stops via `NodeExecutor.request_cancel` / isolated process-group terminate
- Checkpoints: write checkpoint blobs to artifact store so resume can continue on another worker (P3)
- Isolated plugin timeouts stay via `GRAPHYN_PLUGIN_ISOLATED_TIMEOUT`
- **P2 durable store:** registry + queue persist under `workspace/distributed/*.json` by default (or Redis when `GRAPHYN_REDIS_URL` is set). In-memory remains the fast path; `GRAPHYN_DISTRIBUTED_STORE=memory` disables durability (tests).
- **P2 cancel → worker:** `POST /jobs/{id}/cancel` marks the job cancelled; claiming workers poll status (CLI / loopback) and stop before/after execute. Heartbeats renew leases; expired leases reclaim to `pending`.

---

## 9. UI (P2)

- **Workers** page under Deploy (`#/workers`): summary strip + label/pool/status filters; row detail drawer; id, status, labels/pools, GPU/VRAM, last heartbeat, **stale** badge (>45s); empty state = Mode B + copyable `graphyn worker start`
- **Trace** page under Observe (`#/trace`): backtrack artifact/run → node → graph → worker (uses `distributed_node_workers` from run meta; see `GET /api/v1/trace`)
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


### Optional trainer-oriented graph (not the checked-in example)

The checked-in `examples/29_distributed_placement/pipeline.graph.json` uses light
Common nodes so ports validate. A trainer/evaluator sketch would wire
`features→trainer.dataset` / `model` and `trainer→evaluator.model_artifact` with
matching port names — keep that as a custom graph; do not replace the Common demo.

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
| `GRAPHYN_JOB_HISTORY_MAX` | Terminal jobs kept in the queue snapshot (default 500) |
| `GRAPHYN_JOB_RESULT_TTL_S` | Unread results protected from history trim for this long (default 3600) |
| `GRAPHYN_JOB_EVENTS_MAX` | Events kept per job (default 500) |
| `GRAPHYN_WORKER_COMPLETE_RETRIES` | Worker retries for complete / blob upload (default 6) |
| `GRAPHYN_DISTRIBUTED_BLOB_GRACE_S` | Delay before run-end blob cleanup (default 30) |
| `GRAPHYN_DISTRIBUTED_BLOB_TTL_S` | `cleanup_workspace` blob sweep age (default 86400) |
| `GRAPHYN_DISTRIBUTED_KEEP_BLOBS` | `1` disables run-end blob cleanup |


## 15. Review fixes (P0–P2 hardening)

Post-review hardening applied on `cursor/usecase-plugins-workflows`:

| Issue | Fix |
|---|---|
| Job GPU constraints dropped on enqueue | `effective_job_constraints(placement, capability)` mirrors `resolve_worker`; backend stamps `require_gpu` / `tags` / VRAM / pool onto `NodeJob`; only an explicit IR `mode=worker` pins the job (superseded run-start pinning — see Mode B fixes) |
| Example graph invalid ports | `examples/29_distributed_placement` uses Common `python_code` → `set_map` (gpu-tagged) → `json_transform` with `input`/`output` ports |
| Blob path jail | `_safe_path` uses `Path.is_relative_to(root)` |
| HTTP GET blob nested keys | `http_get_blob` percent-encodes with `urllib.parse.quote(key, safe="/")` |
| Cross-process wait | `wait_for_result` polls the durable store (disk/Redis) so CLI enqueue + API complete wake without sharing a process Event |
| Complete authz + lease fencing | `complete` requires status ∈ {claimed,running}, `worker_id == claimed_by`, and matching `lease_generation` (reclaim increments generation) |
| Per-job timeout | Each remote wait uses `job.timeout_s` / `GRAPHYN_DISTRIBUTED_JOB_TIMEOUT` (no shared graph-wide deadline) |
| Worker pin + plugins | `resolve_worker(mode=worker)` fails closed when the pinned worker advertises plugins that omit `node_type` |
| Empty plugin advertisement | Worker CLI warns when `plugins` stays empty; optional `--plugins` override |

### Hardening (pillar E)

| Issue | Fix |
|---|---|
| Mid-flight cancel | Isolated plugin subprocess: `cancel_check` polled during wait → `terminate_process_group`. `NodeExecutor.request_cancel` / `set_cancel_check` checked between retries and before `process`; passed into `run_isolated_node`. Worker CLI HTTP loop: ~2 Hz cancel-watch thread during execute. |
| Preferred-worker pin after reclaim | `reclaim_expired_leases` calls `widen_placement_after_reclaim`: `mode=worker` → `mode=auto` (clears `worker`), keeps tags / `require_gpu` / VRAM / pool; `lease_generation` still increments. |
| Atomic job claim (DIST-001) | `JobQueue.claim` uses `DistributedStateStore.mutate_queue` (disk: exclusive `jobs.lock` flock RMW; Redis: lock / WATCH) so pending→claimed is CAS-safe across processes — not `threading.Lock` alone |
| Queue snapshot lost updates (DIST-002) | All durable `JobQueue` mutators (`enqueue` / `claim` / `complete` / `renew_lease` / `append_events` / `cancel` / `mark_running` / `reclaim_expired_leases` / `renew_leases_for_worker` / `clear`) apply patches inside `mutate_queue` / `_durable_mutate` — not blind full-snapshot replace from a stale local cache |
| Worker registry lost updates (DIST-003) | All durable `WorkerRegistry` mutators (`register` / `heartbeat` / `remove` / `clear`) apply patches inside `mutate_workers` / `_durable_mutate_workers` (disk: exclusive `workers.lock` flock + unique temp files; Redis: lock / WATCH; memory: RLock) — not blind `save_workers` from a stale local cache |

### Mode B fixes (2026-09)

| Issue | Fix |
|---|---|
| History trim dropped random jobs (uuid sort) incl. unread results | Trim by `finished_at`; never the job being completed; unread results kept until `result_consumed_at` (backend ack) or `GRAPHYN_JOB_RESULT_TTL_S` |
| Restarted worker kept dead jobs alive; complete never retried; `worker-local` collisions | Heartbeat `active_job_ids`; register requeues old claims (bumped generation); complete retry/backoff; auto `<host>-<uuid8>` worker ids |
| In-process / loopback workers sent the queue's *current* generation | Always the claimed `job.lease_generation` (fencing restored) |
| Every remote job pinned to the run-start worker | Pin only for IR `mode=worker`; constraints otherwise; per-run load-score bump |
| Cleanup deleted staging/prod runs and shared deduplicated artifacts | `protected_run_ids()` (non-latest aliases + model-registry stages) skipped by `cleanup_workspace`; `delete_run` raises `RunProtectedError` (409) unless `force`; `ArtifactStore.purge_run` reference-counts by `by_run` membership; age `cleanup` skips protected / recently-referenced artifacts |
| Redis `mutate_queue` dropped `paused_runs` | Encoded in every write |
| Redis lock (10s) could expire mid-mutate → lost update | Every write is WATCH/MULTI CAS; lock is fairness only (30s); release failures logged |
| Blobs never deleted; no-op disk rewrites; GET renewed leases; unbounded events | Run-end + TTL blob cleanup; disk store skips identical rewrites; GET read-only; events capped |
| Blob upload could overwrite any key; no download verification; sync hashing on event loop | §7.1 key rules, write-once, `output_sha256`, verified downloads, threadpool |
| Worker never re-registered after 404; free-form heartbeat status | Re-register on 404; `status: WorkerStatus` (422 otherwise) |
| `ArtifactStore` per-instance locks, split read/write locks, fixed `*.json.tmp` | One exclusive `.store.lock` flock (`app.core.persist.file_lock`) across each RMW; unique temp names |
| Registry / queue reads served stale per-process caches | Read-through: reload when `store.state_version()` changes (disk inode/mtime/size, memory counter); Redis always read-through |
| Mixed graphs saved the materialized graph hash / used one graph-wide seed for every job | Logical `graph_hash` (+ `materialized_graph_hash`), outputs scoped to the run, per-node `derive_node_seed` (same as Mode A), cache keyed by logical config |


### Persistence invariant (shared distributed state)

Any **production read-modify-write** on shared distributed state (workers or job queue) **must** use the cross-process-safe mutation APIs:

- Prefer `load_*` for reads and `mutate_*` (`mutate_workers` / `mutate_queue`) for RMW.
- Keep `save_*` only for justified **init / import / test** full replaces — never for concurrent production updates from a process-local cache.
- Disk backends use exclusive flock on a dedicated lock file for the full RMW and **unique per-write temp filenames** (never a shared `*.json.tmp`).
- `file_lock.acquire` fails closed (`LockUnavailable`) when the platform cannot lock, including a Windows lock of an empty read-only handle. `DiskStateStore` does not treat that as missing JSON.
- Redis backends always commit through WATCH/MULTI (CAS); the distributed lock is only a fairness hint, so lock expiry cannot lose an update — never a process-local `threading.Lock` alone.
- Read-only accessors (`WorkerRegistry.get/list`, `JobQueue.get/get_result/is_cancelled/…`) reload their cache when `DistributedStateStore.state_version(kind)` changes (`None` = always read through).
- In-memory backends use an `RLock` (sufficient only within one process).

### Remaining cancel limits

- [x] Isolated plugin subprocess mid-flight kill on cancel (process group)
- [x] Cooperative cancel between `NodeExecutor` retry attempts / back-off sleep
- [x] Worker CLI polls job status during long execute (cancel-watch thread)
- [x] Reclaim clears preferred-worker pin (widen to tags/GPU eligibility)
- [ ] In-process `node.process()` (non-isolated) cannot be forcibly interrupted mid-call — cancel is observed only before/after `process`, between retries, or when the call returns
- [x] Streaming `execute_stream` polls cancel before start / between items (cooperative; mid-yield still open — DIST-CANCEL-2)

