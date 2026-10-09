# Template sweep

Tip `6978329f529c59567fdfa4397c5bea5a6b1c9099` · 2026-10-08 IST · live API Mode A.

## Headline

- File-based templates found: **129** (98 under `examples/**`, 31 under `workspace/configs/templates/**`).
- Status (file templates): **Invalid 71**, **Validates-only 38**, **Runs 17**, **Needs-external 3**
- **Every Invalid template is invalid because it references node types from packs removed on this branch** (no schema/IR errors otherwise).
- Marketplace catalog (`GET /pipeline-templates`, total 3032): all 3032 materialize (HTTP 200) but only **112 (3.7%) validate** against the live registry. The catalog advertises ~2,900 templates that cannot run on this branch. Unit test `full_catalog_validate_ge_95` fails for the same reason.
- Executed: 24 template runs (+variants) via live API with outputs redirected to the review sandbox, trainer epochs capped at 2, `append=false`. Mode B placement template (ex29) ran in Mode A with placement ignored — Mode B not verifiable.
- Marketplace seeds ship with empty required config (to/url/ingest path) — they validate but fail at run time until the user fills config: treated as Validates-only / Needs-external.

## Executed runs

| Template | Run ID | Status | Elapsed s | Error |
|---|---|---|---|---|
| ex01-wake-word | `3e8f241044164086b5bf843f22fba79c` | succeeded | 34.6 |  |
| ex02-speech-commands | `cca7f7a7aba5440f937774457e125f71` | succeeded | 50.3 |  |
| ex03-env-sounds | `2571b9073fb04418a122a5962d8257e0` | succeeded | 6.1 |  |
| ex05-speech-enh-degraded | `749287c789f141ad9bad03c85c1a28b4` | succeeded | 6.0 |  |
| ex06-infer | `9accbd0c25764b869b86918da16c16fc` | succeeded | 4.0 |  |
| ex06-train-asis | `2704e3e4bf4e4053a27f1fbf5f535658` | failed | 2.0 | DatasetIngestNode: Dataset 'workspace/datasets/output/audio_export/latest' has not been produced yet (missing or empty). It is written by an |
| ex09-parallel | `4c1e00cf832a41cf86bbcc4b082c3af8` | succeeded | 16.1 |  |
| ex10-resumable | `11c4f4c5341d471c89ea17d46fc059f4` | succeeded | 8.1 |  |
| ex18-preprocessing | `a2b2c36cc78a40058d1dc35c7a49efda` | succeeded | 2.0 |  |
| ex29-distributed-placement | `1c786d066b10474e8ba73a0ee603f01e` | succeeded | 2.0 |  |
| ex30-edge-deploy | `5895848b9e454ab7a18e18de6c408bb3` | failed | 2.0 | FileNotFoundError: EdgeOptimizerNode: model not found at 'workspace/artifacts/models/saved_model' |
| tpl-audio-classification | `894d1317c2bb4ef38ca612e086bc02e4` | succeeded | 8.0 |  |
| tpl-audio-quality-check | `3a22e4db46144ca98de5ed88c35f3bb3` | succeeded | 4.0 |  |
| tpl-basic-wakeword | `d4db881cf5a642a081d08af7ad9cf837` | succeeded | 2.1 |  |
| tpl-speech-recognition | `15b8957f929649099a875ce42a563e1f` | succeeded | 6.1 |  |
| tpl-e2e-prepare | `d0f764318bec4795af9b54ef6114ff95` | succeeded | 46.2 |  |
| ex06-train-chained | `10b707ec403241f5af1db75a2ea1692b` | succeeded | 66.3 |  |
| mkt-agents-email-alert | `fd8bdb40484046808bbaf8afcac7086e` | failed | 2.0 | send_email: recipient 'to' is required. |
| mkt-agents-llm-local-chat | `702c0c4aab5b4956940142fe9bb4fc0f` | succeeded | 2.0 |  |
| mkt-agents-notify-on-run | `59571860e1d1406fb175a867df1b9e56` | failed | 2.0 | HttpWebhookNode: config.url (or connection_id) is required (completion callback URL). |
| mkt-audio-kws-automotive | `d381b94590254a669acad46f24ecec23` | failed | 2.0 | DatasetIngestNode: config.path is required for filesystem ingest. Empty path previously resolved to the process CWD and could load the entir |
| mkt-audio-kws-edge-tflite | `95eea4793acf444eac8e48ec8820e09f` | failed | 2.0 | DatasetIngestNode: config.path is required for filesystem ingest. Empty path previously resolved to the process CWD and could load the entir |
| mkt-common-branch-merge-error | `04ff6b0e4da44d3cb287101ad193c818` | succeeded | 2.0 |  |
| mkt-common-http-poll-transform | `497b017ac2e24a4bbea9b5fd12e45b3e` | failed | 2.0 | HttpRequestNode: config.url is required. |

