# Template / plugin audit (2026-09-02 IST)

Evidence from PluginPackage AST, `isolated_schema`, CompatibilityChecker, and
`unit_test/core/ir/test_example_templates.py` (104 passed including every
`examples/**/*.graph.json`).

## 1. PluginPackage runtimes

Default runtime is **inprocess** when `plugin.toml` omits `runtime`.

| Plugin | runtime | node_types (manifest / AST) |
|---|---|---|
| Audio/alignment_node | inprocess (default) | alignment_node |
| Audio/audio_annotator | inprocess | audio_annotator |
| Audio/audio_classifier | inprocess | audio_classifier |
| Audio/audio_conditioner | inprocess | audio_conditioner |
| Audio/audio_event_detector | inprocess | audio_event_detector |
| Audio/audio_exporter | inprocess | audio_exporter |
| Audio/audio_generator | inprocess | audio_generator |
| Audio/audio_quality_gate | inprocess | audio_quality_gate |
| Audio/augmentation_pipeline | inprocess | augmentation_pipeline |
| Audio/dataset_ingest | inprocess | dataset_ingest |
| Audio/environment_simulator | inprocess | environment_simulator |
| Audio/feature_frontend | inprocess | feature_frontend |
| Audio/segmenter | inprocess | segmenter |
| Audio/speaker_separator | inprocess | speaker_separator |
| Audio/speech_enhancer | inprocess | speech_enhancer |
| Audio/speech_synthesizer | inprocess | speech_synthesizer |
| Audio/stream_ingest | inprocess | stream_ingest |
| Audio/stream_processor | inprocess | stream_processor |
| Audio/voice_converter | inprocess | voice_converter |
| Common/asr_transcribe | inprocess | asr_transcribe |
| Common/caption_export | inprocess | caption_export |
| Common/csv_table | inprocess | csv_table |
| Common/dataset_balancer | inprocess | dataset_balancer |
| Common/dataset_builder | inprocess | dataset_builder |
| Common/dataset_versioner | inprocess | dataset_versioner |
| Common/deployment_packager | inprocess | deployment_packager |
| Common/doc_parse_chunk | inprocess | doc_parse_chunk |
| Common/edge_optimizer | **isolated** | edge_optimizer |
| Common/embedding_generator | inprocess | embedding_generator |
| Common/error_catch | inprocess | error_catch |
| Common/eval_gate | inprocess | eval_gate |
| Common/evaluator | inprocess | evaluator |
| Common/experiment_tracker | inprocess | experiment_tracker |
| Common/http_request | inprocess | http_request |
| Common/http_webhook | inprocess | http_webhook |
| Common/if_switch | inprocess | if_switch |
| Common/json_transform | inprocess | json_transform |
| Common/merge | inprocess | merge |
| Common/multimodal_fusion | inprocess | multimodal_fusion |
| Common/object_store | inprocess | object_store |
| Common/pii_redact | inprocess | pii_redact |
| Common/python_code | inprocess | python_code |
| Common/realtime_inference | **isolated** | realtime_inference |
| Common/schedule_trigger | inprocess | schedule_trigger |
| Common/set_map | inprocess | set_map |
| Common/structured_llm | inprocess | structured_llm |
| Common/trainer | **isolated** | trainer, model_builder |
| Common/wait_delay | inprocess | wait_delay |

Isolated plugins that must not `exec_module` on the host: **trainer**
(`trainer`, `model_builder`), **edge_optimizer**, **realtime_inference**.

## 2. Plugin-local PortDataType classes (`types.py`, not `app.models`)

Defined in plugin `types.py` (not re-exported from `app.models`):

| Type | Plugin | Flows into isolated node? |
|---|---|---|
| WordTiming, Transcript | asr_transcribe | No (inprocess ASR / PII / LLM) |
| CaptionExportResult | caption_export | No |
| CsvTableResult | csv_table | No |
| Chunk | doc_parse_chunk | No |
| EmbeddingVector | embedding_generator | **No** — no graph edge to trainer / edge_optimizer / realtime_inference |
| ErrorPayload | error_catch | No |
| EvalReport | eval_gate | No |
| ExperimentArtifact | experiment_tracker | **No** — tracker is inprocess; isolated trainer does not consume it |
| HttpResponse | http_request | No |
| WebhookReceipt | http_webhook | No |
| BranchResult | if_switch | No |
| JsonDocument | json_transform | No |
| MergedPayload | merge | No |
| ObjectRef, ObjectList | object_store | No |
| PiiFinding, RedactionAudit | pii_redact | No |
| CodeResult | python_code | No |
| TickEvent | schedule_trigger | No |
| MappedPayload | set_map | No |
| StructuredDocument | structured_llm | No |
| DelayReceipt | wait_delay | No |

