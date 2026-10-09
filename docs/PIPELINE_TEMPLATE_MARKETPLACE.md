# Pipeline Template Marketplace

> Packs are **product surfaces** that ship **workflow templates** (real graphs + use cases), not only node lists.
> Machine catalog: [`PIPELINE_TEMPLATE_CATALOG.json`](./PIPELINE_TEMPLATE_CATALOG.json) (generated).
> Generator (source of truth): `python scripts/generate_pipeline_template_catalog.py`
> Materializer: `app/core/templates/pipeline_template_materializer.py` / `scripts/materialize_pipeline_template.py`

## Design rules

1. **Catalog JSON is authoritative** and generated — never hand-edit it. Every entry comes from an explicit *base pipeline* in the generator (node chain, explicit `edges_hint`, working configs). Industry variants (`tpl-<base>-<industry>`) reuse the base graph unchanged and carry `metadata_extra.base_template`.
2. **Only shipped packs are advertised**: Audio, Common, Agents, Video, WakeWord (plus `cross` composites of those). RAG, Vision, TinyML and MLOps are not shipped and have no templates.
3. **The generator refuses to write an invalid catalog.** Every entry is materialized and validated against the registry built from the shipped `PluginPackage/` tree; one failure aborts the write (`--check` reports without writing).
4. **Every base pipeline is run live** before release. Run ids live in `docs/PIPELINE_TEMPLATE_VERIFICATION.json` and are merged into each entry as `metadata_extra.verified_run`.
5. **One seed graph per base pipeline** is written to `examples/templates/marketplace/tpl-<base>.graph.json` (stale seeds are deleted on regenerate).
6. **Materialize on demand** into Graph IR `schema_version` 1.1 via `POST /pipelines/marketplace/materialize` (or `app/core/templates/pipeline_template_materializer.py`). The materializer binds ingest paths to bundled seed data under `workspace/datasets/input/*`, drops config keys the live node does not accept, caps smoke epochs, and uses `edges_hint` when present.
7. **Console Templates page** loads a slim index at `graphyn-ui/public/marketplace-catalog.json`; regenerate it whenever the full catalog changes.
8. Keep FaceRecognition / unrelated services untouched.

## Taxonomy

| Pack | Template families (base pipelines) |
|---|---|
| Audio | KWS train + TFLite edge, speaker ID, sound-event train/detect, YAMNet classify, rule annotate, quality gate export, speech enhancement, podcast leveling, room-simulation augment, TTS dataset, speaker separation, voice conversion, embeddings, stream monitor, sound generation, dataset balance + version |
| WakeWord | data gen, features, train + export, train + INT8 + detect, detect |
| Video | scene clips, zero-shot tagging, action recognition, frame captions (local VLM), transcribe + captions |
| Agents | local LLM chat, guarded reply + memory, guardrail approval + memory, tool router + memory, structured extract + validate, tool router via MCP, agent loop, email alert |
| Common | ASR captions, ASR PII redact, word alignment, doc chunk store, CSV transform, HTTP poll transform, branch/merge/error, train + track experiment, speaker embeddings, dataset report email |
| Cross | call analytics, meeting notes + memory, TTS → ASR round trip, video + audio fusion |

Filters (marketplace / MCP `search_templates`): `pack`, `packs_used[]`, `industry`, `modality[]`, `lifecycle[]`, `tags[]`, `family`, `status`.

### Status values

| status | Meaning |
|---|---|
| `ready` | Runs out of the box on the bundled seed data (verified live). |
| `needs-credentials` | Validates; the run stops with a clear "configure credential X" / missing dependency error until the operator adds it (e.g. `tool-router-mcp` needs a `graphyn_mcp` credential). |
| `needs-endpoint` | Validates; runs once the named local service is reachable (Ollama at the configured host, allowed by the HTTP egress policy). Until then the run fails with the egress/connection error. |
| `needs-upstream` | Runs once the named upstream template has produced its artifact (e.g. `wakeword-detect` needs the model from `wakeword-train-export`). |

## Catalog entry shape

`id`, `name`, `description`, `pack`, `packs_used[]`, `family`, `industry`, `modality[]`, `lifecycle[]`, `tags[]`,
`node_chain` (`{node_type, role, config_overrides}`), `edges_hint`, `parameters`, `mcp`, `status`, `value_prop`,
`metadata_extra` (`base_template`, `requires`, `verified_run`).

## MCP usage (agents)

1. `search_templates` (pack/industry/tags/lifecycle/status) → pick `id`
2. `materialize_template` → Graph IR
3. `validate_graph` → `save_pipeline` → `execute_pipeline`
4. `inspect_run` / `list_artifacts` / `get_artifact_lineage`
5. Secrets only via `secrets_list` / `secrets_set` — never raw keys in graphs

See [`MCP_AGENT_PACK_COVERAGE.md`](./MCP_AGENT_PACK_COVERAGE.md) for the journey map.

## Regenerate

```bash
venv/bin/python scripts/generate_pipeline_template_catalog.py          # catalog + seed graphs (refuses invalid entries)
venv/bin/python scripts/generate_pipeline_template_catalog.py --check  # validate only
venv/bin/python scripts/generate_plugin_node_platform_catalog.py       # PLUGIN_NODE_PLATFORM_CATALOG.json from the shipped registry
venv/bin/python scripts/materialize_pipeline_template.py tpl-audio-kws-train-smart-home -o /tmp/kws.graph.json
# Offline full-catalog materialize + validate (no API):
venv/bin/python scripts/validate_all_marketplace_templates.py
# Live execute of one template per family (needs GRAPHYN_API_TOKEN):
venv/bin/python scripts/smoke_marketplace_templates.py
```

## Coverage

The catalog's `coverage` object lists shipped node types and the ones no template uses yet (trigger / utility nodes such as `webhook_trigger`, `http_webhook`, `credential_probe`, `set_map`, `realtime_inference`).