## Marketplace catalog by pack

| Pack | Entries | Valid | % |
|---|---|---|---|
| RAG | 960 | 0 | 0.0 |
| TinyML | 926 | 0 | 0.0 |
| Vision | 695 | 0 | 0.0 |
| Audio | 182 | 72 | 39.6 |
| WakeWord | 98 | 0 | 0.0 |
| Agents | 66 | 30 | 45.5 |
| Video | 49 | 0 | 0.0 |
| MLOps | 30 | 0 | 0.0 |
| Common | 26 | 10 | 38.5 |

| Catalog status | Entries | Valid |
|---|---|---|
| seeded | 6 | 1 |
| alter-existing | 37 | 32 |
| proposed | 2862 | 79 |
| needs-api | 127 | 0 |

Top missing node types across catalog (count of templates):

- `mcu_dataset_ingest`: 806
- `mcu_dataset_health`: 780
- `cmsis_pack_exporter`: 715
- `text_embed`: 693
- `mcu_train`: 631
- `vector_store_write`: 630
- `mcu_arena_estimator`: 480
- `mcu_window`: 480
- `tflm_convert`: 480
- `mcu_glue_stubs`: 480
- `rag_generate`: 477
- `mcu_label_taxonomy`: 468
- `yolo_val`: 456
- `artifact_checksum`: 448
- `citation_attach`: 435
- `yolo_train`: 396
- `tflm_host_sim`: 348
- `rag_rerank`: 322
- `mcu_feature_pipeline`: 319
- `vision_dataset_ingest`: 319
- `prompt_assemble`: 315
- `tflm_quantize`: 307
- `yolo_export`: 276
- `vector_store_query`: 267
- `tinyml_ptq_calib_builder`: 246

## File templates (all)

