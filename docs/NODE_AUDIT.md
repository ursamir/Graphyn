# Node / Plugin Config Audit

> Generated 2026-09-08 (Asia/Calcutta). Scope: all `48` PluginPackage plugins with `plugin.toml`.
>
> Goal: every node is self-sufficient for Builder + MCP — complete titles/descriptions/enums,
> honest defaults, secrets via env names, accurate edge flags, plugin-owned schema overlays.

## Method

Stakeholder scores (1–5) use heuristics + spot checks:

| Stakeholder | Looks for |
|---|---|
| Workflow author | labels, enums, placeholders, required vs optional |
| ML engineer | real training/eval/ASR/export knobs, honest defaults |
| Ops/SRE | timeouts, retries, paths, fail-closed errors |
| Security | secrets via env names, python_code trust, no secret-in-IR |
| Edge | `supports_edge`, packager/optimizer accuracy |
| Agent/MCP | schema complete for tool callers |
| UI Builder | `plugin.toml` `[config_schema]` + Field titles/descriptions |

## Summary table

| Plugin | Fields | Weak py | Weak toml | Miss toml | Edge | Author | MCP/UI | Sec | Notes |
|---|---:|---:|---:|---|---|---:|---:|---:|---|
| `audio-quality-gate` | 15 | 2 | 2 | — | True | 4 | 4 | 5 |  |
| `speech-enhancer` | 7 | 2 | 2 | — | False | 4 | 4 | 5 |  |
| `evaluator` | 6 | 1 | 1 | — | False | 4 | 4 | 5 |  |
| `realtime-inference` | 8 | 1 | 1 | — | True | 4 | 4 | 5 |  |
| `stream-processor` | 6 | 1 | 1 | — | True | 4 | 4 | 5 |  |
| `alignment-node` | 6 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `asr-transcribe` | 5 | 0 | 0 | — | True | 5 | 5 | 5 | Real providers only (openai_compat/assemblyai/deepgram). |
| `audio-annotator` | 6 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `audio-classifier` | 4 | 0 | 0 | — | True | 5 | 5 | 5 | Backends enumerated; top_k clarified. P2: confidence_threshold filter. |
| `audio-conditioner` | 17 | 0 | 0 | — | True | 5 | 5 | 5 | Production knobs complete (LUFS/compress/limiter). Descriptions enriched. |
| `audio-event-detector` | 7 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `audio-exporter` | 6 | 0 | 0 | — | False | 5 | 5 | 5 | Added format=wav enum; split ratios / append clarified. |
| `audio-generator` | 8 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `augmentation-pipeline` | 2 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `caption-export` | 4 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `csv-table` | 3 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `dataset-balancer` | 6 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `dataset-builder` | 6 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `dataset-ingest` | 13 | 0 | 0 | — | False | 5 | 5 | 5 | Source-type enum + HF columns + integrity/dedupe documented. |
| `dataset-versioner` | 4 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `deployment-packager` | 5 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `doc-parse-chunk` | 4 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `edge-optimizer` | 6 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `embedding-generator` | 6 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `environment-simulator` | 9 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `error-catch` | 3 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `eval-gate` | 4 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `experiment-tracker` | 5 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `feature-frontend` | 15 | 0 | 0 | — | True | 5 | 5 | 5 | FFT/mel/MFCC/delta knobs documented; fixed_length clarified. |
| `http-request` | 12 | 0 | 0 | — | True | 5 | 5 | 5 | Real http only; auth via env/secret name. |
| `http-webhook` | 6 | 0 | 0 | — | True | 5 | 5 | 2 |  |
| `if-switch` | 3 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `json-transform` | 3 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `merge` | 2 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `multimodal-fusion` | 6 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `object-store` | 7 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `pii-redact` | 2 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `python-code` | 3 | 0 | 0 | — | True | 5 | 5 | 5 | Trust model documented; allowlist + allow_network Off by default. |
| `schedule-trigger` | 2 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `segmenter` | 9 | 0 | 0 | — | True | 5 | 5 | 5 | Modes enumerated; VAD/silence/event thresholds documented. |
| `set-map` | 4 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `speaker-separator` | 8 | 0 | 0 | — | False | 5 | 5 | 4 | P0: auth_token_env added; inline auth_token deprecated+exclude. |
| `speech-synthesizer` | 7 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `stream-ingest` | 10 | 0 | 0 | — | True | 5 | 5 | 5 |  |
| `structured-llm` | 7 | 0 | 0 | — | True | 5 | 5 | 5 | openai_compat only; schema widget=json. |
| `trainer` | 16 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `voice-converter` | 4 | 0 | 0 | — | False | 5 | 5 | 5 |  |
| `wait-delay` | 2 | 0 | 0 | — | True | 5 | 5 | 5 |  |

## P0 / P1 / P2

### P0 (fixed this pass)

- **Security — speaker-separator**: added `auth_token_env` (default `HUGGINGFACE_TOKEN`); deprecated inline `auth_token` remains `exclude=True` + secret widget; runtime resolves via secrets/env first.
- **Catalog-wide weak Field/plugin.toml copy**: enriched titles/descriptions/widgets across ~48 plugins (path-ish titles, On/Off boolean semantics, JSON widgets).
- **Enum honesty**: restored `One of: …` descriptions for Literal/enum fields (providers, backends, modes, formats).
- **HTTP / ASR / LLM**: verified still real-only (`provider` enums have no mock/fake).
- **audio-exporter**: declared `format` = `wav` only (matches runtime).

### P1 (fixed this pass)

- Priority audio nodes (`audio_conditioner`, `segmenter`, `feature_frontend`, `dataset_ingest`, `audio_exporter`, `audio_classifier`): production knobs documented in Config + `plugin.toml`.
- Workflow nodes (`http_request`, `http_webhook`, `if_switch`, `set_map`, `structured_llm`, `asr_transcribe`): auth/timeout/retry/schema copy aligned for Builder + MCP.
- Restored lost empty-object `default = {}` entries in several `plugin.toml` overlays after enrichment.

### P2 (remaining)

- **audio-classifier**: optional `confidence_threshold` filter (runtime change) — not added this pass.
- **audio-exporter**: FLAC/Opus export formats — not supported yet; schema correctly admits `wav` only.
- **caption-export `formats`**: still a free-form list; could become a multi-select enum of `srt|vtt|json`.
- **trainer**: deeper Keras/PyTorch hyperparams (optimizer/scheduler/loss) remain intentionally limited (out of scope: full trainer rewrite).
- **Progressive disclosure**: no `ui.group` / advanced-section metadata yet in `plugin.toml` (Builder shows flat forms).
- **WakeWord package**: separate layout (not all nodes use per-node `plugin.toml` Config overlays like Common/Audio).
- **stream-ingest device_id**: clarify sentinel for "default device" across OSes.
- A few boolean titles still terse; On/Off chrome is in `ConfigFieldEditor` regardless.

## Worst nodes before this pass (by weak Field descriptions)

http-request, segmenter, feature-frontend, audio-quality-gate, stream-ingest, environment-simulator, audio-conditioner, structured-llm, speaker-separator, audio-generator, audio-event-detector, set-map, http-webhook, dataset-ingest.

## Verification

- Prefer plugin-owned schema: `plugin.toml` `[config_schema.<node>]` overlays Pydantic via `app.core.nodes.plugin_ui.overlay_plugin_ui`.
- Targeted unit tests: `unit_test/plugins/audio/*`, `unit_test/plugins/common/test_{http_request,asr_transcribe,structured_llm,if_switch,set_map}.py`.

