# Implementation Plan: unit_test Suite

## Overview

Build a brand-new `unit_test/` folder at the project root containing a comprehensive, up-to-date test suite covering all files in `app/` and all 29 plugins in `PluginPackage/`. The suite replaces the outdated `tests/` folder and is runnable with `venv/bin/pytest unit_test/`.

Design documents: `design.md`, `design-conftest.md`, `design-test-patterns.md`
Requirements: `requirements.md`, `requirements-per-file.md`

## Tasks

- [ ] 1. Create unit_test folder structure and conftest.py
  - Create `unit_test/` with `__init__.py` in every subdirectory: `core/`, `core/nodes/`, `core/ir/`, `core/plugins/`, `api/`, `mcp/`, `cli/`, `models/`, `plugins/`, `plugins/audio/`, `plugins/common/`
  - Write `unit_test/conftest.py` with all fixtures from `design-conftest.md`: `fresh_registry` (function-scoped), `tmp_plugin_dir` (tmp_path-backed), `make_audio_sample` factory, `patch_threads` (autouse), `api_client` (TestClient), `tmp_workspace`, `minimal_node_cls`, `minimal_meta`
  - Verify `venv/bin/pytest unit_test/ --collect-only` exits 0
  - **Requirements:** Req 1 criteria 1–10

- [ ] 2. Write data model unit tests
  - `unit_test/models/test_audio_sample.py`: construction defaults, None→empty array coercion, list→ndarray coercion, model_validate round-trip, PortDataType subclass check
  - `unit_test/models/test_feature_array.py`: construction, None coercion to zeros((0,0)), PortDataType subclass
  - `unit_test/models/test_tensor_batch.py`: construction, batch_size property, None coercion
  - `unit_test/models/test_tflite_artifact.py`: valid quantisation values, invalid raises ValidationError
  - `unit_test/models/test_model_artifact.py`, `test_prediction_result.py`, `test_deployment_artifact.py`, `test_data_sample.py`: default construction, PortDataType subclass, no shared mutable defaults
  - **Requirements:** Req 17 criteria 1–17
  - **Depends on:** Task 1

- [ ] 3. Write node infrastructure unit tests
  - `unit_test/core/nodes/test_errors.py`: all 8 error classes importable, inheritance chain correct
  - `unit_test/core/nodes/test_observers.py`: LoggingObserver emits correct JSON at correct log level; CompositeObserver fans out to all children
  - `unit_test/core/nodes/test_node_config.py`: extra fields raise ValidationError; empty dict uses defaults
  - `unit_test/core/nodes/test_retry.py`: invalid params raise ValidationError; wait formula correct; property-based monotonicity test (Hypothesis, 100 examples)
  - `unit_test/core/nodes/test_node_base.py`: SISO wrapper, lifecycle hooks order, input_type/output_type properties, process not implemented on base
  - `unit_test/core/nodes/test_registry.py`: register/get/unregister/contains, NodeNotFoundError, to_json/from_json round-trip — all using `fresh_registry`
  - `unit_test/core/nodes/test_catalogue.py`: register/resolve round-trip, DuplicatePortTypeError on second register
  - `unit_test/core/nodes/test_discovery.py`: valid node registered, DuplicateNodeTypeError, missing metadata logged as warning, _pascal_to_snake conversions — all using `fresh_registry`
  - `unit_test/core/nodes/test_compat.py`: reflexivity, issubclass consistency, check_connection raises NodeTypeError on mismatch; property-based reflexivity (Hypothesis)
  - `unit_test/core/nodes/test_metadata.py`: empty node_type/label/description/category raise ValidationError; valid metadata round-trips
  - `unit_test/core/nodes/test_ports.py`: InputPort/OutputPort construction, PortDataType subclass registration
  - **Requirements:** Req 2, Req 3, Req 18 criteria 1–14
  - **Depends on:** Task 1

- [ ] 4. Write Graph IR unit tests
  - `unit_test/core/ir/test_ir_models.py`: duplicate node ID raises ValueError; bad edge reference raises ValueError; invalid node ID chars raise ValueError; property-based idempotent round-trip (Hypothesis)
  - `unit_test/core/ir/test_ir_loader.py`: load_ir(dump_ir(graph)) == graph; wrong major version raises IRVersionError; minor version difference accepted
  - `unit_test/core/ir/test_yaml_shim.py`: YAML dict → GraphIR with correct node count, auto-chained edges, seed preserved; explicit edges override auto-chain
  - `unit_test/core/ir/test_ir_migrate.py`: migrate_yaml_to_ir_file writes .graph.json next to YAML; custom output_path respected; output is valid IR JSON
  - **Requirements:** Req 4 criteria 1–4, Req 16 criterion 2, Req 19 criteria 23–25
  - **Depends on:** Task 1

