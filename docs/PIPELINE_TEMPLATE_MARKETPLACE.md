# Pipeline Template Marketplace

> Packs are **product surfaces** that ship **workflow templates** (real graphs + use cases), not only node lists.
> Machine catalog: [`PIPELINE_TEMPLATE_CATALOG.json`](./PIPELINE_TEMPLATE_CATALOG.json) (generated).
> Generator (source of truth): `python scripts/generate_pipeline_template_catalog.py`
> Materializer: `app/core/pipeline_template_materializer.py` / `scripts/materialize_pipeline_template.py`

## Design rules

1. **Catalog JSON is authoritative** — do not hand-type hundreds of near-duplicates in markdown.
2. **Materialize on demand** into Graph IR `schema_version` **1.1** (`metadata`, `nodes[{id,node_type,config}]`, `edges[{src_id,src_port,dst_id,dst_port}]`, `parameters`).
3. **Seed only ~20–40** representative `.graph.json` under `examples/templates/marketplace/` (not all templates).
4. **Deduplicate** by stable `id` (`tpl-<family>-…`). Reject rename-only variants.
5. **Honesty**: MCU flash/OTA templates → `status: needs-api` + `honesty_banner` in metadata. Medical/EHR → generic triage/docs only; no clinical claims.
6. Keep FaceRecognition / unrelated services untouched.

## Taxonomy

### Packs (primary)

| Pack | Template families |
|---|---|
| Audio | KWS, SED, enhancement, diarization, captions, call analytics, podcast, meeting CRM, compliance, edge |
| WakeWord | data-gen → feature → train → export → infer → e2e × languages |
| TinyML | KWS / IMU anomaly / tiny vision / audio event × MCU × PTQ/QAT × TFLM/ExecuTorch/CMSIS/Vela |
| Vision | YOLO detect/seg/pose/obb/classify × industries × train/val/export/infer/track |
| RAG | ingest / query / hybrid / HyDE / parent-doc / eval / agentic |
| Video | scene-caption, action classify, AV-align ASR, safety monitor, video-RAG |
| Agents | run-pipeline, ship-promote, schedule, webhook, HITL, tool-router, memory chat |
| MLOps | train-eval-ship, canary, drift, feature-store, dataset-diff |
| Common | HTTP/JSON, control-flow, doc bridge, multimodal embed, realtime |
| Cross | composites across packs |

### Filters (marketplace / MCP)

- `pack`, `packs_used[]`
- `industry`
- `modality[]` (audio, vision, video, text, imu)
- `lifecycle[]`: `ingest` | `prep` | `train` | `eval` | `deploy` | `observe` | `agent`
- `tags[]`, `family`, `status`

### Status values

| status | Meaning |
|---|---|
| `proposed` | Design catalog entry |
| `seeded` | Representative `.graph.json` written under examples |
| `needs-api` | Blocked on missing platform API (e.g. MCU flash) |
| `alter-existing` | Builds on Existing/Alter production nodes |

## Catalog entry shape

Each template **must** include:

- `id`, `name`, `description`
- `pack`, `packs_used[]`, `industry`, `modality[]`, `lifecycle[]`, `tags[]`
- `node_chain`: ordered `{node_type, role?, config_overrides?}`
- `edges_hint` (optional; default linear `n{i}.output → n{i+1}.input`)
- `parameters`
- `mcp`: `{instantiate, required_tools, agent_brief}`
- `status`, `value_prop`

## How packs map to template families

Packs ship nodes **and** a marketplace slice. Example: Vision pack → `tpl-vision-yolo-detect-train-retail-shelf`, export variants, track/hard-neg loops. TinyML pack → MCU×quant×export matrix + honest flash companions.

## MCP usage (agents)

1. `search_templates` (pack/industry/tags/lifecycle) → pick `id`
2. `materialize_template` / materializer → Graph IR
3. `validate_graph` → `save_pipeline` → `execute_pipeline`
4. `inspect_run` / `list_artifacts` / `get_artifact_lineage`
5. Ship path: `create_ship_package` → HITL → `promote_ship_package`
6. Secrets only via `secrets_list` / `secrets_set` — never raw keys in graphs

See [`MCP_AGENT_PACK_COVERAGE.md`](./MCP_AGENT_PACK_COVERAGE.md) for journey map, gaps, and playbooks.

## Regenerate

```bash
python scripts/generate_pipeline_template_catalog.py
python scripts/generate_pipeline_template_catalog.py --min 950 --seed-graphs 32
python scripts/materialize_pipeline_template.py tpl-vision-yolo-detect-train-retail-shelf \
  -o /tmp/retail.graph.json
```

## Coverage

The generator asserts every catalog + refinement `node_type` appears in ≥1 template (or is explicitly deprecated in refinements). See `coverage` object in the JSON catalog.
