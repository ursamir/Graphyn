# Fix Agent Checkpoint

## Status

current_file: File_review/GROUP_01_IR_Core/migrate.md
current_file_status: pending
last_completed_file: File_review/GROUP_01_IR_Core/loader.md
total_files: 104
files_done: 1
files_skipped: 0
session_count: 1

---

## File Queue

| # | Status | Review File | Source File | Findings | C | H | M | L |
|---|---|---|---|---|---|---|---|---|
| 1 | done | `File_review/GROUP_01_IR_Core/loader.md` | `app/core/ir/loader.py` | 5 | 0 | 1 | 2 | 2 | 3 confirmed+fixed, 1 downgraded (warnings.warn — logger import violates file contract), 1 pre-existing test failure |
| 2 | pending | `File_review/GROUP_01_IR_Core/migrate.md` | `app/core/ir/migrate.py` | 5 | 0 | 1 | 3 | 1 |
| 3 | pending | `File_review/GROUP_01_IR_Core/models.md` | `app/core/ir/models.py` | 6 | 0 | 1 | 2 | 3 |
| 4 | pending | `File_review/GROUP_01_IR_Core/yaml_shim.md` | `app/core/ir/yaml_shim.py` | 7 | 1 | 2 | 3 | 1 |
| 5 | pending | `File_review/GROUP_02_Node_Base/base.md` | `app/core/nodes/base.py` | 6 | 0 | 2 | 2 | 2 |
| 6 | pending | `File_review/GROUP_02_Node_Base/compat.md` | `app/core/nodes/compat.py` | 4 | 0 | 1 | 2 | 1 |
| 7 | pending | `File_review/GROUP_02_Node_Base/config.md` | `(unknown)` | 0 | 0 | 0 | 0 | 0 |
| 8 | pending | `File_review/GROUP_02_Node_Base/errors.md` | `app/core/nodes/errors.py` | 2 | 0 | 0 | 1 | 1 |
| 9 | pending | `File_review/GROUP_02_Node_Base/metadata.md` | `app/core/nodes/metadata.py` | 2 | 0 | 0 | 0 | 2 |
| 10 | pending | `File_review/GROUP_02_Node_Base/observers.md` | `app/core/nodes/observers.py` | 3 | 0 | 0 | 1 | 2 |
| 11 | pending | `File_review/GROUP_02_Node_Base/ports.md` | `app/core/nodes/ports.py` | 2 | 0 | 0 | 1 | 1 |
| 12 | pending | `File_review/GROUP_02_Node_Base/retry.md` | `app/core/nodes/retry.py` | 2 | 0 | 0 | 1 | 1 |
| 13 | pending | `File_review/GROUP_03_Registry_Discovery/catalogue.md` | `app/core/nodes/catalogue.py` | 4 | 0 | 0 | 2 | 2 |
| 14 | pending | `File_review/GROUP_03_Registry_Discovery/discovery.md` | `app/core/nodes/discovery.py` | 8 | 0 | 2 | 4 | 2 |
| 15 | pending | `File_review/GROUP_03_Registry_Discovery/registry.md` | `app/core/nodes/registry.py` | 5 | 0 | 0 | 3 | 2 |
| 16 | pending | `File_review/GROUP_03_Registry_Discovery/registry_runtime.md` | `app/core/registry_runtime.py` | 4 | 0 | 2 | 1 | 1 |
| 17 | pending | `File_review/GROUP_04_Plugin_Ecosystem/dependencies.md` | `app/core/plugins/dependencies.py` | 3 | 0 | 1 | 1 | 1 |
| 18 | pending | `File_review/GROUP_04_Plugin_Ecosystem/errors.md` | `(unknown)` | 0 | 0 | 0 | 0 | 0 |
| 19 | pending | `File_review/GROUP_04_Plugin_Ecosystem/index.md` | `app/core/plugins/index.py` | 4 | 0 | 1 | 2 | 1 |
| 20 | pending | `File_review/GROUP_04_Plugin_Ecosystem/installer.md` | `app/core/plugins/installer.py` | 5 | 0 | 1 | 3 | 1 |
| 21 | pending | `File_review/GROUP_04_Plugin_Ecosystem/loader.md` | `app/core/plugins/loader.py` | 4 | 0 | 1 | 2 | 1 |
| 22 | pending | `File_review/GROUP_04_Plugin_Ecosystem/manager.md` | `app/core/plugins/manager.py` | 5 | 1 | 2 | 1 | 1 |
| 23 | pending | `File_review/GROUP_04_Plugin_Ecosystem/manifest.md` | `app/core/plugins/manifest.py` | 4 | 0 | 0 | 2 | 2 |
| 24 | pending | `File_review/GROUP_04_Plugin_Ecosystem/store.md` | `app/core/plugins/store.py` | 4 | 0 | 1 | 2 | 1 |
| 25 | pending | `File_review/GROUP_05_Planner/planner.md` | `app/core/planner.py` | 9 | 1 | 4 | 3 | 1 |
| 26 | pending | `File_review/GROUP_06_Execution_Runtime/conditions.md` | `app/core/conditions.py` | 3 | 0 | 0 | 2 | 1 |
| 27 | pending | `File_review/GROUP_06_Execution_Runtime/events.md` | `app/core/events.py` | 6 | 0 | 2 | 3 | 1 |
| 28 | pending | `File_review/GROUP_06_Execution_Runtime/executor.md` | `app/core/executor.py` | 6 | 0 | 3 | 2 | 1 |
| 29 | pending | `File_review/GROUP_06_Execution_Runtime/node_executor.md` | `app/core/node_executor.py` | 5 | 0 | 2 | 2 | 1 |
| 30 | pending | `File_review/GROUP_06_Execution_Runtime/orchestrator.md` | `app/core/orchestrator.py` | 10 | 2 | 4 | 3 | 1 |
| 31 | pending | `File_review/GROUP_06_Execution_Runtime/runtime_backend.md` | `app/core/runtime_backend.py` | 4 | 0 | 0 | 2 | 2 |
| 32 | pending | `File_review/GROUP_07_Observability_Storage/artifact_serializer.md` | `app/core/artifact_serializer.py` | 2 | 0 | 0 | 1 | 1 |
| 33 | pending | `File_review/GROUP_07_Observability_Storage/artifact_store.md` | `app/core/artifact_store.py` | 5 | 0 | 2 | 2 | 1 |
| 34 | pending | `File_review/GROUP_07_Observability_Storage/checkpoint.md` | `app/core/checkpoint.py` | 5 | 0 | 1 | 3 | 1 |
| 35 | pending | `File_review/GROUP_07_Observability_Storage/logger.md` | `app/core/logger.py` | 4 | 0 | 0 | 2 | 2 |
| 36 | pending | `File_review/GROUP_07_Observability_Storage/pipeline_cache.md` | `app/core/pipeline_cache.py` | 5 | 0 | 1 | 3 | 1 |
| 37 | pending | `File_review/GROUP_07_Observability_Storage/provenance.md` | `app/core/provenance.py` | 4 | 0 | 1 | 2 | 1 |
| 38 | pending | `File_review/GROUP_07_Observability_Storage/run_control.md` | `app/core/run_control.py` | 3 | 0 | 1 | 1 | 1 |
| 39 | pending | `File_review/GROUP_07_Observability_Storage/run_journal.md` | `app/core/run_journal.py` | 6 | 0 | 2 | 3 | 1 |
| 40 | pending | `File_review/GROUP_08_Platform_Infra/config.md` | `app/core/config.py` | 3 | 0 | 0 | 1 | 2 |
| 41 | pending | `File_review/GROUP_08_Platform_Infra/errors.md` | `(unknown)` | 0 | 0 | 0 | 0 | 0 |
| 42 | pending | `File_review/GROUP_08_Platform_Infra/hash.md` | `app/core/utils/hash.py` | 3 | 0 | 1 | 1 | 1 |
| 43 | pending | `File_review/GROUP_08_Platform_Infra/validation.md` | `app/core/validation.py` | 4 | 0 | 1 | 2 | 1 |
| 44 | pending | `File_review/GROUP_08_Platform_Infra/webhook.md` | `app/core/webhook.py` | 5 | 0 | 2 | 2 | 1 |
| 45 | pending | `File_review/GROUP_09_SDK_CLI/main.md` | `app/cli/main.py` | 9 | 0 | 3 | 4 | 2 |
| 46 | pending | `File_review/GROUP_09_SDK_CLI/sdk.md` | `app/core/sdk.py` | 9 | 0 | 2 | 4 | 3 |
| 47 | pending | `File_review/GROUP_10_API/artifacts.md` | `app/api/routers/artifacts.py` | 4 | 0 | 2 | 1 | 1 |
| 48 | pending | `File_review/GROUP_10_API/main.md` | `app/api/main.py` | 3 | 0 | 0 | 3 | 0 |
| 49 | pending | `File_review/GROUP_10_API/nodes.md` | `app/api/routers/nodes.py` | 4 | 0 | 0 | 2 | 2 |
| 50 | pending | `File_review/GROUP_10_API/pipelines.md` | `app/api/routers/pipelines.py` | 7 | 0 | 3 | 2 | 2 |
| 51 | pending | `File_review/GROUP_10_API/plugins.md` | `app/api/routers/plugins.py` | 5 | 0 | 1 | 2 | 2 |
| 52 | pending | `File_review/GROUP_10_API/run_control.md` | `app/api/routers/run_control.py` | 3 | 0 | 0 | 2 | 1 |
| 53 | pending | `File_review/GROUP_10_API/runs.md` | `app/api/routers/runs.py` | 5 | 0 | 0 | 3 | 2 |
| 54 | pending | `File_review/GROUP_11_MCP/artifacts.md` | `app/mcp/handlers/artifacts.py` | 3 | 0 | 0 | 1 | 2 |
| 55 | pending | `File_review/GROUP_11_MCP/auth.md` | `app/mcp/auth.py` | 2 | 0 | 0 | 1 | 1 |
| 56 | pending | `File_review/GROUP_11_MCP/discovery.md` | `app/mcp/handlers/discovery.py` | 3 | 0 | 0 | 1 | 2 |
| 57 | pending | `File_review/GROUP_11_MCP/execution.md` | `app/mcp/handlers/execution.py` | 3 | 1 | 1 | 1 | 0 |
| 58 | pending | `File_review/GROUP_11_MCP/graph.md` | `app/mcp/handlers/graph.py` | 4 | 0 | 1 | 2 | 1 |
| 59 | pending | `File_review/GROUP_11_MCP/optimization.md` | `app/mcp/handlers/optimization.py` | 4 | 0 | 1 | 2 | 1 |
| 60 | pending | `File_review/GROUP_11_MCP/provenance.md` | `app/mcp/handlers/provenance.py` | 4 | 1 | 0 | 2 | 1 |
| 61 | pending | `File_review/GROUP_11_MCP/run_control.md` | `app/mcp/handlers/run_control.py` | 3 | 0 | 1 | 1 | 1 |
| 62 | pending | `File_review/GROUP_11_MCP/server.md` | `app/mcp/server.py` | 3 | 0 | 1 | 1 | 1 |
| 63 | pending | `File_review/GROUP_11_MCP/tool_registry.md` | `app/mcp/tool_registry.py` | 2 | 0 | 0 | 1 | 1 |
| 64 | pending | `File_review/GROUP_12_Domain_Models/audio_artifact_serializer.md` | `app/models/audio_artifact_serializer.py` | 4 | 0 | 1 | 2 | 1 |
| 65 | pending | `File_review/GROUP_12_Domain_Models/audio_sample.md` | `app/models/audio_sample.py` | 2 | 0 | 1 | 0 | 1 |
| 66 | pending | `File_review/GROUP_12_Domain_Models/deployment_artifact.md` | `(unknown)` | 0 | 0 | 0 | 0 | 0 |
| 67 | pending | `File_review/GROUP_12_Domain_Models/feature_array.md` | `app/models/feature_array.py` | 2 | 0 | 0 | 1 | 1 |
| 68 | pending | `File_review/GROUP_12_Domain_Models/ingestion.md` | `app/domain/ingestion.py` | 7 | 0 | 2 | 5 | 0 |
| 69 | pending | `File_review/GROUP_12_Domain_Models/model_artifact.md` | `app/models/model_artifact.py` | 1 | 0 | 1 | 0 | 0 |
| 70 | pending | `File_review/GROUP_12_Domain_Models/prediction_result.md` | `app/models/prediction_result.py` | 1 | 0 | 1 | 0 | 0 |
| 71 | pending | `File_review/GROUP_12_Domain_Models/project_manager.md` | `app/domain/project_manager.py` | 7 | 0 | 2 | 3 | 2 |
| 72 | pending | `File_review/GROUP_12_Domain_Models/quality_checker.md` | `app/domain/quality_checker.py` | 5 | 0 | 2 | 3 | 0 |
| 73 | pending | `File_review/GROUP_12_Domain_Models/tensor_batch.md` | `app/models/tensor_batch.py` | 2 | 0 | 0 | 1 | 1 |
| 74 | pending | `File_review/GROUP_12_Domain_Models/tflite_artifact.md` | `app/models/tflite_artifact.py` | 2 | 0 | 1 | 0 | 1 |
| 75 | pending | `File_review/GROUP_13_Audio_Plugins_Batch_1/audio_classifier_nodes.md` | `PluginPackage/Audio/audio_classifier/nodes.py` | 8 | 0 | 4 | 3 | 1 |
| 76 | pending | `File_review/GROUP_13_Audio_Plugins_Batch_1/audio_conditioner_nodes.md` | `PluginPackage/Audio/audio_conditioner/nodes.py` | 6 | 0 | 2 | 3 | 1 |
| 77 | pending | `File_review/GROUP_13_Audio_Plugins_Batch_1/audio_event_detector_nodes.md` | `PluginPackage/Audio/audio_event_detector/nodes.py` | 7 | 0 | 4 | 2 | 1 |
| 78 | pending | `File_review/GROUP_13_Audio_Plugins_Batch_1/audio_exporter_nodes.md` | `PluginPackage/Audio/audio_exporter/nodes.py` | 7 | 1 | 2 | 3 | 1 |
| 79 | pending | `File_review/GROUP_13_Audio_Plugins_Batch_1/audio_generator_nodes.md` | `PluginPackage/Audio/audio_generator/nodes.py` | 6 | 0 | 2 | 2 | 2 |
| 80 | pending | `File_review/GROUP_13_Audio_Plugins_Batch_1/audio_quality_gate_nodes.md` | `PluginPackage/Audio/audio_quality_gate/nodes.py` | 7 | 0 | 1 | 5 | 1 |
| 81 | pending | `File_review/GROUP_14_Audio_Plugins_Batch_2/alignment_node_nodes.md` | `PluginPackage/Audio/alignment_node/nodes.py` | 7 | 0 | 3 | 3 | 1 |
| 82 | pending | `File_review/GROUP_14_Audio_Plugins_Batch_2/audio_annotator_nodes.md` | `PluginPackage/Audio/audio_annotator/nodes.py` | 5 | 0 | 0 | 3 | 2 |
| 83 | pending | `File_review/GROUP_14_Audio_Plugins_Batch_2/augmentation_pipeline_nodes.md` | `PluginPackage/Audio/augmentation_pipeline/nodes.py` | 7 | 0 | 2 | 3 | 2 |
| 84 | pending | `File_review/GROUP_14_Audio_Plugins_Batch_2/dataset_ingest_nodes.md` | `PluginPackage/Audio/dataset_ingest/nodes.py` | 7 | 0 | 3 | 3 | 1 |
| 85 | pending | `File_review/GROUP_14_Audio_Plugins_Batch_2/feature_frontend_nodes.md` | `PluginPackage/Audio/feature_frontend/nodes.py` | 6 | 0 | 2 | 3 | 1 |
| 86 | pending | `File_review/GROUP_15_Audio_Plugins_Batch_3/environment_simulator_nodes.md` | `PluginPackage/Audio/environment_simulator/nodes.py` | 5 | 0 | 2 | 2 | 1 |
| 87 | pending | `File_review/GROUP_15_Audio_Plugins_Batch_3/segmenter_nodes.md` | `PluginPackage/Audio/segmenter/nodes.py` | 5 | 0 | 1 | 3 | 1 |
| 88 | pending | `File_review/GROUP_15_Audio_Plugins_Batch_3/speaker_separator_nodes.md` | `PluginPackage/Audio/speaker_separator/nodes.py` | 6 | 0 | 2 | 3 | 1 |
| 89 | pending | `File_review/GROUP_15_Audio_Plugins_Batch_3/speech_enhancer_nodes.md` | `PluginPackage/Audio/speech_enhancer/nodes.py` | 5 | 0 | 1 | 2 | 2 |
| 90 | pending | `File_review/GROUP_15_Audio_Plugins_Batch_3/speech_synthesizer_nodes.md` | `PluginPackage/Audio/speech_synthesizer/nodes.py` | 5 | 1 | 1 | 3 | 0 |
| 91 | pending | `File_review/GROUP_15_Audio_Plugins_Batch_3/stream_ingest_nodes.md` | `PluginPackage/Audio/stream_ingest/nodes.py` | 5 | 0 | 1 | 3 | 1 |
| 92 | pending | `File_review/GROUP_15_Audio_Plugins_Batch_3/stream_processor_nodes.md` | `PluginPackage/Audio/stream_processor/nodes.py` | 4 | 0 | 1 | 2 | 1 |
| 93 | pending | `File_review/GROUP_15_Audio_Plugins_Batch_3/voice_converter_nodes.md` | `PluginPackage/Audio/voice_converter/nodes.py` | 6 | 0 | 2 | 3 | 1 |
| 94 | pending | `File_review/GROUP_16_Common_Plugins/dataset_balancer_nodes.md` | `PluginPackage/Common/dataset_balancer/nodes.py` | 4 | 0 | 1 | 2 | 1 |
| 95 | pending | `File_review/GROUP_16_Common_Plugins/dataset_builder_nodes.md` | `PluginPackage/Common/dataset_builder/nodes.py` | 4 | 0 | 1 | 2 | 1 |
| 96 | pending | `File_review/GROUP_16_Common_Plugins/dataset_versioner_nodes.md` | `PluginPackage/Common/dataset_versioner/nodes.py` | 3 | 0 | 0 | 2 | 1 |
| 97 | pending | `File_review/GROUP_16_Common_Plugins/deployment_packager_nodes.md` | `PluginPackage/Common/deployment_packager/nodes.py` | 3 | 0 | 0 | 2 | 1 |
| 98 | pending | `File_review/GROUP_16_Common_Plugins/edge_optimizer_nodes.md` | `PluginPackage/Common/edge_optimizer/nodes.py` | 4 | 0 | 2 | 1 | 1 |
| 99 | pending | `File_review/GROUP_16_Common_Plugins/embedding_generator_nodes.md` | `PluginPackage/Common/embedding_generator/nodes.py` | 4 | 0 | 2 | 1 | 1 |
| 100 | pending | `File_review/GROUP_16_Common_Plugins/evaluator_nodes.md` | `PluginPackage/Common/evaluator/nodes.py` | 4 | 0 | 2 | 1 | 1 |
| 101 | pending | `File_review/GROUP_16_Common_Plugins/experiment_tracker_nodes.md` | `PluginPackage/Common/experiment_tracker/nodes.py` | 4 | 0 | 1 | 2 | 1 |
| 102 | pending | `File_review/GROUP_16_Common_Plugins/multimodal_fusion_nodes.md` | `PluginPackage/Common/multimodal_fusion/nodes.py` | 4 | 0 | 1 | 2 | 1 |
| 103 | pending | `File_review/GROUP_16_Common_Plugins/realtime_inference_nodes.md` | `PluginPackage/Common/realtime_inference/nodes.py` | 4 | 0 | 2 | 2 | 0 |
| 104 | pending | `File_review/GROUP_16_Common_Plugins/trainer_nodes.md` | `PluginPackage/Common/trainer/nodes.py` | 6 | 1 | 2 | 2 | 1 |