- [ ] 5. Write core services unit tests (conditions, events, runtime_backend, webhook)
  - `unit_test/core/test_conditions.py`: len() passes/fails, import raises, unknown name raises, disallowed function raises, syntax error raises
  - `unit_test/core/test_events.py`: create_event_source factory for timer/queue/file_watcher; unknown type raises ValueError; QueueSource yields queued item; TimerSource is EventSource subclass
  - `unit_test/core/test_runtime_backend.py`: get_backend("local_python") returns LocalPythonBackend; unknown raises KeyError; list_backends sorted; register_backend works; register non-subclass raises TypeError; backend_id property
  - `unit_test/core/test_webhook.py`: save writes webhooks.json; load returns {} when missing; notify no-op when no URL; notify no-raise when httpx fails; event filtering
  - **Requirements:** Req 19 criteria 1–22
  - **Depends on:** Task 1

- [ ] 6. Write pipeline, cache, logger, run_manager, SDK unit tests
  - `unit_test/core/test_pipeline_cache.py`: key() determinism; save/load round-trip; clear() returns counts and invalidates keys; property-based key determinism (Hypothesis)
  - `unit_test/core/test_logger.py`: pipeline_start appends correct event; node_end appends correct event; UTC timestamps; node_end output_count passthrough
  - `unit_test/core/test_run_manager.py`: pause/resume state machine; cancel idempotence; save_graph_ir writes graph.json atomically; register_artifact returns ArtifactRecord; deduplication
  - `unit_test/core/test_sdk.py`: PipelineNode unknown type raises ValueError; invalid config raises ValueError; ArtifactCollection dict protocol; ArtifactCollection.lineage never raises; Pipeline.subscribe returns unsubscribe callable
  - `unit_test/core/test_pipeline.py`: PipelineGraph topological order; cycle raises PipelineGraphError; validate_pipeline accepts valid config; validate_pipeline raises for unknown node type
  - `unit_test/core/test_validation.py`: validate_pipeline valid/invalid/unknown-type/invalid-config/DAG-format
  - `unit_test/core/test_registry_runtime.py`: get_registry() returns populated NodeRegistry with plugin nodes
  - **Requirements:** Req 4 criteria 5–9, Req 5, Req 14 criterion 5, Req 15, Req 16 criterion 1
  - **Depends on:** Task 1

- [ ] 7. Write artifact store and provenance unit tests
  - `unit_test/core/test_artifact_store.py`: register returns ArtifactRecord; deduplication (same content → same artifact_id); get returns record; get nonexistent raises ArtifactNotFoundError (subclass of KeyError); unsupported type raises ValueError; list with run_id filter; list sorted by created_at desc
  - `unit_test/core/test_provenance.py`: record() writes files; no duplicate in by_run; get_lineage unknown returns error node; get_lineage registered returns full tree; find_by_run unknown returns []; find_reproducible by graph_hash
  - **Requirements:** Req 20 criteria 1–14
  - **Depends on:** Task 1

- [ ] 8. Write ingestion, project_manager, quality_checker unit tests
  - `unit_test/core/test_ingestion.py`: IngestionJob construction; append_progress thread-safety (10 threads × 10 appends = 100 total); read_progress snapshot; independent instances; start_url_job/start_hf_job return job_id; get_job; get_job nonexistent raises KeyError
  - `unit_test/core/test_project_manager.py`: create/delete/rename/set_status; duplicate create raises; wrong confirm raises; invalid status raises; duplicate taxonomy sibling raises; invalid contract raises; add_annotations writes JSONL; export_annotations CSV has header; diff_versions returns counts
  - `unit_test/core/test_quality_checker.py`: _check_duration_range below min returns error finding; within range returns []; _check_sample_rate mismatch returns finding; _check_clipping peak>0.999 returns finding; _check_dc_offset mean>0.01 returns finding; _check_class_imbalance imbalanced returns finding; balanced returns []; _finding returns correct dict
  - **Requirements:** Req 21, Req 22, Req 23
  - **Depends on:** Task 1

