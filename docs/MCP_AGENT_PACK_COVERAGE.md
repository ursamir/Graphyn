# MCP / Agent Pack Coverage

> How agents discover packs, instantiate marketplace templates, run pipelines, and ship — plus gaps.
> Verified against `app/mcp/tool_registry.py` on branch `cursor/usecase-plugins-workflows`.

## 1. Current MCP tool inventory

**Actual register() count:** **73 unique tools** (72 always including `search_templates` + pack-first tools + `accept_proposal` when `GRAPHYN_MCP_HUMAN_APPROVAL=1`).

**Docs drift:** [`MCP_SERVER.md`](./MCP_SERVER.md) still says “28/29 tools”. That narrative is **stale**. Journey waves added pipelines/runs/templates/models/schedules/webhooks/ship/audit/datasets/workers. Prefer this doc + `tool_registry.py` as source of truth until MCP_SERVER is rewritten.

### Inventory by journey area

| Area | Tools |
|---|---|
| Discovery | `list_nodes`, `list_plugins`, `install_plugin`, `manage_plugin` |
| Graph | `generate_graph`, `validate_graph`, `get_graph_schema`, `get_graph_capability_summary`, `get_event_schema`, `propose_graph`, `list_proposals`, `get_proposal`, `accept_proposal`*, `reject_proposal` |
| Templates (seeded + marketplace) | `list_templates`, `get_template`, `instantiate_template`, `search_templates` |
| Pipelines | `list_pipelines`, `get_pipeline`, `save_pipeline`, `publish_pipeline`, `promote_pipeline`, `rollback_pipeline` |
| Execution | `execute_pipeline`, `inspect_run`, `pause_run`, `resume_run`, `cancel_run`, `list_runs`, `get_run`, `get_run_outputs`, `compare_runs`, `replay_run`, `optimize_execution` |
| Artifacts / lineage | `list_artifacts`, `get_artifact_lineage` |
| Models | `register_model`, `list_models`, `get_model`, `request_model_prod`, `approve_model_prod` |
| Ship | `create_ship_package`, `get_ship_package`, `list_ship_packages`, `download_ship_package`, `promote_ship_package` |
| Schedules / webhooks | `list_schedules`, `upsert_schedule`, `enable_schedule`, `delete_schedule`, `run_schedule_now`, `get_webhooks`, `put_webhooks`, `test_webhook` |
| Datasets / workers | `list_dataset_versions`, `get_dataset_version`, `upload_dataset_file`, `list_workers`, `list_jobs` |
| Secrets | `secrets_list`, `secrets_set` |
| Workspace / audit | `list_projects`, `list_data_inputs`, `list_experiments`, `get_trace`, `get_readiness`, `get_audit_events`, `export_audit` |

\* `accept_proposal` only when human-approval flag enabled.

## 2. Journey map (pack-first)

```
discover packs/nodes
  → search marketplace templates (pack/industry/tags)
  → get / materialize template → Graph IR
  → validate_graph → save_pipeline (draft)
  → execute_pipeline → inspect_run / artifacts / lineage
  → register_model / create_ship_package
  → HITL approve → promote_ship_package / promote_pipeline
  → schedules / webhooks / workers observe
  → audit export
```

| Step | Tools today | Notes |
|---|---|---|
| Discover nodes | `list_nodes` | Runtime registry only — not full design catalog |
| Discover packs | `list_plugins`, **`list_packs`**, **`describe_pack`** | Pack taxonomy from design catalog + template counts |
| Search templates | `list_templates` | Seeded workspace graphs only |
| Marketplace search | **`search_templates`** (added) | Reads `PIPELINE_TEMPLATE_CATALOG.json` |
| Materialize chain | **`materialize_template`** / `build_graph_from_chain` | MCP + Python helper |
| Validate / save / run | `validate_graph`, `save_pipeline`, `execute_pipeline` | OK |
| Observe | `inspect_run`, `list_artifacts`, `get_artifact_lineage`, `list_workers` | OK |
| Ship | ship_* + model prod approve | HITL for prod |
| Secrets | `secrets_*` | Names only on list |

## 3. Gaps (blocking pack-first agents)