**Promoted / already platform (`app.models`):** AudioSample, DataSample,
DatasetArtifact (promoted earlier this branch; plugin `dataset_builder/types.py`
re-exports), DeploymentArtifact, FeatureArray, ModelArtifact, PredictionResult,
TensorBatch, TFLiteArtifact.

### Isolated I/O vs neighbors (this fix)

| Isolated node | Input | Output | Neighbor |
|---|---|---|---|
| model_builder | **DatasetArtifact** (was `object`) | `object` (compiled Keras/Torch module — not a PortDataType) | dataset_builder.output |
| trainer | model=`object`, dataset=**DatasetArtifact** (was `object`) | ModelArtifact | model_builder + dataset_builder; evaluator.model_artifact |
| edge_optimizer | ModelArtifact | DeploymentArtifact | evaluator.output |
| realtime_inference | **list[FeatureArray]** (was bare `list`) | **list[PredictionResult]** (was bare `list`) | feature_frontend.output |

Also tightened inprocess DatasetArtifact chain: evaluator.dataset,
dataset_balancer in/out, dataset_versioner in/out, dataset_builder.input
`list[FeatureArray]`.

`recast_plugin_types` already remaps `_graphyn_plugin_*` instances onto
`app.models` **by class `__name__`**. No extra recast map entries were required
after DatasetArtifact promotion. EmbeddingVector / ExperimentArtifact are
**not** promoted (they do not enter isolated workers).

Evidence: `unit_test/core/plugins/test_isolated_schema.py` (AST + stub Config
fields + platform ports) and
`test_dep_isolation.py::test_recast_plugin_dataset_artifact_pickle_roundtrip`.

## 3. Isolated stub Config

AST Config fields for trainer, model_builder, edge_optimizer, realtime_inference
are rebuilt on host stubs (`isolated_schema` + `plugin.toml` `config_schema`).
`test_isolated_stub_config_and_ports_match_ast` loads each isolated
PluginPackage with mocked venv `ensure` and asserts:

- every AST Config field is on the stub (`extra_forbidden` cannot drop
  `architecture=ds_cnn`, `epochs`, `model_path`, …)
- port `data_type` matches AST-resolved platform types

## 4. Graph IR + Config + edges

Loader: IR `load_ir` → PluginPackage AST `Config.model_validate` (current
source; isolated registry stubs used when they already contain AST fields) →
CompatibilityChecker on every edge.

**59 / 59 `examples/**/*.graph.json` VALIDATE PASS.** No extra_forbidden, no
unknown ports, no incompatible edges against current schemas.

Pytest: `test_all_example_graph_files_validate_against_registry` plus starter
templates, UI-discovered examples, and `pipeline_train_ml`.

## 5. Template default backends vs optional pip

| Node / default | Optional dep | Action |
|---|---|---|
| speech_enhancer Config default was `auto` (tries DeepFilterNet/torch) | torch, deepfilternet | **Default changed to `spectral`** (noisereduce already in requirements). Templates already set `backend=spectral`. Did **not** add torch/deepfilternet. |
| audio_conditioner `normalize_method=lufs` (podcast-leveling) | pyloudnorm | **Pinned `pyloudnorm==0.1.1`** in requirements.txt / setup.py (CPU). |
| segmenter `mode=vad` (audio-quality-check) | webrtcvad | **Pinned `webrtcvad==2.0.10`** in requirements.txt / setup.py (CPU, needs C compiler — Docker already has `build-essential`). |
| pii_redact `engine=auto` | presidio | Falls back to regex if Presidio missing — **no change**. |
| trainer / model_builder / edge_optimizer / realtime_inference | tensorflow/keras/torch/onnx | **Not** added to base image. Run-blockers below. |
| dataset_builder | scikit-learn (required by plugin, not optional) | Installed via plugin auto-install into host; not in base requirements. Train graphs still blocked on keras. |

## 6. Table: template/example → validate → remaining run-blockers

Run-blockers are **execution** issues after schema validation (missing datasets,
keras/GPU/TFLite, live API keys). Schema/edge validation is PASS for all.

