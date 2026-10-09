# Tests

Tip `6978329f529c59567fdfa4397c5bea5a6b1c9099` · run 2026-10-08 IST on Server-99 host venv.

## Backend (pytest)

Command: `venv/bin/pytest unit_test -p no:cacheprovider` (default markers; `heavy` tests skip unless `GRAPHYN_RUN_HEAVY=1`). Wall time ~122 s.

| Collected | Passed | Failed | Errors | Skipped |
|---|---|---|---|---|
| 3381 | 2802 | 195 | 307 | 77 |

- **452** of the 502 failures+errors (307 errors, 145 failures) are caused by plugins removed from this branch (missing `PluginPackage/...` paths or unregistered node types). The suite was not pruned when the packs were removed → **the suite is red on this branch**, contradicting ENTERPRISE_READINESS "tests green".
- **50** failures are not simple missing-path errors; 23 of those are indirect removed-plugin effects (template families, catalog ≥95% gate, proposed-plugin registry, registry runtime). The remaining 27 are real product regressions or stale tests (below).

### Real product regressions (root-caused)

| Root cause | Tests |
|---|---|
| Run outputs listing regressions (ordering/meta/inventory) (4) | test_backend_review_round2::test_outputs_truncate_in_natural_order<br>test_ui_review_backend_fixes::test_outputs_with_meta_and_node_paging<br>test_example06_app_fixes::test_outputs_prioritise_key_files_and_skip_ingest_inputs<br>test_outputs_inventory::test_listing_uses_artifact_inventory_not_labels_csv |
| `app/api/routers/projects.py:1050` imports non-existent `disable_schedules_for_pipeline` (1) | TestProjectPipelines::test_put_get_list_delete |
| Mode B: `app/core/distributed/transfer.py:229-244` `root` unbound on normal path (UnboundLocalError) / downstream job failures (20) | test_modeb_fixes_backend::test_auto_placement_is_not_pinned_to_run_start_worker<br>test_modeb_fixes_backend::test_pool_placement_enqueues_pool_constraint<br>test_modeb_fixes_backend::test_explicit_worker_mode_still_pins<br>test_modeb_fixes_backend::test_run_end_deletes_job_and_input_blobs<br>test_modeb_fixes_backend::test_keep_blobs_env_disables_cleanup<br>test_modeb_fixes_backend::test_tampered_output_blob_fails_run<br>test_distributed_backend_logs::test_distributed_backend_emits_lifecycle_logs<br>test_distributed_transfer::test_dump_load_port_value_round_trip<br>test_distributed_transfer::test_put_get_blob_round_trip<br>test_distributed_transfer::test_model_artifact_artifactref_round_trip_keras_and_saved_model<br>test_distributed_transfer::test_raw_host_path_must_not_survive_put_get_without_materialize<br>test_distributed_transfer::test_deployment_artifact_directory_sideload_round_trip<br>test_distributed_transfer::test_tflite_artifact_path_sideload_round_trip<br>test_distributed_transfer::test_plain_port_value_unaffected_by_sideload<br>test_distributed_transfer::test_deployment_artifact_labels_and_bundle_round_trip<br>test_distributed_wave_backend::test_wave_path_remote_no_local_rematerialize<br>test_distributed_wave_backend::test_worker_input_refs_end_to_end_in_process<br>test_leftover_distributed_logical_hash::test_modeb_graph_hash_is_logical_and_stable<br>test_leftover_distributed_logical_hash::test_modeb_jobs_run_scoped_and_seeded_from_logical_config<br>test_leftover_distributed_logical_hash::test_modeb_custom_run_manager_without_logical_hash_kw |
| Stale test (mocks dict, worker path changed) (1) | test_dep_isolation::test_isolated_process_uses_worker_not_host |
| Indirect removed-plugin / catalog / registry (23) | test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-vision-yolo-detect-train-retail-shelf]<br>test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-rag-ingest-fs-recursive-faiss-support]<br>test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-tinyml-kws-wearable-cortex-m4-ptq-tflm]<br>test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-wakeword-en-hey-graphyn-data-gen]<br>test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-video-ingest-scene-caption-security]<br>test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-agents-run-pipeline-mlops]<br>test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-mlops-train-eval-ship-audio]<br>test_pipeline_template_materializer::test_full_catalog_validate_ge_95<br>test_registry_runtime::test_get_registry_contains_at_least_18_audio_plugin_nodes<br>test_registry_runtime::test_get_registry_contains_common_plugin_nodes<br>test_all_common_plugins::test_all_listed_common_plugins_registered<br>test_proposed_plugins_registry::test_all_new_packs_install<br>test_proposed_plugins_registry::test_key_nodes_registered[yolo_train]<br>test_proposed_plugins_registry::test_key_nodes_registered[tflm_quantize]<br>test_proposed_plugins_registry::test_key_nodes_registered[vector_store_write]<br>test_proposed_plugins_registry::test_key_nodes_registered[vector_store_query]<br>test_proposed_plugins_registry::test_key_nodes_registered[rag_generate]<br>test_proposed_plugins_registry::test_key_nodes_registered[text_embed]<br>test_proposed_plugins_registry::test_key_nodes_registered[mcu_train]<br>test_proposed_plugins_registry::test_key_nodes_registered[wakeword_train]<br>test_proposed_plugins_registry::test_key_nodes_registered[video_ingest]<br>test_proposed_plugins_registry::test_key_nodes_registered[agent_loop]<br>test_proposed_plugins_registry::test_key_nodes_registered[ship_package_create] |
| Plugin schema UX/jargon test (1) | test_ux_plugins_schema_ux::test_descriptions_have_no_jargon[send_email] |

