# Plugin Node Refinements

> **Design-only deltas** on top of [`PLUGIN_NODE_PLATFORM_CATALOG.md`](./PLUGIN_NODE_PLATFORM_CATALOG.md) (145 base node_types).
> Machine-readable: [`PLUGIN_NODE_REFINEMENTS.json`](./PLUGIN_NODE_REFINEMENTS.json).
> Do **not** delete Existing production nodes without a migration note.

## Summary

| Action | Count | Notes |
|---|---:|---|
| Unchanged (base catalog) | 145 | Existing + Alter + Proposed kept |
| Granularize (new atoms) | **10** | N146–N155 |
| Aggregate runtime nodes | **1** | `micro_speech_pipeline` (already N068) retained |
| Template-only macros | **3** | Prefer over new runtime cards |
| Deprecated | 0 | — |
| **Resulting distinct node_types** | **155** | 145 + 10 |

## Granularize (added)

| ID | node_type | Pack | Why |
|---|---|---|---|
| N146 | `yolo_dataset_yaml_build` | Vision | Split yaml build out of `yolo_train` |
| N147 | `yolo_hyperparam_search` | Vision | Optuna-style search ≠ single train run |
| N148 | `yolo_resume_train` | Vision | Resume checkpoint ≠ cold start |
| N149 | `bm25_index_build` | RAG | Explicit sparse index before hybrid |
| N150 | `parent_doc_retriever` | RAG | Parent/child retrieve atop hierarchical chunks |
| N151 | `hyde_generate` | RAG | Split HyDE from `query_rewrite` |
| N152 | `mcu_window` | TinyML | Atom from `mcu_feature_pipeline` |
| N153 | `mcu_mfcc` | TinyML | Atom from `mcu_feature_pipeline` |
| N154 | `mcu_spectrogram` | TinyML | Atom from `mcu_feature_pipeline` |
| N155 | `hitl_approve` | Agents | Split HITL gate from `agent_loop` |

## Aggregate

### Runtime aggregate (keep one card)

- **`micro_speech_pipeline` (N068)** — opinionated KWS→int8 tflite helper for canvas UX. New flexible graphs should prefer atoms (`mcu_window` → `mcu_mfcc` → `mcu_train` → …).

### Template-only macros (no new runtime node_types)

| Macro | Expands to |
|---|---|
| `rag_ingest_e2e` | `rag/ingest-*` marketplace family |
| `yolo_train_export_e2e` | vision train + export templates |
| `tinyml_kws_to_tflm_e2e` | `tinyml/kws-*-tflm` family |

Prefer **template_only** so the runtime/canvas surface does not explode.

## Altered notes (no deletion)

- **`mcu_feature_pipeline`**: remains valid convenience node; new templates prefer atoms.
- **`query_rewrite`**: HyDE mode kept for compatibility; prefer `hyde_generate` when HyDE-only.

## Honesty / needs-API

- `mcu_flash_ota`, `mcu_ondevice_metrics` → marketplace templates use `status: needs-api` + honesty banner.
- Never fake Devices/flash APIs.

## Migration

None required for Existing nodes. Proposed atoms are additive. When implementing, register new `node_type`s via PluginPackage roots without removing prior types.
