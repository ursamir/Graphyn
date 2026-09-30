# Node Catalogue

The first two tables are the Audio + Common production nodes; compact tables for the other packs follow (see `PluginPackage/NODES.md` — `model_builder` ships inside the `trainer` plugin). There are no built-in node implementations in `app/core/nodes/audio/` or `app/core/nodes/ml/` — those directories do not exist.

`PluginPackage/` currently has 156 `plugin.toml` manifests. Proposed packs (RAG, Vision, TinyML, MLOps, Agents, WakeWord, Video) run their real implementations by default (`config.stub=False`). `stub=True` is an explicit placeholder that logs a warning. The editor catalog badges a node **stub** only when that field's schema default is true. Device flash and on-device metrics write a host-side dry-run receipt; they do not program a board or report device telemetry.


> **Platform design catalog (100+ node_types, alterations, TinyML/YOLO/RAG):** [`docs/PLUGIN_NODE_PLATFORM_CATALOG.md`](./PLUGIN_NODE_PLATFORM_CATALOG.md) (+ [`PLUGIN_NODE_PLATFORM_CATALOG.json`](./PLUGIN_NODE_PLATFORM_CATALOG.json)).

For full config fields, port specs, and capability details → **[PluginPackage/NODES.md](../PluginPackage/NODES.md)**  
For architecture, data flow, and install patterns → **[PluginPackage/ARCHITECTURE.md](../PluginPackage/ARCHITECTURE.md)**

---

## Audio Plugins — `PluginPackage/Audio/` (19 nodes)

| node_type | Category | Key Dependencies |
|---|---|---|
| `dataset_ingest` | Input | librosa, soundfile; optional: datasets, boto3 |
| `stream_ingest` | Input | librosa; optional: sounddevice, websockets, ffmpeg (rtp/rtsp) |
| `audio_conditioner` | Preprocessing | librosa, scipy; optional: pyloudnorm |
| `audio_quality_gate` | Preprocessing | librosa, scipy, numpy; optional: pyloudnorm |
| `audio_annotator` | Preprocessing | numpy (pure Python) |
| `alignment_node` | Preprocessing | optional: ctc-forced-aligner, mfa |
| `segmenter` | Processing | librosa; optional: webrtcvad |
| `augmentation_pipeline` | Augmentation | librosa, scipy; optional: audiomentations |
| `speech_enhancer` | Enhancement | noisereduce; optional: deepfilternet |
| `speaker_separator` | Enhancement | optional: pyannote.audio, speechbrain |
| `environment_simulator` | Enhancement | pyroomacoustics, numpy |
| `feature_frontend` | Features | librosa, numpy |
| `stream_processor` | Streaming | numpy |
| `audio_event_detector` | Detection | optional: tensorflow, torch |
| `audio_classifier` | Inference | optional: tensorflow, torch |
| `speech_synthesizer` | Generation | optional: TTS (Coqui), espeak-ng |
| `voice_converter` | Generation | optional: speechbrain, torch |
| `audio_generator` | Generation | optional: audiocraft, torch |
| `audio_exporter` | Output | soundfile, numpy |

## Common Plugins — `PluginPackage/Common/` (31 nodes)