- [ ] 9. Write plugin ecosystem unit tests
  - `unit_test/core/plugins/test_manifest.py`: valid manifest constructs; invalid slug raises PluginManifestError; invalid version raises; non-.py entry_point raises; property-based valid manifest acceptance (Hypothesis)
  - `unit_test/core/plugins/test_manager.py`: install into tmp_plugin_dir registers node; double install raises PluginAlreadyInstalledError; uninstall removes node; disable unloads node; enable reloads node; uninstall nonexistent raises PluginNotFoundError; load_enabled_plugins fault isolation
  - `unit_test/core/plugins/test_store.py`: PluginRecord save/load round-trip; update_enabled toggles state
  - `unit_test/core/plugins/test_loader.py`: platform version compat check accepts matching version; rejects incompatible major version
  - `unit_test/core/plugins/test_index.py`: remote fetch calls httpx.get; HTTP error raises PluginIndexError; local fetch reads file; no source returns []; caching; search by name/description/tag; lookup by name/version
  - `unit_test/core/plugins/test_dependencies.py`: DependencyChecker raises PluginDependencyError listing unsatisfied deps
  - `unit_test/core/plugins/test_installer.py`: correct checksum passes; wrong checksum raises PluginInstallError
  - **Requirements:** Req 6, Req 16 criterion 5
  - **Depends on:** Task 1

- [ ] 10. Write Audio plugin tests (registration + smoke)
  - One file per plugin in `unit_test/plugins/audio/`. Each file contains: registration test (install into tmp_plugin_dir, assert node_type in fresh_registry), metadata test (label/category/version non-empty), construct test (cls(config={}, seed=0) succeeds), process smoke test (process({"input": [make_audio_sample()]}) returns dict with "output" key)
  - Plugins: audio_conditioner (+ Req 9 criteria 1–5), feature_frontend (+ Req 9 criteria 6–7), dataset_ingest, stream_ingest, audio_quality_gate (+ Req 9 criteria 11–12), segmenter (+ Req 9 criteria 8–9), audio_annotator, alignment_node, speech_enhancer, speaker_separator, environment_simulator, augmentation_pipeline (+ Req 9 criterion 10), audio_event_detector, audio_classifier, speech_synthesizer, voice_converter, audio_generator, stream_processor
  - `unit_test/plugins/audio/test_all_audio_plugins.py`: module-scoped fixture installs all 18 plugins once; asserts all 18 node_types present with valid metadata
  - **Requirements:** Req 7, Req 9
  - **Depends on:** Task 1

- [ ] 11. Write Common plugin tests (registration + smoke)
  - One file per plugin in `unit_test/plugins/common/`. Same pattern as Task 10: registration, metadata, construct, process smoke
  - Plugins: dataset_builder (+ Req 10 criteria 1–2), trainer, evaluator, edge_optimizer, realtime_inference, dataset_balancer (+ Req 10 criterion 4), dataset_versioner (+ Req 10 criterion 3), experiment_tracker (+ Req 10 criterion 7), deployment_packager, embedding_generator (+ Req 10 criterion 5), multimodal_fusion (+ Req 10 criterion 6)
  - `unit_test/plugins/common/test_all_common_plugins.py`: module-scoped fixture installs all 11 plugins once; asserts all 11 node_types present with valid metadata
  - **Requirements:** Req 8, Req 10
  - **Depends on:** Task 1

- [ ] 12. Write REST API router tests
  - `unit_test/api/test_nodes_router.py`: GET /nodes shape, GET /nodes/{type} 200/404, POST validate-config valid/invalid
  - `unit_test/api/test_pipelines_router.py`: POST validate IR JSON valid/invalid; YAML returns deprecation header; templates CRUD
  - `unit_test/api/test_runs_router.py`: GET /runs returns list; GET /runs/nonexistent 404
  - `unit_test/api/test_run_control_router.py`: pause/resume/cancel active run 200; inactive run 404 with error dict
  - `unit_test/api/test_artifacts_router.py`: GET list; GET by id 200/404; invalid id 400; lineage never 404; replay 404/422
  - `unit_test/api/test_data_router.py`: GET inputs/outputs lists; GET label 404; GET dataset 404; merge empty sources 422; upload bad extension 400
  - `unit_test/api/test_ingest_router.py`: POST url empty urls 422; POST url valid returns job_id; stream 404 unknown job; POST hf empty repo_id 422
  - `unit_test/api/test_projects_router.py`: GET list; POST create; DELETE wrong confirm 422; GET taxonomy 404 unknown project
  - `unit_test/api/test_plugins_router.py`: GET list; POST install; GET by name 404; enable/disable; DELETE 404
  - `unit_test/api/test_system_router.py`: GET health 200 with status/timestamp; timestamp UTC
  - **Requirements:** Req 11, Req 24
  - **Depends on:** Task 1

