# Implementation Plan: Speech Commands End-to-End Training Pipeline (Example 06)

## Overview

Implement a complete end-to-end ML pipeline under `examples/06_speech_commands_e2e/`
that extends Example 02 through feature extraction, model training, evaluation,
TFLite export, and inference. All processing steps are plugin nodes that
auto-discover into the existing `NodeRegistry`. No changes to `app/` are required.

All Python commands use `venv/bin/python` and `venv/bin/pip`.

## Tasks

- [x] 1. Scaffold project structure and install dependencies
  - Create `examples/06_speech_commands_e2e/plugins/__init__.py` (empty)
  - Create `examples/06_speech_commands_e2e/tests/__init__.py` (empty)
  - Create `examples/06_speech_commands_e2e/tests/conftest.py` with Hypothesis
    profiles and `audio_sample_strategy` / `feature_array_strategy` fixtures
  - Add a note in `README.md` (stub) that `data/` should symlink or copy from
    `examples/02_speech_commands/data/`; `run_train.py` falls back automatically
  - Install missing dependencies:
    `venv/bin/pip install tensorflow keras scikit-learn seaborn matplotlib`
  - _Requirements: 9.2, 12.13, 14.1_

- [x] 2. Implement `data_types.py` — new PortDataType subclasses
  - [x] 2.1 Create `examples/06_speech_commands_e2e/plugins/data_types.py`
    - Implement `FeatureArray(PortDataType)` with `data`, `label`, `sample_rate`,
      `source_path`, `metadata` fields and `_coerce_float32` field validator
    - Implement `ModelArtifact(PortDataType)` with `model_path`, `labels`,
      `history`, `metrics` fields
    - Implement `TFLiteArtifact(PortDataType)` with `tflite_path`, `labels`,
      `quantisation`, `file_size_bytes` fields
    - Implement `PredictionResult(PortDataType)` with `source_path`,
      `predicted_label`, `probabilities`, `metadata` fields
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [ ]* 2.2 Write property test for `FeatureArray` dtype invariant (P10)
    - **Property 10: FeatureArray dtype invariant**
    - **Validates: Requirements 1.6**
    - Add to `tests/test_data_types.py`

  - [ ]* 2.3 Write unit tests for all four PortDataType field contracts
    - Test default values, field presence, and `PortDataType` subclass registration
    - Add to `tests/test_data_types.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 3. Implement `feature_extractor.py` — FeatureExtractorNode
  - [x] 3.1 Create `examples/06_speech_commands_e2e/plugins/feature_extractor.py`
    - Declare `node_type = "feature_extractor"`, `NodeMetadata`, SISO ports
      (`list[AudioSample]` → `list[FeatureArray]`), and inner `Config(NodeConfig)`
      with all fields (`feature_type`, `n_mfcc`, `n_mels`, `n_fft`, `hop_length`,
      `fmax`, `fixed_length`, `normalize`)
    - Implement `process()`: MFCC path via `librosa.feature.mfcc`, log-mel path
      via `librosa.feature.melspectrogram` + `librosa.power_to_db`, transpose to
      `[T, F]`, pad/truncate to `fixed_length`, per-sample normalisation, cast to
      `float32`, yield `FeatureArray` with propagated label/sample_rate/path/metadata
    - Raise `ValueError` for empty waveforms; raise `ImportError` if librosa missing
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 12.1, 15.2_

  - [x]* 3.2 Write property test for fixed output shape (P1)
    - **Property 1: FeatureExtractor — Fixed Output Shape**
    - **Validates: Requirements 2.4, 2.9**
    - Add to `tests/test_feature_extractor.py`

  - [x]* 3.3 Write property test for float32 dtype (P2)
    - **Property 2: FeatureExtractor — Float32 dtype**
    - **Validates: Requirements 1.6, 2.2, 2.3**
    - Add to `tests/test_feature_extractor.py`

  - [x]* 3.4 Write property test for determinism (P3)
    - **Property 3: FeatureExtractor — Determinism**
    - **Validates: Requirements 2.8, 13.2**
    - Add to `tests/test_feature_extractor.py`

  - [x]* 3.5 Write property test for label propagation (P4)
    - **Property 4: FeatureExtractor — Label Propagation**
    - **Validates: Requirements 2.6**
    - Add to `tests/test_feature_extractor.py`

  - [x]* 3.6 Write property test for count preservation (P5)
    - **Property 5: FeatureExtractor — Count Preservation**
    - **Validates: Requirements 2.1**
    - Add to `tests/test_feature_extractor.py`

- [x] 4. Checkpoint — Ensure feature extractor tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement `dataset_builder.py` — DatasetBuilderNode
  - [x] 5.1 Create `examples/06_speech_commands_e2e/plugins/dataset_builder.py`
    - Declare `node_type = "dataset_builder"`, `NodeMetadata`, SISO ports
      (`list[FeatureArray]` → `dict`), and empty `Config(NodeConfig)`
    - Implement `process()`: derive sorted label list, sort features by
      `source_path` for determinism, split by `metadata["split"]`, call
      `to_arrays()` to stack and channel-expand to `[N, T, F, 1]`, encode labels
      as `int32` indices, return dict with `X_train/val/test`, `y_train/val/test`,
      `labels`, `input_shape`, `n_classes`
    - Raise `ValueError` for invalid split values
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 12.2, 13.3_

  - [x]* 5.2 Write property test for no sample loss (P6)
    - **Property 6: DatasetBuilder — No Sample Loss**
    - **Validates: Requirements 3.6**
    - Add to `tests/test_dataset_builder.py`

  - [x]* 5.3 Write property test for shape consistency (P7)
    - **Property 7: DatasetBuilder — Shape Consistency**
    - **Validates: Requirements 3.4, 3.7**
    - Add to `tests/test_dataset_builder.py`

  - [x]* 5.4 Write property test for label encoding consistency (P8)
    - **Property 8: DatasetBuilder — Label Encoding Consistency**
    - **Validates: Requirements 3.3**
    - Add to `tests/test_dataset_builder.py`

  - [x]* 5.5 Write property test for deterministic ordering (P9)
    - **Property 9: DatasetBuilder — Deterministic Ordering**
    - **Validates: Requirements 13.3**
    - Add to `tests/test_dataset_builder.py`

- [x] 6. Checkpoint — Ensure dataset builder tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement `model_builder.py` — ModelBuilderNode
  - Create `examples/06_speech_commands_e2e/plugins/model_builder.py`
  - Declare `node_type = "model_builder"`, `NodeMetadata`, multi-port
    (`dataset` InputPort → `model` OutputPort), and `Config(NodeConfig)` with
    `architecture`, `filters`, `num_layers`, `alpha`, `dropout_rate`,
    `learning_rate` fields
  - Implement `_build_ds_cnn()`: `Input` → `Conv2D` → `BN` → `ReLU` →
    N × (`DepthwiseConv2D` → `BN` → `ReLU` → `Conv2D(1×1)` → `BN` → `ReLU`) →
    `GlobalAveragePooling2D` → `Dropout` → `Dense(softmax)`
  - Implement `_build_mobilenet()`: `Conv2D(strides=2)` → `BN` → `ReLU6` →
    3 inverted residual blocks → `GlobalAveragePooling2D` → `Dropout` →
    `Dense(softmax)`
  - Implement `process()`: call `keras.utils.set_random_seed(seed)`, build model
    from `dataset["input_shape"]` and `dataset["n_classes"]`, compile with Adam +
    sparse_categorical_crossentropy + accuracy, return `{"model": model}`
  - Raise `ImportError` if TensorFlow missing
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 12.3, 13.4, 15.1_

- [x] 8. Implement `model_trainer.py` — ModelTrainerNode
  - Create `examples/06_speech_commands_e2e/plugins/model_trainer.py`
  - Declare `node_type = "model_trainer"`, `NodeMetadata`, multi-port
    (`model` + `dataset` InputPorts → `output` OutputPort of type `ModelArtifact`),
    and `Config(NodeConfig)` with `epochs`, `batch_size`, `output_path`,
    `checkpoint_path`, `min_val_accuracy`, `patience`
  - Implement `setup()`: verify TensorFlow importable, raise `ImportError` with
    install command if not
  - Implement `process()`: call `keras.utils.set_random_seed(seed)`, create
    output/checkpoint dirs, attach `EarlyStopping` + `ModelCheckpoint` +
    `ReduceLROnPlateau` callbacks, call `model.fit()`, save SavedModel to
    `output_path/saved_model/`, save `X_train` repr data as
    `output_path/saved_model/X_train_repr.npy`, warn if `val_accuracy` below
    threshold, return `ModelArtifact`
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 12.4, 13.1, 15.1, 15.3, 15.4_

- [x] 9. Implement `model_evaluator.py` — ModelEvaluatorNode
  - Create `examples/06_speech_commands_e2e/plugins/model_evaluator.py`
  - Declare `node_type = "model_evaluator"`, `NodeMetadata`, multi-port
    (`model_artifact` + `dataset` InputPorts → `output` OutputPort of type
    `ModelArtifact`), and `Config(NodeConfig)` with `output_path`,
    `plot_confusion_matrix`, `plot_training_curves`
  - Implement `setup()` / `teardown()` for lazy model loading / resource release
  - Implement `process()`: load SavedModel via `keras.saving.load_model`, run
    `model.predict()` on `X_test`, compute top-1 accuracy + per-class
    precision/recall/F1 via `sklearn.metrics`, compute confusion matrix, write
    `metrics.json`, optionally call `_plot_confusion_matrix()` and
    `_plot_training_curves()` helpers using matplotlib/seaborn, return updated
    `ModelArtifact` with metrics populated
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 12.5, 15.1_

- [x] 10. Implement `tflite_exporter.py` — TFLiteExporterNode
  - Create `examples/06_speech_commands_e2e/plugins/tflite_exporter.py`
  - Declare `node_type = "tflite_exporter"`, `NodeMetadata`, SISO ports
    (`ModelArtifact` → `TFLiteArtifact`), and `Config(NodeConfig)` with
    `quantisation`, `output_path`, `representative_samples`
  - Validate `quantisation` in `__init__`, raise `ValueError` for unknown values
  - Implement `process()`: create `TFLiteConverter.from_saved_model`, apply
    float16 or int8 optimisations (loading `X_train_repr.npy` for INT8 calibration),
    convert, write `model.tflite` and `labels.txt`, return `TFLiteArtifact` with
    `file_size_bytes` populated
  - Raise `ImportError` if TensorFlow missing
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 12.6, 15.1_

- [x] 11. Implement `inference_node.py` — InferenceNode
  - Create `examples/06_speech_commands_e2e/plugins/inference_node.py`
  - Declare `node_type = "inference"`, `NodeMetadata`, SISO ports
    (`list[FeatureArray]` → `list[PredictionResult]`), and `Config(NodeConfig)`
    with required `model_path` field
  - Implement `setup()`: check model file exists (raise `FileNotFoundError` if
    not), load `labels.txt`, create `tf.lite.Interpreter`, call
    `allocate_tensors()`, cache `_input_details` and `_output_details`
  - Implement `teardown()`: delete interpreter
  - Implement `process()`: for each `FeatureArray`, reshape to `[1, T, F, 1]`,
    handle INT8 quantisation (scale + zero_point), invoke interpreter, dequantise
    output if INT8, build `PredictionResult` with `predicted_label` and
    `probabilities` dict, print `filename → label (confidence%)` to stdout
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 12.7, 15.1_

- [x] 12. Checkpoint — Ensure all plugin node files are importable without errors
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Implement visualisation nodes
  - [x] 13.1 Create `examples/06_speech_commands_e2e/plugins/feature_visualizer.py`
    - Declare `node_type = "feature_visualizer"`, SISO pass-through
      (`list[FeatureArray]` → `list[FeatureArray]`), `Config` with `output_path`,
      `max_samples`, `feature_type`
    - Implement `process()`: save up to `max_samples` PNG files using
      `librosa.display.specshow` with appropriate axis labels, return input list
      unchanged
    - _Requirements: 11.1, 11.2, 12.8_

  - [x] 13.2 Create `examples/06_speech_commands_e2e/plugins/confusion_matrix_node.py`
    - Declare `node_type = "confusion_matrix_plot"`, SISO pass-through
      (`ModelArtifact` → `ModelArtifact`), `Config` with `output_path`,
      `normalize`, `figsize`
    - Implement `process()`: read `artifact.metrics["confusion_matrix"]`, optionally
      normalise rows, render seaborn heatmap with `annot=True` and label axes,
      save PNG, return artifact unchanged
    - _Requirements: 11.3, 11.4, 12.9_

  - [x] 13.3 Create `examples/06_speech_commands_e2e/plugins/training_curves_node.py`
    - Declare `node_type = "training_curves_plot"`, SISO pass-through
      (`ModelArtifact` → `ModelArtifact`), `Config` with `output_path`, `figsize`
    - Implement `process()`: read `artifact.history`, create 2-subplot figure
      (loss subplot + accuracy subplot), save PNG, return artifact unchanged
    - _Requirements: 11.5, 12.10_

- [x] 14. Write plugin discovery test
  - Create `examples/06_speech_commands_e2e/tests/test_plugin_discovery.py`
  - Set `GRAPHYN_PLUGINS_DIR` to the example's `plugins/` directory, import
    `get_registry`, assert all ten `node_type` strings are present in the registry
  - _Requirements: 12.13_

- [x] 15. Write pipeline YAML files
  - [x] 15.1 Create `examples/06_speech_commands_e2e/pipeline_train.yaml`
    - Phase 1 preprocessing pipeline for the `yes` label only (for CLI testing):
      `file_input` → `clean` → `trim` → `silence_detector` →
      `command_validator` → `pitch_shift` → `time_stretch` → `duplicate` →
      `split` → `file_export` with `append: true`
    - Include `seed: 42` at pipeline level
    - _Requirements: 9.1, 9.6_

  - [x] 15.2 Create `examples/06_speech_commands_e2e/pipeline_infer.yaml`
    - Inference pipeline: `file_input` → `clean` → `trim` →
      `feature_extractor` (identical config to training) → `inference`
    - Include `seed: 42` at pipeline level
    - _Requirements: 10.1, 10.4_

- [x] 16. Write SDK scripts
  - [x] 16.1 Create `examples/06_speech_commands_e2e/run_train.py`
    - Set `GRAPHYN_PLUGINS_DIR` before SDK import; define `phase1_preprocess(command)`
      running the preprocessing pipeline with `append=True` for one label; define
      `phase2_train()` running the full ML pipeline; `main()` loops over all 6
      labels for Phase 1, saves `feature_config.json`, runs Phase 2, prints
      summary (val_accuracy, test_accuracy, SavedModel size KB, TFLite size KB);
      exit code 1 with human-readable message on any exception
    - _Requirements: 9.2, 9.3, 9.4, 9.5, 9.6, 15.5_

  - [x] 16.2 Create `examples/06_speech_commands_e2e/run_infer.py`
    - Accept `--model` and `--input` CLI arguments; load `feature_config.json`
      from `output/` (fallback to hardcoded defaults); run inference pipeline;
      print warnings (not exceptions) for undecodable files; exit code 1 on
      pipeline error
    - _Requirements: 10.2, 10.3, 10.4, 10.5, 15.6_

- [x] 17. Write `README.md`
  - Create `examples/06_speech_commands_e2e/README.md`
  - Document: prerequisites (TF install command), data setup (symlink from
    Example 02 or `prepare_real_data.py`), training usage
    (`venv/bin/python run_train.py`), inference usage (`run_infer.py --model ...
    --input ...`), expected outputs (SavedModel, TFLite, metrics.json, plots),
    and architecture overview (DS-CNN vs MobileNet)
  - _Requirements: 9.2, 10.2_

- [x] 18. Write inference node unit tests
  - Create `examples/06_speech_commands_e2e/tests/test_inference_node.py`
  - Mock `tf.lite.Interpreter` to avoid requiring a real TFLite model; test
    `setup()` raises `FileNotFoundError` for missing model path; test `process()`
    returns correct `PredictionResult` structure; test INT8 dequantisation path
  - _Requirements: 8.2, 8.4, 8.5, 8.6, 8.8_

- [x] 19. Final checkpoint — Run full test suite
  - Run `venv/bin/pytest examples/06_speech_commands_e2e/tests/ -v`
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation before moving to the next phase
- Property tests (P1–P10) validate universal correctness properties from `design_testing.md`
- Unit tests validate specific examples and edge cases
- All plugin nodes follow the existing pattern from `examples/02_speech_commands/plugins/command_validator.py`
- Multi-port nodes (`ModelBuilderNode`, `ModelTrainerNode`, `ModelEvaluatorNode`) override
  `process(self, inputs: dict)` and return `dict`; all others use the SISO shorthand
- The `ModelTrainerNode` saves `X_train_repr.npy` alongside the SavedModel so
  `TFLiteExporterNode` can build the INT8 representative dataset without re-running
  the full pipeline