| node_type | Category | Key Dependencies |
|---|---|---|
| `dataset_builder` | ML | numpy, scikit-learn; optional: tensorflow, torch |
| `model_builder` | ML | ships inside the `trainer` plugin (same pack) |
| `trainer` | ML | optional: tensorflow/keras, torch |
| `evaluator` | ML | scikit-learn, numpy; optional: matplotlib, seaborn |
| `edge_optimizer` | ML | optional: tensorflow, onnx, tf2onnx |
| `realtime_inference` | Inference | optional: tensorflow, torch, onnxruntime |
| `dataset_balancer` | ML | numpy |
| `dataset_versioner` | ML | hashlib, json (stdlib) |
| `experiment_tracker` | ML | json (stdlib); optional: mlflow |
| `deployment_packager` | ML | zipfile, json (stdlib) |
| `embedding_generator` | Features | optional: torch, transformers, openl3, speechbrain |
| `multimodal_fusion` | Features | optional: torch, transformers |
| `asr_transcribe` | Processing | numpy; optional: httpx |
| `pii_redact` | Processing | numpy; optional: presidio |
| `structured_llm` | Processing | optional: httpx |
| `eval_gate` | Quality | stdlib |
| `http_webhook` | Output | optional: httpx |
| `doc_parse_chunk` | Input | stdlib; optional: unstructured |
| `caption_export` | Output | stdlib |
| `object_store` | Output | stdlib; optional: boto3 |
| `http_request` | Output | optional: httpx |
| `if_switch` | Logic | stdlib |
| `set_map` | Transform | stdlib |
| `json_transform` | Transform | stdlib |
| `schedule_trigger` | Input | stdlib |
| `python_code` | Transform | stdlib (trusted-operator exec; not a sandbox) |
| `error_catch` | Logic | stdlib |
| `merge` | Transform | stdlib |
| `wait_delay` | Logic | stdlib |
| `csv_table` | Output | csv (stdlib) |
| `send_email` | Output | stdlib (`app.core.notify.smtp_notify`); `GRAPHYN_SMTP_*` env or SMTP `connection_id`; `dry_run` |
| `credential_probe` | Utility | stdlib (smoke plugin: declares a credential kind, resolves a connection) |

## Agents Plugins — `PluginPackage/Agents/` (9 nodes)

| node_type | Purpose |
|---|---|
| `agent_loop` | **Extractive only** — scans `context` in windows for the goal's terms; calls no LLM and no tools (`mode="extractive"`). Use `llm_chat` for model calls. |
| `llm_chat` | Chat via `provider` = `local` (default, extractive) / `stub` / `openai_compat` / `ollama` / `anthropic` / `gemini`; `connection_id` → workspace default → env |
| `prompt_template` | `str.format` or sandboxed Jinja2 render |
| `tool_router` | Map text / `ToolCallRequest` to a registered tool name |
| `mcp_tool_call` | Call an in-process Graphyn MCP tool (allowlisted) |
| `guardrail_filter` | Regex guardrails (pii, secret, profanity, jailbreak) |
| `output_schema_validate` | Parse LLM JSON and validate against a JSON-Schema subset |
| `memory_store` | Agent memory; `backend` = `json` (locked, atomic file) or `memory` (process-local) |
| `hitl_approve` | Human approval gate via out-of-band decision file; fail closed |

## MLOps Plugins — `PluginPackage/MLOps/` (12 nodes)

`ab_assign`, `artifact_checksum`, `canary_gate`, `dataset_diff`, `drift_detect`, `feature_store_read`, `feature_store_write`, `model_card`, `run_metadata_stamp`, `ship_package_create`, `ship_package_promote`, `ship_package_transition`.

## RAG Plugins — `PluginPackage/RAG/` (24 nodes)

| Group | node_types |
|---|---|
| Connectors / ingest | `rag_fs_connector`, `rag_notion_connector`, `rag_slack_connector`, `rag_url_crawl` |
| Chunking | `chunk_recursive`, `chunk_markdown`, `chunk_semantic`, `chunk_hierarchical` |
| Index / store | `text_embed`, `bm25_index_build`, `vector_store_write`, `vector_store_query`, `multimodal_caption_embed` |
| Retrieval | `hybrid_retrieve`, `parent_doc_retriever`, `query_rewrite`, `hyde_generate`, `rag_rerank`, `contextual_compress` |
| Generation / eval | `prompt_assemble`, `rag_generate`, `citation_attach`, `kg_light_extract`, `rag_eval` |

## Vision Plugins — `PluginPackage/Vision/` (23 nodes)

| Group | node_types |
|---|---|
| Data | `vision_dataset_ingest`, `vision_dataset_health`, `vision_label_convert`, `vision_train_val_split`, `vision_augment`, `vision_hard_negative_mine`, `yolo_dataset_yaml_build`, `annotation_export_coco`, `annotation_export_yolo` |
| YOLO (ultralytics optional) | `yolo_train`, `yolo_resume_train`, `yolo_hyperparam_search`, `yolo_val`, `yolo_predict`, `yolo_track`, `yolo_export`, `yolo_nms_postprocess`, `yolo_task_detect`, `yolo_task_segment`, `yolo_task_pose`, `yolo_task_obb_classify` |
| Runtime | `onnx_runtime_infer`, `tensorrt_infer` |