| Source | Status | Run ID | Note |
|---|---|---|---|
| `examples/01_wake_word/pipeline.graph.json` | Runs | 3e8f241044164086b5bf843f22fba79c | 34.6s; overrides: ['audio_exporter_4.output_dir'] |
| `examples/01_wake_word/pipeline_background.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/02_speech_commands/pipeline.graph.json` | Runs | cca7f7a7aba5440f937774457e125f71 | 50.3s; overrides: ['audio_exporter_6.output_dir'] |
| `examples/02_speech_commands/pipeline_down.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/02_speech_commands/pipeline_go.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/02_speech_commands/pipeline_no.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/02_speech_commands/pipeline_stop.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/02_speech_commands/pipeline_up.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/03_environmental_sounds/pipeline.graph.json` | Runs | 2571b9073fb04418a122a5962d8257e0 | 6.1s; overrides: ['audio_exporter_5.output_dir'] |
| `examples/03_environmental_sounds/pipeline_bird.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/03_environmental_sounds/pipeline_cat.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/03_environmental_sounds/pipeline_happy.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/03_environmental_sounds/pipeline_house.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/04_speaker_verification/pipeline.graph.json` | Invalid | - | missing node types: audio_annotator |
| `examples/04_speaker_verification/pipeline_speaker_002.graph.json` | Invalid | - | missing node types: audio_annotator |
| `examples/04_speaker_verification/pipeline_speaker_003.graph.json` | Invalid | - | missing node types: audio_annotator |
| `examples/04_speaker_verification/pipeline_speaker_004.graph.json` | Invalid | - | missing node types: audio_annotator |
| `examples/04_speaker_verification/pipeline_speaker_005.graph.json` | Invalid | - | missing node types: audio_annotator |
| `examples/04_speaker_verification/pipeline_speaker_006.graph.json` | Invalid | - | missing node types: audio_annotator |
| `examples/05_speech_enhancement/pipeline.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/05_speech_enhancement/pipeline_degraded.graph.json` | Runs | 749287c789f141ad9bad03c85c1a28b4 | 6.0s; overrides: ['audio_exporter_5.output_dir'] |
| `examples/06_speech_commands_e2e/pipeline_infer.graph.json` | Runs | 9accbd0c25764b869b86918da16c16fc | 4.0s; overrides: none |
| `examples/06_speech_commands_e2e/pipeline_preprocess.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/06_speech_commands_e2e/pipeline_preprocess_down.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/06_speech_commands_e2e/pipeline_preprocess_go.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/06_speech_commands_e2e/pipeline_preprocess_no.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/06_speech_commands_e2e/pipeline_preprocess_stop.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/06_speech_commands_e2e/pipeline_preprocess_up.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/06_speech_commands_e2e/pipeline_train_ml.graph.json` | Runs | 10b707ec403241f5af1db75a2ea1692b | 66.3s; overrides: ["dataset_ingest_0:['path']", 'model_builder_0.output_path', 'trainer_0.output_path', 'trainer_0.epochs=2', 'evaluator_0.output_path', 'edge_o |
| `examples/09_parallel_execution/pipeline.graph.json` | Runs | 4c1e00cf832a41cf86bbcc4b082c3af8 | 16.1s; overrides: ['audio_exporter_yes.output_dir', 'audio_exporter_no.output_dir', 'audio_exporter_up.output_dir', 'audio_exporter_down.output_dir'] |
| `examples/10_resumable_pipeline/pipeline.graph.json` | Runs | 11c4f4c5341d471c89ea17d46fc059f4 | 8.1s; overrides: ['audio_exporter_5.output_dir'] |
| `examples/12_conditional_branching/pipeline.graph.json` | Invalid | - | missing node types: dataset_versioner |
| `examples/18_pipeline_composition/augmentation.graph.json` | Invalid | - | missing node types: dataset_versioner |
| `examples/18_pipeline_composition/composed.graph.json` | Invalid | - | missing node types: dataset_versioner |
| `examples/18_pipeline_composition/preprocessing.graph.json` | Runs | a2b2c36cc78a40058d1dc35c7a49efda | 2.0s; overrides: none |
| `examples/19_capability_scheduling/edge_inference.graph.json` | Invalid | - | missing node types: stream_ingest |
| `examples/22_call_analytics/pipeline.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `examples/22_call_analytics/pipeline.live.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `examples/23_meeting_crm/pipeline.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `examples/23_meeting_crm/pipeline.live.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `examples/24_captions/pipeline.graph.json` | Invalid | - | missing node types: asr_transcribe,caption_export |
| `examples/24_captions/pipeline.live.graph.json` | Invalid | - | missing node types: asr_transcribe,caption_export |
| `examples/25_doc_rag_ingest/pipeline.graph.json` | Invalid | - | missing node types: doc_parse_chunk |
| `examples/25_doc_rag_ingest/pipeline.live.graph.json` | Invalid | - | missing node types: doc_parse_chunk |
| `examples/26_nightly_compliance/pipeline.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `examples/26_nightly_compliance/pipeline.live.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `examples/27_github_triage/pipeline.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `examples/27_github_triage/pipeline.live.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `examples/28_asr_eval_merge/pipeline.graph.json` | Invalid | - | missing node types: asr_transcribe |
| `examples/28_asr_eval_merge/pipeline.live.graph.json` | Invalid | - | missing node types: asr_transcribe |
| `examples/29_distributed_placement/pipeline.graph.json` | Runs | 1c786d066b10474e8ba73a0ee603f01e | 2.0s; overrides: none |
| `examples/30_edge_deploy/pipeline.graph.json` | Validates-only | 5895848b9e454ab7a18e18de6c408bb3 | run failed (prerequisite/params): FileNotFoundError: EdgeOptimizerNode: model not found at 'workspace/artifacts/models/saved_model' |
| `examples/templates/audio-classification.graph.json` | Runs | 894d1317c2bb4ef38ca612e086bc02e4 | 8.0s; overrides: ['audio_exporter_4.output_dir'] |
| `examples/templates/audio-quality-check.graph.json` | Runs | 3a22e4db46144ca98de5ed88c35f3bb3 | 4.0s; overrides: ['audio_exporter_4.output_dir'] |
| `examples/templates/basic-wakeword.graph.json` | Runs | d4db881cf5a642a081d08af7ad9cf837 | 2.1s; overrides: ['audio_exporter_3.output_dir'] |
| `examples/templates/call-analytics.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `examples/templates/captions.graph.json` | Invalid | - | missing node types: asr_transcribe,caption_export |
| `examples/templates/doc-rag-ingest.graph.json` | Invalid | - | missing node types: doc_parse_chunk |
| `examples/templates/edge-deploy.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/templates/marketplace/tpl-agents-email-alert-support.graph.json` | Needs-external | fd8bdb40484046808bbaf8afcac7086e | run failed: send_email: recipient 'to' is required. |
| `examples/templates/marketplace/tpl-agents-llm-local-chat-support.graph.json` | Runs | 702c0c4aab5b4956940142fe9bb4fc0f | 2.0s; overrides: none |
| `examples/templates/marketplace/tpl-agents-notify-on-run-mlops.graph.json` | Needs-external | 59571860e1d1406fb175a867df1b9e56 | run failed: HttpWebhookNode: config.url (or connection_id) is required (completion callback URL). |
| `examples/templates/marketplace/tpl-agents-run-pipeline-mlops.graph.json` | Invalid | - | missing node types: mcp_tool_call,tool_router |
| `examples/templates/marketplace/tpl-agents-run-pipeline-security.graph.json` | Invalid | - | missing node types: mcp_tool_call,tool_router |
| `examples/templates/marketplace/tpl-agents-run-pipeline-support.graph.json` | Invalid | - | missing node types: mcp_tool_call,tool_router |
| `examples/templates/marketplace/tpl-audio-kws-automotive-edge-tflite.graph.json` | Validates-only | 95eea4793acf444eac8e48ec8820e09f | run failed (prerequisite/params): DatasetIngestNode: config.path is required for filesystem ingest. Empty path previously resolved to the process CWD and could  |
| `examples/templates/marketplace/tpl-audio-kws-automotive.graph.json` | Validates-only | d381b94590254a669acad46f24ecec23 | run failed (prerequisite/params): DatasetIngestNode: config.path is required for filesystem ingest. Empty path previously resolved to the process CWD and could  |
| `examples/templates/marketplace/tpl-audio-kws-smart-home-edge-tflite.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/templates/marketplace/tpl-audio-kws-smart-home.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/templates/marketplace/tpl-common-branch-merge-error-general.graph.json` | Runs | 04ff6b0e4da44d3cb287101ad193c818 | 2.0s; overrides: none |
| `examples/templates/marketplace/tpl-common-doc-chunk-store-general.graph.json` | Invalid | - | missing node types: doc_parse_chunk |
| `examples/templates/marketplace/tpl-common-http-poll-transform-general.graph.json` | Needs-external | 497b017ac2e24a4bbea9b5fd12e45b3e | run failed: HttpRequestNode: config.url is required. |
| `examples/templates/marketplace/tpl-coverage-node-audio-classifier.graph.json` | Invalid | - | missing node types: audio_classifier |
| `examples/templates/marketplace/tpl-cross-meeting-audio-asr-rag-factory.graph.json` | Invalid | - | missing node types: asr_transcribe,chunk_recursive,rag_generate,text_embed,vector_store_query,vector_store_write |
| `examples/templates/marketplace/tpl-cross-meeting-audio-asr-rag-retail.graph.json` | Invalid | - | missing node types: asr_transcribe,chunk_recursive,rag_generate,text_embed,vector_store_query,vector_store_write |
| `examples/templates/marketplace/tpl-cross-meeting-audio-asr-rag.graph.json` | Invalid | - | missing node types: asr_transcribe,chunk_recursive,rag_generate,text_embed,vector_store_query,vector_store_write |
| `examples/templates/marketplace/tpl-mlops-canary-promote-audio.graph.json` | Invalid | - | missing node types: ab_assign,canary_gate,ship_package_promote |
| `examples/templates/marketplace/tpl-mlops-drift-watch-audio.graph.json` | Invalid | - | missing node types: dataset_diff,drift_detect,feature_store_read |
| `examples/templates/marketplace/tpl-mlops-train-eval-ship-audio.graph.json` | Invalid | - | missing node types: artifact_checksum,model_card,run_metadata_stamp,ship_package_create,ship_package_transition |
| `examples/templates/marketplace/tpl-rag-ingest-fs-markdown-faiss-support.graph.json` | Invalid | - | missing node types: chunk_markdown,rag_fs_connector,text_embed,vector_store_write |
| `examples/templates/marketplace/tpl-rag-ingest-fs-recursive-faiss-support.graph.json` | Invalid | - | missing node types: chunk_recursive,rag_fs_connector,text_embed,vector_store_write |
| `examples/templates/marketplace/tpl-rag-ingest-fs-semantic-faiss-support.graph.json` | Invalid | - | missing node types: chunk_semantic,rag_fs_connector,text_embed,vector_store_write |
| `examples/templates/marketplace/tpl-tinyml-kws-wearable-cortex-m4-ptq-cmsis-pack.graph.json` | Invalid | - | missing node types: cmsis_nn_optimize_flag,cmsis_pack_exporter,mcu_dataset_health,mcu_dataset_ingest,mcu_glue_stubs,mcu_label_taxonomy,mcu_mfcc,mcu_train,mcu_wi |
| `examples/templates/marketplace/tpl-tinyml-kws-wearable-cortex-m4-ptq-executorch.graph.json` | Invalid | - | missing node types: executorch_export,mcu_arena_estimator,mcu_dataset_health,mcu_dataset_ingest,mcu_glue_stubs,mcu_label_taxonomy,mcu_mfcc,mcu_train,mcu_window |
| `examples/templates/marketplace/tpl-tinyml-kws-wearable-cortex-m4-ptq-tflm.graph.json` | Invalid | - | missing node types: cmsis_pack_exporter,mcu_arena_estimator,mcu_dataset_health,mcu_dataset_ingest,mcu_label_taxonomy,mcu_mfcc,mcu_train,mcu_window,tflm_convert, |
| `examples/templates/marketplace/tpl-video-action-classify-security.graph.json` | Invalid | - | missing node types: action_classify,clip_segment,video_ingest |
| `examples/templates/marketplace/tpl-video-ingest-scene-caption-security.graph.json` | Invalid | - | missing node types: clip_segment,frame_sample,scene_detect,video_caption,video_exporter,video_ingest,video_quality_gate |
| `examples/templates/marketplace/tpl-video-safety-monitor-security.graph.json` | Invalid | - | missing node types: action_classify,frame_sample,video_ingest,yolo_predict |
| `examples/templates/marketplace/tpl-vision-yolo-detect-hparam-retail-shelf.graph.json` | Invalid | - | missing node types: experiment_tracker,vision_dataset_ingest,yolo_dataset_yaml_build,yolo_hyperparam_search,yolo_train,yolo_val |
| `examples/templates/marketplace/tpl-vision-yolo-detect-resume-retail-shelf.graph.json` | Invalid | - | missing node types: experiment_tracker,yolo_resume_train,yolo_val |
| `examples/templates/marketplace/tpl-vision-yolo-detect-train-retail-shelf.graph.json` | Invalid | - | missing node types: experiment_tracker,vision_augment,vision_dataset_health,vision_dataset_ingest,vision_label_convert,vision_train_val_split,yolo_dataset_yaml_ |
| `examples/templates/marketplace/tpl-wakeword-en-hey-graphyn-data-gen.graph.json` | Invalid | - | missing node types: dataset_versioner,wakeword_data_gen |
| `examples/templates/marketplace/tpl-wakeword-en-hey-graphyn-feature.graph.json` | Invalid | - | missing node types: wakeword_data_gen,wakeword_feature_extract |
| `examples/templates/marketplace/tpl-wakeword-en-hey-graphyn-train.graph.json` | Invalid | - | missing node types: experiment_tracker,wakeword_feature_extract,wakeword_train |
| `examples/templates/meeting-crm.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `examples/templates/podcast-leveling.graph.json` | Invalid | - | missing node types: speech_enhancer |
| `examples/templates/speech-commands-e2e-prepare.graph.json` | Runs | d0f764318bec4795af9b54ef6114ff95 | 46.2s; overrides: ['audio_exporter_6.output_dir'] |
| `examples/templates/speech-recognition.graph.json` | Runs | 15b8957f929649099a875ce42a563e1f | 6.1s; overrides: ['audio_exporter_4.output_dir'] |
| `workspace/configs/templates/audio-classification.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/audio-quality-check.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/basic-wakeword.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/call-analytics.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `workspace/configs/templates/captions.graph.json` | Invalid | - | missing node types: asr_transcribe,caption_export |
| `workspace/configs/templates/doc-rag-ingest.graph.json` | Invalid | - | missing node types: doc_parse_chunk |
| `workspace/configs/templates/edge-deploy.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/ex-01-wake-word.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/ex-02-speech-commands.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/ex-03-environmental-sounds.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/ex-04-speaker-verification.graph.json` | Invalid | - | missing node types: audio_annotator |
| `workspace/configs/templates/ex-05-speech-enhancement.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/ex-06-speech-commands-e2e.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/ex-09-parallel-execution.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/ex-10-resumable-pipeline.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/ex-12-conditional-branching.graph.json` | Invalid | - | missing node types: dataset_versioner |
| `workspace/configs/templates/ex-18-pipeline-composition.graph.json` | Invalid | - | missing node types: dataset_versioner |
| `workspace/configs/templates/ex-19-capability-scheduling.graph.json` | Invalid | - | missing node types: stream_ingest |
| `workspace/configs/templates/ex-22-call-analytics.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `workspace/configs/templates/ex-23-meeting-crm.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `workspace/configs/templates/ex-24-captions.graph.json` | Invalid | - | missing node types: asr_transcribe,caption_export |
| `workspace/configs/templates/ex-25-doc-rag-ingest.graph.json` | Invalid | - | missing node types: doc_parse_chunk |
| `workspace/configs/templates/ex-26-nightly-compliance.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `workspace/configs/templates/ex-27-github-triage.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `workspace/configs/templates/ex-28-asr-eval-merge.graph.json` | Invalid | - | missing node types: asr_transcribe |
| `workspace/configs/templates/ex-29-distributed-placement.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/ex-30-edge-deploy.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/meeting-crm.graph.json` | Invalid | - | missing node types: asr_transcribe,pii_redact |
| `workspace/configs/templates/podcast-leveling.graph.json` | Invalid | - | missing node types: speech_enhancer |
| `workspace/configs/templates/speech-commands-e2e-prepare.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `workspace/configs/templates/speech-recognition.graph.json` | Validates-only | - | valid via POST /pipelines/validate; not executed (duplicate/sampled — see md) |
| `examples/06_speech_commands_e2e/pipeline_train_ml.graph.json [variant: ex06-train-chained]` | Runs | 10b707ec403241f5af1db75a2ea1692b | variant run |

## Sampling disclosure

- Of the valid file templates, ~34 are unique graphs (15 `workspace/configs/templates` files duplicate `examples/templates`; several marketplace smart-home graphs duplicate automotive). Every unique runnable family was executed at least once; remaining valid duplicates are "Validates-only (not executed)".
- Catalog entries (3032) were materialized + validated only; none executed beyond the file-template runs above.