| Gap | Proposed tool | Priority | Status |
|---|---|---|---|
| Filter marketplace catalog | `search_templates` | P0 | **Implemented** (reads catalog JSON + optional seeded dir) |
| Pack taxonomy | `list_packs` / `describe_pack` | P0 | **Implemented** |
| Node contract from design catalog | `get_node_spec` | P0 | **Implemented** (ports+config from PLATFORM_CATALOG + refinements) |
| Expand catalog → IR | `materialize_template` | P0 | **Implemented** (MCP + `app/core/pipeline_template_materializer.py`) |
| Ad-hoc chain → IR | `build_graph_from_chain` | P1 | Helper exists |
| Param validation vs template schema | `validate_template_params` | P1 | Proposed |
| Pack install aligned to PluginPackage roots | extend `install_plugin` | P1 | Document paths: TinyML/Vision/RAG/… |
| Design-catalog list_nodes | `list_catalog_nodes` | P2 | Proposed — today `list_nodes` = runtime only |

### Proposed tool sketches

**`search_templates`**
- args: `pack?`, `industry?`, `modality?`, `lifecycle?`, `tags?[]`, `status?`, `q?`, `limit?`
- returns: `{templates:[{id,name,pack,industry,lifecycle,status,value_prop}], count}`

**`list_packs` / `describe_pack`**
- enumerate Audio, Common, TinyML, Vision, RAG, Video, Agents, MLOps, WakeWord + node counts + template family counts

**`get_node_spec`**
- args: `node_type`
- returns ports, config, pack, status, honesty flags from catalog JSON

**`materialize_template`**
- args: `template_id`, `param_overrides?`
- returns Graph IR 1.1 dict (does not save until `save_pipeline`)

## 4. Agent playbooks

### (a) YOLO retail detect train + export

1. `search_templates` pack=Vision industry=retail-shelf tags=[train] → pick `tpl-vision-yolo-detect-train-retail-shelf`
2. `materialize_template` (or Python materializer) → graph
3. `validate_graph` → `save_pipeline` project=… pipeline=retail-yolo-detect
4. `execute_pipeline` → `inspect_run` / `list_artifacts`
5. `search_templates` … export-onnx … → materialize/save/run export graph
6. `register_model` → `create_ship_package` → `request_model_prod` / HITL → `promote_ship_package`
7. Secrets: none for local; HF token via `secrets_set` if pulling weights

### (b) RAG support bot ingest + query

1. `secrets_set` name=`slack_token` (if Slack source) — never inline
2. `search_templates` pack=RAG industry=support tags=[ingest] → `tpl-rag-ingest-slack-markdown-faiss-support` (example)
3. Materialize → validate → save → execute ingest
4. Search query/hybrid template → save as second pipeline → execute with user question params
5. Optional agentic: `tpl-rag-agentic-rag-support` with `guardrail_filter` + `hitl_approve`
6. `rag_eval` template for eval_gate before promote

### (c) TinyML KWS → TFLM CMSIS pack

1. `search_templates` pack=TinyML tags=[kws,tflm,cmsis-pack] industry=wearable
2. Materialize with params `target_mcu=cortex-m4`, `quant_mode=ptq`
3. validate → save → execute (host sim via `tflm_host_sim`)
4. Flash companion template is **`needs-api`** — agent must surface honesty banner; do **not** call fake flash
5. `create_ship_package` for the CMSIS-Pack artifact; promote only with HITL

### (d) Instantiate marketplace template into workspace pipeline

1. `search_templates` → choose `id`
2. Materialize to graph dict
3. `validate_graph`
4. `save_pipeline` (draft) with project + pipeline name
5. Optional: `instantiate_template` for **seeded** examples under workspace `configs/templates`
6. `execute_pipeline` → observe → `publish_pipeline` / promote with approval

## 5. Security

- **Secrets:** only `secrets_set` / `secrets_list` (names only). Node configs take **secret names**, never raw keys.
- **Inline secrets in IR:** `instantiate_template` / `save_pipeline` reject via `InlineSecretError`.
- **Promote / prod:** require human approval paths already present (`approve_model_prod`, `promote_ship_package`, `hitl_approve` node, `accept_proposal` flag).
- **needs-api:** agents must not invent Devices/flash tooling.

## 6. Regenerating catalog + seeds

```bash
python scripts/generate_pipeline_template_catalog.py --min 950 --seed-graphs 32
python scripts/materialize_pipeline_template.py <template_id> -o /tmp/out.graph.json
```

Node refinements: [`PLUGIN_NODE_REFINEMENTS.md`](./PLUGIN_NODE_REFINEMENTS.md).
Marketplace overview: [`PIPELINE_TEMPLATE_MARKETPLACE.md`](./PIPELINE_TEMPLATE_MARKETPLACE.md).