## TinyML Plugins — `PluginPackage/TinyML/` (23 nodes)

| Group | node_types |
|---|---|
| Data / features | `mcu_dataset_ingest`, `mcu_dataset_health`, `mcu_label_taxonomy`, `mcu_window`, `mcu_mfcc`, `mcu_spectrogram`, `mcu_feature_pipeline`, `tinyml_ptq_calib_builder` |
| Train / convert | `mcu_model_zoo`, `mcu_train`, `micro_speech_pipeline`, `tflm_quantize`, `tflm_convert`, `tflm_op_support_check`, `tflm_host_sim`, `mcu_arena_estimator`, `cmsis_nn_optimize_flag`, `ethos_u_vela_compile`, `executorch_export` |
| Deploy (host-side receipts) | `cmsis_pack_exporter`, `mcu_glue_stubs`, `mcu_flash_ota`, `mcu_ondevice_metrics` |

## Video (10) and WakeWord (5) — experimental, non-manifest

Video: `video_ingest`, `video_quality_gate`, `frame_sample`, `scene_detect`, `clip_segment`, `action_classify`, `video_caption`, `video_embed`, `av_align`, `video_exporter`.
WakeWord: `wakeword_data_gen`, `wakeword_feature_extract`, `wakeword_train`, `wakeword_infer`, `wakeword_export_onnx`.

## Recent behavior/config changes

### Agents

