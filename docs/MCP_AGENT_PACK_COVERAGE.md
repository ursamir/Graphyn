# MCP / Agent Pack Coverage

> How agents discover packs, instantiate marketplace templates, run pipelines, and ship — plus gaps.
> Verified against `app/mcp/tool_registry.py` on branch `cursor/usecase-plugins-workflows`.

## 1. Current MCP tool inventory

**Actual register() count:** **~74–75 unique tools** (credentials + notifications + marketplace/pack-first; +`accept_proposal` when `GRAPHYN_MCP_HUMAN_APPROVAL=1`). Verify with `rg 'register\("' app/mcp/tool_registry.py | wc -l`.

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
| Models | `register_model` (optional `model_path` / `node_id` / `allow_untrained`; compiled_untrained model_builder outputs are refused by default), `list_models`, `get_model`, `request_model_prod`, `approve_model_prod` |
| Ship | `create_ship_package`, `get_ship_package`, `list_ship_packages`, `download_ship_package`, `promote_ship_package` |
| Schedules / webhooks | `list_schedules`, `upsert_schedule`, `enable_schedule`, `delete_schedule`, `run_schedule_now`, `get_webhooks`, `put_webhooks`, `test_webhook` |
| Approval gates | `list_pending_gates`, `decide_gate` (approve requires `GRAPHYN_MCP_HUMAN_APPROVAL=1`) |
| Datasets / workers | `list_dataset_versions`, `get_dataset_version`, `upload_dataset_file`, `list_workers`, `list_jobs` |
| Credentials | `list_credentials`, `create_credential`, `get_credential`, `update_credential`, `revoke_credential` |
| Notifications | `list_notifications`, `mark_notifications_read` |
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
| Expand catalog → IR | `materialize_template` | P0 | **Implemented** (MCP + `app/core/templates/pipeline_template_materializer.py`) |
| Ad-hoc chain → IR | `build_graph_from_chain` | P1 | Helper exists |
| Param validation vs template schema | `validate_template_params` | P1 | Proposed |
| Pack install aligned to PluginPackage roots | extend `install_plugin` | P1 | Document paths: Audio/Common/Agents/Video/WakeWord |
| Design-catalog list_nodes | `list_catalog_nodes` | P2 | Proposed — today `list_nodes` = runtime only |

### Proposed tool sketches

**`search_templates`**
- args: `pack?`, `industry?`, `modality?`, `lifecycle?`, `tags?[]`, `status?`, `q?`, `limit?`
- returns: `{templates:[{id,name,pack,industry,lifecycle,status,value_prop}], count}`

**`list_packs` / `describe_pack`**
- enumerate the shipped packs (Audio, Common, Agents, Video, WakeWord) + node counts + template family counts; RAG / Vision / TinyML / MLOps are removed and have no templates

**`get_node_spec`**
- args: `node_type`
- returns ports, config, pack, status, honesty flags from catalog JSON

**`materialize_template`**
- args: `template_id`, `param_overrides?`
- returns Graph IR 1.1 dict (does not save until `save_pipeline`)

## 4. Agent playbooks

### (a) Keyword spotting train → TFLite edge

1. `search_templates` pack=Audio tags=[kws] industry=smart-home → `tpl-audio-kws-train-smart-home`
2. `materialize_template` → graph; `validate_graph` → `save_pipeline`
3. `execute_pipeline` → `inspect_run` / `list_artifacts`
4. For the int8 TFLite model: `tpl-audio-kws-edge-tflite-*`
5. `register_model` → `create_ship_package` → `request_model_prod` / HITL → `promote_ship_package`

### (b) Call-center transcripts with PII redaction

1. `search_templates` pack=Common tags=[asr,pii] industry=callcenter → `tpl-common-asr-pii-redact-callcenter`
2. Materialize → validate → save → execute (local Whisper; no keys)
3. Composite analytics: `tpl-cross-call-analytics` (ASR → PII → rule-based extract → eval gate → object store)

### (c) Wake word "hey graphyn"

1. `tpl-wakeword-data-gen` → `tpl-wakeword-features` → `tpl-wakeword-train-export` (ONNX) or `tpl-wakeword-train-int8-detect`
2. `tpl-wakeword-detect` is `needs-upstream`: it runs once a trained model exists at `workspace/models/wakeword/<model_name>/<model_name>.onnx`

### (d) Instantiate marketplace template into workspace pipeline

1. `search_templates` → choose `id`
2. Materialize to graph dict
3. `validate_graph`
4. `save_pipeline` (draft) with project + pipeline name
5. Optional: `instantiate_template` for **seeded** examples under workspace `configs/templates`
6. `execute_pipeline` → observe → `publish_pipeline` / promote with approval

## 5. Security

- **Credentials:** `list/create/get/update/revoke_credential` (redacted). Nodes store **connection ids**, never raw keys. Ops env bootstrap via CLI `secrets` only.
- **Inline secrets in IR:** `instantiate_template` / `save_pipeline` reject via `InlineSecretError`.
- **Promote / prod:** require human approval paths already present (`approve_model_prod`, `promote_ship_package`, `hitl_approve` node, `accept_proposal` flag).
- **needs-credentials / needs-endpoint / needs-upstream:** surface the template's `status` and `metadata_extra.requires`; do not fake the missing credential, endpoint or artifact.

## 6. Regenerating catalog + seeds

```bash
python scripts/generate_pipeline_template_catalog.py          # refuses to write invalid entries
python scripts/generate_pipeline_template_catalog.py --check  # validate only
python scripts/materialize_pipeline_template.py <template_id> -o /tmp/out.graph.json
```

Node refinements: [`PLUGIN_NODE_REFINEMENTS.md`](./PLUGIN_NODE_REFINEMENTS.md).
Marketplace overview: [`PIPELINE_TEMPLATE_MARKETPLACE.md`](./PIPELINE_TEMPLATE_MARKETPLACE.md).