| Graph | Validate | Remaining run-blockers |
|---|---|---|
| templates/audio-classification.graph.json | PASS | missing data `examples/02_speech_commands/data/go` |
| templates/audio-quality-check.graph.json | PASS | missing data `…/data/go` (webrtcvad now in base image) |
| templates/basic-wakeword.graph.json | PASS | none if `examples/01_wake_word/data/wake_word` present (E2E synthetic WAVs) |
| templates/call-analytics.graph.json | PASS | none (mock ASR/LLM/webhook) |
| templates/captions.graph.json | PASS | none (mock ASR) |
| templates/doc-rag-ingest.graph.json | PASS | none (`object_store` backend=local) |
| templates/meeting-crm.graph.json | PASS | none (mock + regex PII) |
| templates/podcast-leveling.graph.json | PASS | missing data `…/data/go` (pyloudnorm now in base image) |
| templates/speech-recognition.graph.json | PASS | missing data `…/data/go` |
| 01_wake_word/pipeline.graph.json | PASS | none if wake_word data present |
| 01_wake_word/pipeline_background.graph.json | PASS | missing data `…/data/background` |
| 02_speech_commands/pipeline*.graph.json (6) | PASS | missing Speech Commands shards under `examples/02_speech_commands/data/*` |
| 03_environmental_sounds/pipeline*.graph.json (5) | PASS | missing data under `examples/03_environmental_sounds/data/*` |
| 04_speaker_verification/pipeline*.graph.json (6) | PASS | missing data under `examples/04_speaker_verification/data/*` |
| 05_speech_enhancement/pipeline*.graph.json (2) | PASS | missing data `…/data/clean_speech` |
| 06_speech_commands_e2e/pipeline_preprocess*.graph.json (6) | PASS | missing Speech Commands data |
| 06_speech_commands_e2e/pipeline_train_ml.graph.json | PASS | missing preprocess output dataset; **keras/tensorflow** (isolated venv optional deps); evaluator matplotlib/seaborn; **edge_optimizer TFLite** |
| 06_speech_commands_e2e/pipeline_infer.graph.json | PASS | missing data + missing `output/tflite/model.tflite`; TFLite/ONNX/torch runtime |
| 09_parallel_execution/pipeline.graph.json | PASS | hardcoded `/home/meritech/Desktop/newAudio3/…` paths (missing data) |
| 10_resumable_pipeline/pipeline.graph.json | PASS | same absolute host paths |
| 12_conditional_branching/pipeline.graph.json | PASS | same absolute host paths |
| 18_pipeline_composition/augmentation.graph.json | PASS | none (no ingest path) |
| 18_pipeline_composition/composed.graph.json | PASS | absolute host ingest path |
| 18_pipeline_composition/preprocessing.graph.json | PASS | absolute host ingest path |
| 19_capability_scheduling/edge_inference.graph.json | PASS | missing absolute wav path |
| 22_call_analytics/pipeline.graph.json | PASS | none (mock) |
| 22_call_analytics/pipeline.live.graph.json | PASS | Deepgram + openai_compat keys; live HTTP webhook |
| 23_meeting_crm/pipeline.graph.json | PASS | none (mock) |
| 23_meeting_crm/pipeline.live.graph.json | PASS | openai_compat keys; live webhook |
| 24_captions/pipeline.graph.json | PASS | none (mock) |
| 24_captions/pipeline.live.graph.json | PASS | Deepgram API key |
| 25_doc_rag_ingest/pipeline.graph.json | PASS | none |
| 25_doc_rag_ingest/pipeline.live.graph.json | PASS | none (local object_store) |
| 26_nightly_compliance/pipeline.graph.json | PASS | none (mock) |
| 26_nightly_compliance/pipeline.live.graph.json | PASS | openai_compat + live HTTP |
| 27_github_triage/pipeline.graph.json | PASS | none (mock) |
| 27_github_triage/pipeline.live.graph.json | PASS | live HTTP + openai_compat |
| 28_asr_eval_merge/pipeline.graph.json | PASS | none (mock) |
| 28_asr_eval_merge/pipeline.live.graph.json | PASS | openai_compat ASR |

## 7. What was not done

- Did not add torch / DeepFilterNet / TensorFlow / Keras to the Docker base image.
- Did not promote EmbeddingVector or ExperimentArtifact (no isolated inbound edge).
- Absolute `/home/meritech/...` example paths were not rewritten (run-blocker:
  missing data, not schema).