- [ ] 13. Write MCP handler and auth tests
  - `unit_test/mcp/test_auth.py`: no token env → None; correct token → None; wrong token → unauthorized dict; missing token with env set → unauthorized; error dict has required keys
  - `unit_test/mcp/test_tool_registry.py`: register_all_tools calls register exactly 15 times with correct tool names, non-empty descriptions, non-empty schemas
  - `unit_test/mcp/test_handler_discovery.py`: no args returns all nodes; category filter; invalid capability key returns error_type; list_types returns port_data_types
  - `unit_test/mcp/test_handler_graph.py`: generate valid graph; unknown node type error; invalid config error; validate valid/invalid; get_graph_schema title=GraphIR; capability summary fields; get_event_schema 6 entries
  - `unit_test/mcp/test_handler_execution.py`: valid graph returns run_id (patch ThreadPoolExecutor.submit); invalid graph returns valid=False; use_cache forwarded
  - `unit_test/mcp/test_handler_artifacts.py`: inspect_run no run_id returns runs list; with run_id returns meta
  - `unit_test/mcp/test_handler_run_control.py`: pause/resume/cancel inactive run returns run_not_active
  - `unit_test/mcp/test_handler_provenance.py`: list_artifacts; get_artifact_lineage; replay_run
  - `unit_test/mcp/test_handler_optimization.py`: optimize_execution smoke test returns dict
  - `unit_test/mcp/test_mcp_auth_integration.py`: handler with wrong token returns unauthorized
  - **Requirements:** Req 12, Req 25
  - **Depends on:** Task 1

- [ ] 14. Write CLI tests
  - `unit_test/cli/test_cli.py` using Click's CliRunner: list-nodes exits 0 with output; validate valid IR JSON exits 0; validate unknown node type exits non-zero; plugins list exits 0; migrate valid YAML exits 0 and writes .graph.json; run with mocked pipeline exits 0
  - **Requirements:** Req 13
  - **Depends on:** Task 1

- [ ] 15. Write integration and property-based tests
  - `unit_test/core/test_pipeline_integration.py`: two-node pipeline [audio_conditioner → feature_frontend] runs and returns ArtifactCollection; cache hit on second run; checkpoint writes resume_state.json; retry on first-attempt failure; cycle raises PipelineGraphError; parallel=True completes; subscribe callback receives events
  - `unit_test/core/test_property_based.py`: all 8 Hypothesis properties from Req 16 — cache key determinism, IR idempotent round-trip, retry monotonicity, NodeConfig round-trip, valid manifest acceptance, AudioConditionerNode normalization bound, PipelineGraph completeness, CompatibilityChecker reflexivity — each with @settings(max_examples=100)
  - **Requirements:** Req 14, Req 16
  - **Depends on:** Tasks 6, 7, 10

## Task Dependency Graph

```json
{
  "waves": [
    ["1"],
    ["2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14"],
    ["15"]
  ]
}
```

Tasks 2–14 all depend only on Task 1 and can execute in parallel. Task 15 depends on Tasks 6, 7, and 10.

## Notes

- All tests must pass `venv/bin/pytest unit_test/ -q` with exit code 0
- No test may reference deleted node types: `clean`, `normalize`, `split`, `segment`, `augment`, `input`, `export`, `model_trainer`, `model_evaluator`, `tflite_exporter`, `inference`
- No test may write to the real `plugins/` directory — always use `tmp_plugin_dir`
- The `patch_threads` autouse fixture prevents hangs; tests needing real threads (Task 8 thread-safety test) must call the real `Thread.start` directly and join before the test ends
- Plugin process smoke tests should use `make_audio_sample` fixture and assert `isinstance(result["output"], list)`
- Heavy optional deps (torch, tensorflow, TTS, etc.) are gracefully skipped — plugin nodes fall back to CPU/stub backends when optional deps are absent