### Removed-plugin failures by test area

- test_pcm_fixes_audio_decode: 150
- ir: 76
- audio: 75
- common: 60
- test_mlops_fixes_mlops: 43
- test_mlops_fixes_rag_vision: 19
- test_pcm_fixes_stream_ingest: 18
- test_proposed_plugins_registry: 7
- test_leftover_secret_env: 3
- test_review_fixes: 1

### Not run

- `heavy`-marked tests (need `GRAPHYN_RUN_HEAVY=1`, real model training) — skipped by default; included in the 77 skips.
- No Mode B live/integration tests (stack down).

## Frontend (graphyn-ui)

| Check | Result |
|---|---|
| Declared `npm test` (`npx --yes vitest@3.2.4 run --config vitest.config.ts`; also used by `.github/workflows/ci.yml`) | **FAILS** — `vitest/config` cannot be resolved: vitest is not in devDependencies |
| vitest via review workaround config (`/tmp/rv/vt/vitest.review.config.mjs`) | **528/528 tests, 260/260 suites pass** |
| `tsc --noEmit` | exit 0 |
| Production build (`vite build`) | not run (rebuild prohibited) |

## All genuine failure names

- `unit_test.api.test_backend_review_round2::test_outputs_truncate_in_natural_order` — AssertionError: assert [] == ['0.wav', '1.... '5.wav', ...]      Right contains 12 more items, first extra item: '0.wav'   Use -v to get more diff
- `unit_test.api.test_project_pipelines.TestProjectPipelines::test_put_get_list_delete` — ImportError: cannot import name 'disable_schedules_for_pipeline' from 'app.core.pipelines.schedules' (/home/meritech/Desktop/newAudio3/app/core/pipeli
- `unit_test.api.test_ui_review_backend_fixes::test_outputs_with_meta_and_node_paging` — assert False is True
- `unit_test.core.distributed.test_modeb_fixes_backend::test_auto_placement_is_not_pinned_to_run_start_worker` — RuntimeError: Distributed job f8d6b4ea-8a48-4368-9ad8-61fb6851e0f5 (node=n0) ended with status=failed: cannot access local variable 'root' where it is
- `unit_test.core.distributed.test_modeb_fixes_backend::test_pool_placement_enqueues_pool_constraint` — RuntimeError: Distributed job 2f189296-d8da-454e-9dd9-86e5c6f2d772 (node=n0) ended with status=failed: cannot access local variable 'root' where it is
- `unit_test.core.distributed.test_modeb_fixes_backend::test_explicit_worker_mode_still_pins` — RuntimeError: Distributed job 4703219b-d377-4670-b4b2-218d9f523e45 (node=n0) ended with status=failed: cannot access local variable 'root' where it is
- `unit_test.core.distributed.test_modeb_fixes_backend::test_run_end_deletes_job_and_input_blobs` — RuntimeError: Distributed job d975236d-53f6-4dc7-8bf3-8674f08622ef (node=n0) ended with status=failed: cannot access local variable 'root' where it is
- `unit_test.core.distributed.test_modeb_fixes_backend::test_keep_blobs_env_disables_cleanup` — RuntimeError: Distributed job 970c3d09-86df-4d69-a4d8-456c2f0dc857 (node=n0) ended with status=failed: cannot access local variable 'root' where it is
- `unit_test.core.distributed.test_modeb_fixes_backend::test_tampered_output_blob_fails_run` — assert {}  +  where {} = JobResult(job_id='74a7e0d5-b372-4d87-9996-2c22f3258b75', status='failed', output_refs={}, events=[], error="cannot acc... not
- `unit_test.core.plugins.test_dep_isolation::test_isolated_process_uses_worker_not_host` — AttributeError: 'dict' object has no attribute 'published_file_trees'
- `unit_test.core.test_distributed_backend_logs::test_distributed_backend_emits_lifecycle_logs` — RuntimeError: Distributed job 9bcf2ea8-21f8-4ca9-a806-cb422e3772a2 (node=b) ended with status=failed: cannot access local variable 'root' where it is 
- `unit_test.core.test_distributed_transfer::test_dump_load_port_value_round_trip` — UnboundLocalError: cannot access local variable 'root' where it is not associated with a value
- `unit_test.core.test_distributed_transfer::test_put_get_blob_round_trip` — UnboundLocalError: cannot access local variable 'root' where it is not associated with a value
- `unit_test.core.test_distributed_transfer::test_model_artifact_artifactref_round_trip_keras_and_saved_model` — UnboundLocalError: cannot access local variable 'root' where it is not associated with a value
- `unit_test.core.test_distributed_transfer::test_raw_host_path_must_not_survive_put_get_without_materialize` — UnboundLocalError: cannot access local variable 'root' where it is not associated with a value
- `unit_test.core.test_distributed_transfer::test_deployment_artifact_directory_sideload_round_trip` — UnboundLocalError: cannot access local variable 'root' where it is not associated with a value
- `unit_test.core.test_distributed_transfer::test_tflite_artifact_path_sideload_round_trip` — UnboundLocalError: cannot access local variable 'root' where it is not associated with a value
- `unit_test.core.test_distributed_transfer::test_plain_port_value_unaffected_by_sideload` — UnboundLocalError: cannot access local variable 'root' where it is not associated with a value
- `unit_test.core.test_distributed_transfer::test_deployment_artifact_labels_and_bundle_round_trip` — UnboundLocalError: cannot access local variable 'root' where it is not associated with a value
- `unit_test.core.test_distributed_wave_backend::test_wave_path_remote_no_local_rematerialize` — RuntimeError: Distributed job fc2b5c24-7aee-48bf-a973-c19419a1232a (node=gpu0) ended with status=failed: cannot access local variable 'root' where it 
- `unit_test.core.test_distributed_wave_backend::test_worker_input_refs_end_to_end_in_process` — RuntimeError: Distributed job 1f959307-950a-4177-876e-a9ce66780dd5 (node=g0) ended with status=failed: cannot access local variable 'root' where it is
- `unit_test.core.test_example06_app_fixes::test_outputs_prioritise_key_files_and_skip_ingest_inputs` — AssertionError: assert (45 == 12)  +  where 45 = len([{'kind': 'file', 'name': 'graph.json', 'path': 'runs/run-ex6-outputs/graph.json', 'size': 889}, 
- `unit_test.core.test_leftover_distributed_logical_hash::test_modeb_graph_hash_is_logical_and_stable` — RuntimeError: Distributed job 1b44d3a8-b1fb-46f4-86fb-4dabc898080d (node=a) ended with status=failed: cannot access local variable 'root' where it is 
- `unit_test.core.test_leftover_distributed_logical_hash::test_modeb_jobs_run_scoped_and_seeded_from_logical_config` — RuntimeError: Distributed job 103b9f05-ec8a-445f-9318-ee0facc29c16 (node=a) ended with status=failed: cannot access local variable 'root' where it is 
- `unit_test.core.test_leftover_distributed_logical_hash::test_modeb_custom_run_manager_without_logical_hash_kw` — RuntimeError: Distributed job 27dece71-d284-4a6b-b375-8106bbe3cd24 (node=a) ended with status=failed: cannot access local variable 'root' where it is 
- `unit_test.core.test_outputs_inventory::test_listing_uses_artifact_inventory_not_labels_csv` — KeyError: 'llm_dump_0'
- `unit_test.core.test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-vision-yolo-detect-train-retail-shelf]` — AssertionError: ["[n0] Unknown node type 'vision_dataset_ingest'. Available: audio_conditioner, audio_exporter, audio_quality_gate, au...nference, sch
- `unit_test.core.test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-rag-ingest-fs-recursive-faiss-support]` — AssertionError: ["[n0] Unknown node type 'rag_fs_connector'. Available: audio_conditioner, audio_exporter, audio_quality_gate, augment... n1.input: sk
- `unit_test.core.test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-tinyml-kws-wearable-cortex-m4-ptq-tflm]` — AssertionError: ["[n0] Unknown node type 'mcu_dataset_ingest'. Available: audio_conditioner, audio_exporter, audio_quality_gate, augme...nference, sch
- `unit_test.core.test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-wakeword-en-hey-graphyn-data-gen]` — AssertionError: ["[n0] Unknown node type 'wakeword_data_gen'. Available: audio_conditioner, audio_exporter, audio_quality_gate, augmen...tructured_llm
- `unit_test.core.test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-video-ingest-scene-caption-security]` — AssertionError: ["[n0] Unknown node type 'video_ingest'. Available: audio_conditioner, audio_exporter, audio_quality_gate, augmentatio...nference, sch
- `unit_test.core.test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-agents-run-pipeline-mlops]` — AssertionError: ["[n2] Unknown node type 'tool_router'. Available: audio_conditioner, audio_exporter, audio_quality_gate, augmentation...→ n3.tool_nam
- `unit_test.core.test_pipeline_template_materializer::test_family_sample_materialize_validate[tpl-mlops-train-eval-ship-audio]` — AssertionError: ["[n0] Unknown node type 'run_metadata_stamp'. Available: audio_conditioner, audio_exporter, audio_quality_gate, augme... trainer, wai
- `unit_test.core.test_pipeline_template_materializer::test_full_catalog_validate_ge_95` — AssertionError: only 3.69% validated (112/3032) assert 3.6939313984168867 >= 95.0
- `unit_test.core.test_registry_runtime::test_get_registry_contains_at_least_18_audio_plugin_nodes` — AssertionError: Missing audio plugin node types: {'audio_generator', 'stream_processor', 'speech_enhancer', 'environment_simulator', 'speaker_separato
- `unit_test.core.test_registry_runtime::test_get_registry_contains_common_plugin_nodes` — AssertionError: Missing common plugin node types: {'dataset_balancer', 'dataset_versioner', 'embedding_generator', 'experiment_tracker', 'multimodal_f
- `unit_test.plugins.common.test_all_common_plugins::test_all_listed_common_plugins_registered` — AssertionError: new Common plugins missing from registry: {'asr_transcribe', 'doc_parse_chunk', 'caption_export', 'pii_redact'} assert not {'asr_trans
- `unit_test.plugins.test_proposed_plugins_registry::test_all_new_packs_install` — AssertionError: assert 5 >= 100  +  where 5 = len(['guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'])
- `unit_test.plugins.test_proposed_plugins_registry::test_key_nodes_registered[yolo_train]` — AssertionError: assert 'yolo_train' in {'guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'}
- `unit_test.plugins.test_proposed_plugins_registry::test_key_nodes_registered[tflm_quantize]` — AssertionError: assert 'tflm_quantize' in {'guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'}
- `unit_test.plugins.test_proposed_plugins_registry::test_key_nodes_registered[vector_store_write]` — AssertionError: assert 'vector_store_write' in {'guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'}
- `unit_test.plugins.test_proposed_plugins_registry::test_key_nodes_registered[vector_store_query]` — AssertionError: assert 'vector_store_query' in {'guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'}
- `unit_test.plugins.test_proposed_plugins_registry::test_key_nodes_registered[rag_generate]` — AssertionError: assert 'rag_generate' in {'guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'}
- `unit_test.plugins.test_proposed_plugins_registry::test_key_nodes_registered[text_embed]` — AssertionError: assert 'text_embed' in {'guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'}
- `unit_test.plugins.test_proposed_plugins_registry::test_key_nodes_registered[mcu_train]` — AssertionError: assert 'mcu_train' in {'guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'}
- `unit_test.plugins.test_proposed_plugins_registry::test_key_nodes_registered[wakeword_train]` — AssertionError: assert 'wakeword_train' in {'guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'}
- `unit_test.plugins.test_proposed_plugins_registry::test_key_nodes_registered[video_ingest]` — AssertionError: assert 'video_ingest' in {'guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'}
- `unit_test.plugins.test_proposed_plugins_registry::test_key_nodes_registered[agent_loop]` — AssertionError: assert 'agent_loop' in {'guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'}
- `unit_test.plugins.test_proposed_plugins_registry::test_key_nodes_registered[ship_package_create]` — AssertionError: assert 'ship_package_create' in {'guardrail_filter', 'hitl_approve', 'llm_chat', 'output_schema_validate', 'prompt_template'}
- `unit_test.plugins.test_ux_plugins_schema_ux::test_descriptions_have_no_jargon[send_email]` — AssertionError: send_email.from_addr: 'GRAPHYN_[A-Z_]+' in 'Override From. Default: smtp connection from_addr / GRAPHYN_SMTP_FROM.'   send_email.dry_r