- **`hitl_approve`** — approval is never read from the gated payload. On run the node writes `{decision_dir}/{run_id}__{gate_id}.request.json` (random `request_id`, `approver_roles`, `reason_required`, `timeout_s`, `decision_path`, `status`) and polls `{decision_dir}/{run_id}__{gate_id}.decision.json` every `poll_interval_s` (default 2.0) until `timeout_s` (default 3600; 0 = check once). Decision body: `{"request_id", "approved": true, "approver", "role", "reason"}`. It is honoured only if `request_id` matches (stale files are ignored), `approver` is non-empty, `role` is in `approver_roles` (when non-empty; default `[]` = any named approver), and `reason` is present when `reason_required` (default true). `approved` must be the JSON literal `true`. Timeout / invalid / denial → `rejected` port (payload + reason); the request file is updated with `status` + `outcome`. Defaults: `gate_id="hitl_approve"` (set to the graph node id), `decision_dir="workspace/artifacts/agents/hitl_approve/decisions"`. `unattended_approve=true` (default false) passes with no human and writes a `.unattended.json` receipt. Run/gate ids are sanitised to `[A-Za-z0-9_.-]`.
- **`mcp_tool_call`** — `server` must be `graphyn`. `tool_allowlist` (default `[]`) is required: empty refuses every call; the tool must be listed. `allow_mutating` (default false) must also be true for state-changing / credential / execution tools (an explicit list plus prefixes such as `create_`, `update_`, `delete_`, `run_`, `execute_`, `install_`, `set_`, `send_`, `export_` …). `tool_name` pins the tool; a different name from the `tool_name` port or `input.tool` raises. MCP auth runs `app.mcp.auth.check_auth` on the arguments (`_meta.auth_token` against `GRAPHYN_API_TOKEN`; fail closed when auth is required). `timeout_s` default 60 (0 = no limit). Handler errors come back as `ToolCallResult(ok=False, error=…)`.
- **`guardrail_filter`** — `policies` default `["pii", "secret"]` (empty also means pii+secret); also available: `profanity`, `jailbreak`; unknown policy names raise. `action` = `block` (default, raises) / `redact` (replace matches with `[redacted]`, keep structure) / `flag` (pass through + `violations`); an unknown action fails closed as `block`. Scans every string in nested dicts/lists, keys included.
- **`tool_router`** — `tools`: names or `{name, keywords[]}`. An explicit `tool` in the input must match a registered name (case-insensitive), or the request goes to `unmatched`. Otherwise the longest word-boundary keyword/name match wins; negated mentions ("don't search") are skipped; a tie between tools → `unmatched` (ambiguous). `strict` (default true); `strict=false` falls back to the first tool only for the keyword path.
- **`output_schema_validate`** — now does real validation (`stub` default false). The input may be a dict, JSON string, ```` ```json ```` fenced text or a ChatMessage (`content` is parsed). Output: `output` = the parsed JSON value when valid, else `None`; `errors` = `list[str]` of `$.path: message`. `strict` (default true) raises on any error. Schema subset: `type` (incl. lists), `required`, `properties`, `additionalProperties`, `items`, `enum`, `const`, `min/maxLength`, `pattern`, `minimum/maximum`, `min/maxItems`, `anyOf/oneOf/allOf`; bool is never a number.
- **`prompt_template`** — `engine` = `format` (default; `str.format` with named fields only, no positional or `_`-prefixed field access, missing variables raise), `jinja` (Jinja2 `SandboxedEnvironment` + `StrictUndefined`; without jinja2 installed only `{{ var }}` / `{{ a.b }}` works and `{% %}` raises), `fstring` (alias of `format`). An empty `template` passes the input through as text.
- **`agent_loop`** — extractive only; no generative planning. `model`, `api_secret_name`, `tool_allowlist` are reserved and ignored. `max_steps` (default 8) caps the context windows scanned. Result metadata: `llm_called=false`, `tools_called=[]`.

### MLOps / RAG / Vision

- **`canary_gate`** — baseline comes from the `baseline` input port, else `baseline_value` (default none). A wired baseline with a missing / non-finite metric → hold. `higher_is_better` (default true) sets the direction: regression = baseline − value (or value − baseline when false); hold when regression > `max_regression` (default 0.02). Also `min_value` (default 0.0) / `max_value`. A missing or non-finite metric → hold.
- **`drift_detect`** — `method` = `psi` (default; reference-quantile bins plus out-of-range tail bins) or `ks` (two-sample KS D, p-values reported); `bins` default 10 (must be ≥ 2); `split` = `all` (default, concatenates train/val/test) / `train` / `val` / `test` for DatasetArtifacts; `threshold` default 0.2. Score = max per-feature value; features are matched by name.
- **`ab_assign`** — deterministic sha256 of `{experiment_key}:{unit_id}`. `variants` default `["control","treatment"]`, `weights` default `[0.5,0.5]` (empty = uniform; must be non-negative and sum to more than 0). Record input reads `unit_id_field` (default `unit_id`); a missing field raises. Collections and booleans are rejected.
- **`feature_store_write` / `feature_store_read`** — each write appends a timestamped version per entity. `entity_keys` default `["id"]` (a missing field raises; `[]` = content-hash key). `event_time_field` (default empty = write time) sets the version timestamp. `feature_store_read.as_of` (ISO-8601, default empty = latest) returns each entity's latest version at or before that time.
- **`dataset_versioner`** (Common) — `overwrite` default false: an existing `{output_dir}/{version_tag}` whose `lineage.json` hash differs raises `FileExistsError`. Re-running identical data is always allowed.
- **`yolo_val`** — `device` = `cpu` (default) / `auto` (ultralytics picks) / `cuda` / `mps`. Note: it runs ultralytics *predict* over the dataset and reports `mean_score` / `n` (not mAP), with a contrast-blob fallback when ultralytics or a model is missing.
- **`rag_rerank`** — `backend` default `bm25` (lexical, no deps); `cross_encoder` needs sentence-transformers (`model_name_or_path`, `top_n` default 5).
- **`kg_light_extract`** — `backend` default `pattern` (regex triples); `llm` is declared but raises `NotImplementedError`.

### Audio / TinyML PCM decode

- **`_pcm` helper** — not in the Audio pack. A shared copy sits in `mcu_window`, `mcu_mfcc`, `mcu_spectrogram`, `mcu_feature_pipeline`, `mcu_dataset_ingest`, `micro_speech_pipeline` (TinyML), `wakeword_feature_extract`, `wakeword_infer` (WakeWord) and `av_align` (Video). It decodes AudioSample/dict, arrays/lists, WAV bytes or a file path to mono float PCM (mean downmix) and linearly resamples it to 16 kHz by default. Bare arrays are assumed to already be at the target rate; undecodable input raises `ValueError`. `mcu_window` and `mcu_dataset_ingest` resample to their `sample_rate` config (default 16000). `max_windows` (default 0 = unlimited) caps windows/frames per sample in `mcu_window`, `mcu_spectrogram` and `mcu_feature_pipeline`.
- **`stream_ingest`** — `source` now also accepts `rtp` / `rtsp`: `stream_url` (`rtp://`, `rtsp://`, `srt://`, `udp://` only; must have a host) is decoded with `ffmpeg` (required on PATH) under a per-scheme `-protocol_whitelist`, for `duration_s` seconds (0 = until EOS). URL credentials are redacted from outputs and errors.
- **`dataset_ingest`** — filesystem ingest now requires a non-empty `config.path` (it no longer falls back to CWD).

