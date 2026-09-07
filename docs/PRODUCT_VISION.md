# Graphyn Product Vision

> Single platform for AI/workflow **development → deployment → accountability**.  
> North star (Samir, 2026-09-07): **n8n + MLflow + orchestrator + Edge Impulse + agentic**, with everything backtracked.

Related: [ARCHITECTURE.md](./ARCHITECTURE.md), [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md), [MARKET_READINESS_ROADMAP.md](./MARKET_READINESS_ROADMAP.md).

---

## 1. One sentence

**Graphyn** is the control plane where humans and AI agents design typed DAG workflows, train and evaluate models, place work on the right machines (cloud/lab/edge), deploy packages, and **always** answer: *what ran, where, with which data, which code, and who/what triggered it?*

---

## 2. Pillars (what “combination of …” means)

| Pillar | Analogy | Graphyn meaning |
|---|---|---|
| **Workflow builder** | n8n | Visual + IR-native Builder, plugins as nodes, templates, triggers, human-in-the-loop |
| **ML lifecycle** | MLflow | Runs, metrics, artifacts, experiments, model lineage, compare/promote |
| **Orchestrator** | Prefect / Airflow / custom | Typed DAG execution, waves, resume, cache, distributed workers |
| **Edge / embed** | Edge Impulse | Collect → train → optimize → package → deploy to edge/device runtimes |
| **Agentic** | MCP / copilots | Agents build/run/debug graphs via MCP + UI; secrets never in IR |
| **Accountability** | Audit + lineage | Provenance, replay, actor trail, backtrack any artifact to graph+run+inputs |

These are **one product**, not five products glued together. GraphIR is the shared language; runs/artifacts/provenance are the shared memory; plugins are the extension surface.

---

## 3. Current fit (honest)

### Strong foundations (keep investing)
- **Orchestrator:** GraphIR, planner waves, LocalPython + Distributed backends, checkpoints, cache, conditions (local), pause/cancel
- **Workflow UX:** IR Builder (n8n-style canvas), Templates, Plugins, Workers UI
- **ML-ish core:** trainer / evaluator / model_builder / experiment_tracker / edge_optimizer / deployment_packager plugins; ArtifactStore + ProvenanceStore + replay
- **Agentic entry:** MCP + CLI + API + secrets store
- **Accountability seeds:** run journal, provenance JSON, artifact lineage UI, `distributed_node_workers` placement map

### Thin or missing (must build for the vision)
| Gap | Why it matters |
|---|---|
| **Promotion / environments** | Dev → staging → prod graph+model versions with approval |
| **RBAC / tenants** | Multi-user accountability (Bearer-only today) |
| **Full Edge device loop** | Wizard + packager exist; flash/device feedback still thin |
| **Agentic diffs depth** | Proposals MCP/UI shipped; richer diff UX / auto-apply guardrails next |
| **Triggers at scale** | Schedules/webhooks/events as productized “always-on” workflows (nodes exist; ops surface thin) |
| **Observability (OTel)** | Trace UX + audit seeds shipped; OTel spans per node/job across workers are P3 |

**Shipped foundations (see Progress):** experiment board, thin audit log, Trace backtrack UX, Agentic proposals, Edge wizard, Workers UI, console IA.

---

## 4. Non-goals (for now)

- Becoming a generic chat LLM product
- Replacing Kubernetes (we *use* workers/backends; P3 K8s is optional scale)
- Audio-only identity — audio is a **pack**, not the brand

---

## 5. Operating principles

1. **GraphIR is canonical** — UI, agents, and CLI all speak the same graph.
2. **Everything is an artifact or a run** — if you can’t point to a run_id / artifact_id, it didn’t happen.
3. **Agents are first-class users** — MCP parity with UI; never embed secrets in graphs.
4. **Placement is explicit** — local / GPU worker / edge capability is part of the graph story.
5. **Backtrack before blame** — lineage and replay beat screenshots and tribal knowledge.

---

## 6. Suggested build sequence toward the vision

1. **Accountability UX (backtrack)** — single “Trace” surface: run → nodes → artifacts → lineage → worker; audit events for mutations  
2. **Experiment / compare** — MLflow-shaped board on top of existing runs + experiment_tracker  
3. **Agentic Builder loop** — MCP tools to propose graph diffs + human approve in UI  
4. **Edge product path** — template + UI wizard: dataset → train → edge_optimizer → deployment_packager → download  
5. **Promotion + RBAC** — environments, approvals, roles  
6. **Distributed harden + OTel** — already started; mid-flight cancel, reclaim widen, traces  

Distributed execution (P0–P2) is the **orchestrator scale** leg of this vision, not a side quest.

---

## 7. Success looks like

A user (or agent) can:
1. Build a pipeline in Builder or via MCP  
2. Train on Server-99 GPU worker, evaluate, register a model artifact  
3. Optimize and package for edge  
4. Deploy / download the package  
5. Months later open any output and **fully backtrack** who/what/where produced it  

…without leaving Graphyn.

---

## 8. Progress (shipped toward the vision)

| When | Item | Notes |
|---|---|---|
| 2026-09-07 | **Trace UX (Pillar A — Accountability)** | Unified `GET /api/v1/trace` backtrack payload (artifact → node → run → graph → worker); thin append-only `audit/events.jsonl` + `GET /api/v1/audit`; Observe → **Trace** UI (`#/trace`) with Open in Trace from Artifacts/Runs. Partial chains when pieces missing. Audit recent events on Admin → System. |
| 2026-09-07 | **Edge deploy wizard (Pillar D)** | Template `examples/templates/edge-deploy.graph.json` + `examples/30_edge_deploy/`; Deploy → **Edge** (`#/edge`) wizard: template → configure model path/target → `run-async` → download package. Hydrate unwraps python_code CodeResult → ModelArtifact. |
| 2026-09-07 | **Experiments board (Pillar B — ML lifecycle)** | `GET /api/v1/experiments` (+ `/{name}`, `/compare`) aggregates `experiment.json` / meta+metrics; Observe → **Experiments** UI (`#/experiments`) with multi-select compare (params/metrics diff). No mlflow package required. |
| 2026-09-07 | **Agentic Builder proposals (Pillar C)** | `proposals/` store + `POST/GET /api/v1/proposals` (+ accept/reject); MCP `propose_graph` / `list_proposals` / `get_proposal`; Build → **Proposals** UI (`#/proposals`) with Accept → Builder via `loadGraphIntoBuilder`; audit on create/accept/reject. |
| 2026-09-07 | **Console IA (vision-aligned nav)** | Restructured sidebar: **Build** (Builder, Templates, Proposals, Runs) · **Observe** (Trace, Experiments, Artifacts) · **Library** (Plugins, Data) · **Deploy** (Edge, Workers) · **Admin** (Projects, Secrets, System). Deep-link query preservation for Trace/Edge/Experiments/Proposals. |

### Console map

| Group | Views | Role |
|---|---|---|
| **Build** | Builder, Templates, Proposals, Runs | Design graphs, review agent proposals, launch & inspect runs |
| **Observe** | Trace, Experiments, Artifacts | Accountability backtrack, compare metrics, artifact library |
| **Library** | Plugins, Data | Extension surface & datasets |
| **Deploy** | Edge, Workers | Edge package loop & distributed placement |
| **Admin** | Projects, Secrets, System | Tenancy seeds, secrets, health + audit |

Still open from §3: full RBAC, promotion, OTel; deepen agentic diffs / promotion approvals.