### Common

- **`python_code`** (defense-in-depth; still not a sandbox) — `import` is limited to `json` and `math`. Both resolve to curated wrappers (`json`: `loads`/`dumps`/`JSONDecodeError`; `math`: its public functions/constants), never the real modules. `re`, `datetime`, `itertools`, `functools`, `collections`, `decimal` and `statistics` are no longer importable. Relative, dotted, `*` and `_`-prefixed imports are rejected. The AST filter also rejects any `_`-prefixed attribute, `.format()` / `.format_map()` calls, and any access to exec/spawn names (`system`, `popen`, `exec*`, `spawn*`, `fork`, `kill` …), `modules` / `builtins` / `codecs` / `import_module`, frame/code introspection (`gi_frame`, `f_globals`, `tb_frame`, `co_code` …) and `mro`. `allow_network` (default false) is now reserved: it no longer unlocks `httpx` / `requests` / `urllib` / `aiohttp`, and setting it true raises when `GRAPHYN_HTTP_EGRESS_MODE=restricted`. `open()` still requires `allowed_paths`. No new time or memory limits were added.
- **Secret-name resolution** — these nodes resolve config-supplied secret names through `app.core.trust.secrets.resolve_secret`: `http_request.auth_env`, `http_webhook.hmac_env`, `vector_store_write.pg_dsn_secret` / `vector_store_query` (store `dsn_secret`, fallback `PGVECTOR_DSN`), `rag_notion_connector.secret_name` (default `NOTION_API_TOKEN`), `rag_slack_connector.secret_name` (default `SLACK_BOT_TOKEN`), `speaker_separator.auth_token_env` (default `HUGGINGFACE_TOKEN`) and `asr_transcribe` provider keys. The Graphyn secret store is checked first. Process env is read only for secret-shaped names (`*_API_KEY`, `*_APIKEY`, `*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `*_DSN`, `*_URL`, `*_URI`) that do not start with `GRAPHYN_`, or for names in `GRAPHYN_SECRET_ENV_ALLOWLIST` (comma-separated). Otherwise it returns empty and the node fails closed.
- **`structured_llm`** (`provider=openai_compat`) — resolves key and endpoint via `app.core.ml.llm_client.resolve_llm_endpoint` (precedence: `connection_id` → workspace default → secret/env `OPENAI_API_KEY`; with a Groq `base_url`, `GROQ_API_KEY` is a fallback). A key is sent only to its bound base URL: the connection's `base_url`, else `OPENAI_BASE_URL` / `https://api.openai.com/v1`. A node `base_url` that differs is refused, except for env/secret keys whose host is in `GRAPHYN_LLM_BASE_URL_ALLOWLIST`. Example: Groq with env `GROQ_API_KEY` needs `GRAPHYN_LLM_BASE_URL_ALLOWLIST=api.groq.com`, or a connection whose `base_url` is Groq. A node `base_url` is also egress-checked before any credential is resolved. Note: if `OPENAI_API_KEY` is also set, it is resolved before `GROQ_API_KEY`.

## Capability Matrix

| node_type | GPU Req | Edge | Streaming | Realtime | Deterministic | Cacheable |
|---|---|---|---|---|---|---|
| `dataset_ingest` | No | No | Yes | No | Yes | Yes |
| `stream_ingest` | No | Yes | Yes | Yes | No | No |
| `audio_conditioner` | No | Yes | No | Yes | Yes | Yes |
| `audio_quality_gate` | No | Yes | No | No | Yes | Yes |
| `audio_annotator` | No | Yes | No | No | Yes | Yes |
| `alignment_node` | No | No | No | No | Yes | Yes |
| `segmenter` | No | Yes | Yes | Yes | Yes | Yes |
| `augmentation_pipeline` | No | Yes | No | No | No | No |
| `speech_enhancer` | Optional | Yes (CPU) | No | Yes | No | Yes |
| `speaker_separator` | Optional | No | No | Yes | No | No |
| `environment_simulator` | No | No | No | No | No | No |
| `feature_frontend` | No | Yes | No | Yes | Yes | Yes |
| `stream_processor` | No | Yes | Yes | Yes | Yes | No |
| `audio_event_detector` | Optional | Yes (TFLite) | Yes | Yes | Yes | No |
| `audio_classifier` | Optional | Yes (TFLite) | No | Yes | Yes | No |
| `speech_synthesizer` | Optional | No | No | Yes | No | No |
| `voice_converter` | Optional | No | No | Yes | No | No |
| `audio_generator` | Yes | No | No | No | No | No |
| `dataset_builder` | No | No | No | No | Yes | Yes |
| `model_builder` | Optional | No | No | No | No | No |
| `trainer` | Optional | No | No | No | No | No |
| `evaluator` | No | No | No | No | Yes | No |
| `edge_optimizer` | No | No | No | No | Yes | Yes |
| `realtime_inference` | Optional | Yes (TFLite) | Yes | Yes | Yes | No |
| `dataset_balancer` | No | No | No | No | No | No |
| `dataset_versioner` | No | No | No | No | Yes | Yes |
| `experiment_tracker` | No | No | No | No | Yes | Yes |
| `deployment_packager` | No | No | No | No | Yes | Yes |
| `embedding_generator` | Optional | No | No | No | Yes | Yes |
| `multimodal_fusion` | Optional | No | No | Yes | No | No |
| `asr_transcribe` | No | Yes | No | No | Yes | Yes |
| `pii_redact` | No | Yes | No | No | Yes | Yes |
| `structured_llm` | No | Yes | No | No | Yes | Yes |
| `eval_gate` | No | Yes | No | No | Yes | No |
| `http_webhook` | No | Yes | No | No | Yes | No |
| `doc_parse_chunk` | No | Yes | No | No | Yes | Yes |
| `caption_export` | No | Yes | No | No | Yes | No |
| `object_store` | No | Yes | No | No | Yes | No |
| `http_request` | No | Yes | No | No | Yes | No |
| `if_switch` | No | Yes | No | No | Yes | Yes |
| `set_map` | No | Yes | No | No | Yes | Yes |
| `json_transform` | No | Yes | No | No | Yes | Yes |
| `schedule_trigger` | No | Yes | No | No | Yes | No |
| `python_code` | No | Yes | No | No | Yes | No |
| `error_catch` | No | Yes | No | No | Yes | No |
| `merge` | No | Yes | No | No | Yes | Yes |
| `wait_delay` | No | Yes | No | No | Yes | No |
| `csv_table` | No | Yes | No | No | Yes | No |

## Installing Nodes

```python
from app.core.plugins.manager import PluginManager

manager = PluginManager()
manager.install("PluginPackage/Audio/audio_conditioner/", upgrade=True)
manager.install("PluginPackage/Audio/segmenter/", upgrade=True)
manager.load_enabled_plugins()
# nodes are now available in the registry
```

```bash
graphyn plugin install PluginPackage/Audio/audio_conditioner/
graphyn plugin install PluginPackage/Common/dataset_builder/
```
