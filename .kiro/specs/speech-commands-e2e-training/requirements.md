# Requirements Document

## Introduction

Example 06 extends the Example 02 speech command dataset pipeline into a complete
end-to-end machine learning system. Where Example 02 stops at a clean, split,
augmented dataset, Example 06 continues through feature extraction, model training,
evaluation, export, and real-time inference.

The system is composed of two pipelines that share plugin nodes:

1. **Training Pipeline** — takes the preprocessed dataset produced by Example 02,
   extracts acoustic features (MFCC / log-mel spectrogram), trains a DS-CNN or
   MobileNet-style classifier with Keras 3 + TensorFlow backend, evaluates it,
   and exports both a SavedModel and a TFLite flatbuffer.

2. **Inference Pipeline** — loads a single audio clip (or a directory of clips),
   runs the same preprocessing and feature extraction as the training pipeline,
   loads the exported model, and produces per-class probability predictions with
   a top-1 label decision.

All new processing steps are implemented as plugin nodes that follow the existing
`Node` subclass pattern (ClassVar metadata, typed ports, inner `Config(NodeConfig)`)
and live under `examples/06_speech_commands_e2e/plugins/`.

---

## Glossary

- **AudioSample**: The existing `PortDataType` defined in `app/models/audio_sample.py`.
  Carries a float32 waveform, sample rate, label, and metadata dict.
- **FeatureArray**: New `PortDataType`. Carries a 2-D or 3-D numpy float32 array
  (the computed acoustic feature), the originating label, sample rate, and metadata.
- **ModelArtifact**: New `PortDataType`. Carries the filesystem path to a trained
  Keras SavedModel directory, the label list, training history, and evaluation metrics.
- **TFLiteArtifact**: New `PortDataType`. Carries the filesystem path to a `.tflite`
  flatbuffer, the label list, and quantisation metadata.
- **PredictionResult**: New `PortDataType`. Carries the top-1 predicted label,
  the full per-class probability vector, the source audio path, and metadata.
- **Training Pipeline**: The pipeline defined in
  `examples/06_speech_commands_e2e/pipeline_train.yaml` (and `run_train.py`).
- **Inference Pipeline**: The pipeline defined in
  `examples/06_speech_commands_e2e/pipeline_infer.yaml` (and `run_infer.py`).
- **DS-CNN**: Depthwise Separable CNN — a lightweight convolutional architecture
  suitable for keyword spotting on edge devices.
- **MobileNet-style**: A MobileNetV2-inspired architecture using inverted residual
  blocks with depthwise separable convolutions.
- **MFCC**: Mel-Frequency Cepstral Coefficients — a compact acoustic feature
  representation derived from the mel spectrogram.
- **Log-mel spectrogram**: The log-compressed mel-filterbank energy matrix used
  as a 2-D image-like input to convolutional models.
- **SavedModel**: TensorFlow's portable model serialisation format (a directory).
- **TFLite**: TensorFlow Lite — a flatbuffer format for on-device inference.
- **INT8 quantisation**: Post-training quantisation that maps float32 weights and
  activations to 8-bit integers, reducing model size and latency.
- **Plugin**: A Python file placed in `examples/06_speech_commands_e2e/plugins/`
  that is auto-discovered by `AutoDiscovery` and registered in `NodeRegistry`.
- **Node**: A `Node` subclass with `ClassVar` metadata, typed `InputPort` /
  `OutputPort` declarations, and an inner `Config(NodeConfig)`.
- **SISO node**: A node with exactly one input port named `"input"` and one output
  port named `"output"`, using the SISO shorthand `process(self, data)` signature.
- **Lifecycle hooks**: `setup()`, `on_start()`, `on_end()`, `on_error()`,
  `teardown()` — called by the pipeline executor around each `process()` call.
- **Seed**: Integer passed to `Node.__init__` for deterministic random behaviour.
- **Labels**: The six command classes: `yes`, `no`, `up`, `down`, `go`, `stop`.
- **Top-1 accuracy**: The fraction of test samples for which the highest-probability
  class matches the ground-truth label.
- **Confusion matrix**: An N×N matrix where entry (i, j) is the number of samples
  of true class i predicted as class j.

---

## Requirements

### Requirement 1: New PortDataTypes

**User Story:** As a pipeline author, I want strongly-typed data types for features,
model artifacts, TFLite artifacts, and predictions, so that port compatibility is
enforced at pipeline construction time and the TypeCatalogue reflects all types.

#### Acceptance Criteria

1. THE `FeatureArray` SHALL be a `PortDataType` subclass with fields:
   `data: np.ndarray` (float32, shape `[n_frames, n_bins]` or `[n_frames, n_bins, 1]`),
   `label: str`, `sample_rate: int`, `source_path: str`, and `metadata: dict`.
2. THE `ModelArtifact` SHALL be a `PortDataType` subclass with fields:
   `model_path: str` (path to SavedModel directory), `labels: list[str]`,
   `history: dict` (Keras training history), and `metrics: dict` (evaluation metrics).
3. THE `TFLiteArtifact` SHALL be a `PortDataType` subclass with fields:
   `tflite_path: str`, `labels: list[str]`, and `quantisation: str`
   (`"float32"`, `"float16"`, or `"int8"`).
4. THE `PredictionResult` SHALL be a `PortDataType` subclass with fields:
   `source_path: str`, `predicted_label: str`, `probabilities: dict[str, float]`
   (mapping each label to its probability), and `metadata: dict`.
5. WHEN `AutoDiscovery` scans the plugins directory, THE `TypeCatalogue` SHALL
   contain all four new types under their fully-qualified names.
6. FOR ALL `FeatureArray` objects `f`, `f.data.dtype` SHALL equal `numpy.float32`.

---

### Requirement 2: Feature Extraction Node (MFCC / Log-Mel)

**User Story:** As a data scientist, I want a feature extraction node that converts
preprocessed audio into MFCC or log-mel spectrogram arrays, so that the model
receives consistent, normalised acoustic features.

#### Acceptance Criteria

1. THE `FeatureExtractorNode` SHALL accept `list[AudioSample]` on its `"input"` port
   and produce `list[FeatureArray]` on its `"output"` port.
2. WHEN `feature_type` is `"mfcc"`, THE `FeatureExtractorNode` SHALL compute
   `n_mfcc` coefficients (default 40) using librosa with `n_fft=512`,
   `hop_length=160`, `n_mels=40`, and `fmax=8000`.
3. WHEN `feature_type` is `"log_mel"`, THE `FeatureExtractorNode` SHALL compute
   a log-mel spectrogram with `n_mels` bins (default 40), `n_fft=512`,
   `hop_length=160`, and `fmax=8000`, then apply `librosa.power_to_db`.
4. THE `FeatureExtractorNode` SHALL pad or truncate each feature array to exactly
   `fixed_length` frames (default 101) along the time axis, producing a
   deterministic output shape of `[fixed_length, n_mfcc_or_n_mels]`.
5. WHEN `normalize` is `true`, THE `FeatureExtractorNode` SHALL apply per-sample
   mean-and-variance normalisation to the feature array (zero mean, unit variance).
6. THE `FeatureExtractorNode` SHALL propagate `label`, `sample_rate`, `path`, and
   `metadata` from the source `AudioSample` into the output `FeatureArray`.
7. IF an `AudioSample` has an empty waveform (`len(data) == 0`), THEN THE
   `FeatureExtractorNode` SHALL raise a `ValueError` identifying the source path.
8. FOR ALL `AudioSample` inputs with identical waveform and config, THE
   `FeatureExtractorNode` SHALL produce identical `FeatureArray` outputs
   (deterministic, no random state).
9. FOR ALL valid `AudioSample` inputs, THE `FeatureExtractorNode` SHALL produce
   `FeatureArray` outputs where `data.shape[0] == fixed_length` (fixed time axis).
10. FOR ALL valid `AudioSample` inputs, THE `FeatureExtractorNode` SHALL produce
    `FeatureArray` outputs where `data.shape[1]` equals `n_mfcc` (for MFCC) or
    `n_mels` (for log-mel).

---

### Requirement 3: Dataset Builder Node

**User Story:** As a data scientist, I want a node that assembles extracted features
into train/val/test numpy arrays ready for Keras, so that the model training node
receives a single, well-structured dataset object.

#### Acceptance Criteria

1. THE `DatasetBuilderNode` SHALL accept `list[FeatureArray]` on its `"input"` port
   and produce a `dict` on its `"output"` port containing keys `"X_train"`,
   `"X_val"`, `"X_test"`, `"y_train"`, `"y_val"`, `"y_test"`, and `"labels"`.
2. THE `DatasetBuilderNode` SHALL derive the train/val/test split from the
   `"split"` key in each `FeatureArray`'s metadata (values: `"train"`, `"val"`,
   `"test"`), preserving the split assignments made by the upstream `split` node.
3. THE `DatasetBuilderNode` SHALL encode labels as integer indices using a sorted
   label list, and store the sorted label list under the `"labels"` key.
4. THE `DatasetBuilderNode` SHALL expand feature arrays to shape
   `[n_samples, fixed_length, n_bins, 1]` (adding a channel dimension) for
   compatibility with 2-D convolutional layers.
5. IF any `FeatureArray` has a `"split"` metadata key with a value other than
   `"train"`, `"val"`, or `"test"`, THEN THE `DatasetBuilderNode` SHALL raise a
   `ValueError` identifying the invalid split value.
6. FOR ALL dataset outputs, `len(X_train) + len(X_val) + len(X_test)` SHALL equal
   the total number of input `FeatureArray` objects (no samples lost or duplicated).
7. FOR ALL dataset outputs, `len(X_train) == len(y_train)`,
   `len(X_val) == len(y_val)`, and `len(X_test) == len(y_test)` SHALL hold.

---

### Requirement 4: Model Creation Node

**User Story:** As a data scientist, I want a node that constructs an untrained
Keras 3 model (DS-CNN or MobileNet-style), so that the architecture is reproducible
and configurable without modifying training code.

#### Acceptance Criteria

1. THE `ModelBuilderNode` SHALL accept a `dict` (dataset metadata) on its
   `"dataset"` input port and produce a Keras `Model` object on its `"model"` port.
2. WHEN `architecture` is `"ds_cnn"`, THE `ModelBuilderNode` SHALL construct a
   Depthwise Separable CNN with configurable `num_layers` (default 4) and
   `filters` (default 64), using `keras.layers.DepthwiseConv2D` and
   `keras.layers.Conv2D`.
3. WHEN `architecture` is `"mobilenet"`, THE `ModelBuilderNode` SHALL construct a
   MobileNetV2-style model using inverted residual blocks with depthwise separable
   convolutions and configurable `alpha` width multiplier (default 1.0).
4. THE `ModelBuilderNode` SHALL infer the input shape from the dataset metadata
   (`fixed_length`, `n_bins`) and the number of output classes from `len(labels)`.
5. THE `ModelBuilderNode` SHALL use `keras.layers.GlobalAveragePooling2D` before
   the final `Dense` layer with `softmax` activation.
6. THE `ModelBuilderNode` SHALL include `keras.layers.BatchNormalization` and
   `keras.layers.Dropout` (rate configurable, default 0.25) for regularisation.
7. WHEN `seed` is provided, THE `ModelBuilderNode` SHALL set `keras.utils.set_random_seed`
   to that value before constructing the model, ensuring reproducible weight
   initialisation.
8. THE `ModelBuilderNode` SHALL compile the model with `Adam` optimiser
   (learning rate configurable, default 0.001), `sparse_categorical_crossentropy`
   loss, and `accuracy` metric.

---

### Requirement 5: Model Training Node

**User Story:** As a data scientist, I want a node that trains the Keras model on
the assembled dataset with configurable callbacks, so that training is reproducible,
observable, and produces a persisted SavedModel artifact.

#### Acceptance Criteria

1. THE `ModelTrainerNode` SHALL accept a Keras `Model` on its `"model"` port and
   a `dict` dataset on its `"dataset"` port, and produce a `ModelArtifact` on its
   `"output"` port.
2. THE `ModelTrainerNode` SHALL train for `epochs` (default 30) with `batch_size`
   (default 32) using the `"X_train"` / `"y_train"` arrays and validate on
   `"X_val"` / `"y_val"`.
3. THE `ModelTrainerNode` SHALL attach a `keras.callbacks.EarlyStopping` callback
   monitoring `"val_loss"` with `patience` (default 5) and `restore_best_weights=True`.
4. THE `ModelTrainerNode` SHALL attach a `keras.callbacks.ModelCheckpoint` callback
   saving the best model (by `val_accuracy`) to `checkpoint_path`.
5. THE `ModelTrainerNode` SHALL attach a `keras.callbacks.ReduceLROnPlateau`
   callback monitoring `"val_loss"` with `factor=0.5` and `patience=3`.
6. THE `ModelTrainerNode` SHALL save the final model as a TensorFlow SavedModel
   to `output_path/saved_model/`.
7. THE `ModelTrainerNode` SHALL store the complete Keras training history
   (all epoch metrics) in the `ModelArtifact.history` field.
8. WHEN `seed` is provided, THE `ModelTrainerNode` SHALL call
   `keras.utils.set_random_seed` before `model.fit()` to ensure reproducible
   training.
9. IF training produces a `val_accuracy` below `min_val_accuracy` (default 0.0,
   i.e. no threshold by default), THEN THE `ModelTrainerNode` SHALL log a warning
   but SHALL still produce the `ModelArtifact` and continue the pipeline.
10. THE `ModelTrainerNode` SHALL use `setup()` to verify TensorFlow is importable
    and raise `ImportError` with a clear message if it is not.

---

### Requirement 6: Model Evaluation Node

**User Story:** As a data scientist, I want a node that evaluates the trained model
on the held-out test set and produces a confusion matrix and per-class metrics, so
that I can assess model quality before deployment.

#### Acceptance Criteria

1. THE `ModelEvaluatorNode` SHALL accept a `ModelArtifact` on its `"model_artifact"`
   port and a `dict` dataset on its `"dataset"` port, and produce a `ModelArtifact`
   on its `"output"` port with the `metrics` field populated.
2. THE `ModelEvaluatorNode` SHALL compute top-1 accuracy, per-class precision,
   per-class recall, and per-class F1-score on `"X_test"` / `"y_test"`.
3. THE `ModelEvaluatorNode` SHALL compute and store the full N×N confusion matrix
   (as a nested list of integers) in `metrics["confusion_matrix"]`.
4. THE `ModelEvaluatorNode` SHALL write a JSON file to `output_path/metrics.json`
   containing all computed metrics.
5. WHEN `plot_confusion_matrix` is `true`, THE `ModelEvaluatorNode` SHALL save a
   matplotlib confusion matrix heatmap to `output_path/confusion_matrix.png` using
   the label names on both axes.
6. WHEN `plot_training_curves` is `true`, THE `ModelEvaluatorNode` SHALL save a
   matplotlib figure with two subplots (loss and accuracy over epochs) to
   `output_path/training_curves.png` using data from `ModelArtifact.history`.
7. FOR ALL evaluation runs on the same model and test set, THE `ModelEvaluatorNode`
   SHALL produce identical metric values (deterministic inference).
8. THE `ModelEvaluatorNode` SHALL load the SavedModel from `ModelArtifact.model_path`
   using `keras.saving.load_model` in `setup()` and release it in `teardown()`.

---

### Requirement 7: TFLite Export Node

**User Story:** As an embedded engineer, I want a node that converts the trained
SavedModel to TFLite with optional INT8 quantisation, so that the model can be
deployed on microcontrollers and mobile devices.

#### Acceptance Criteria

1. THE `TFLiteExporterNode` SHALL accept a `ModelArtifact` on its `"input"` port
   and produce a `TFLiteArtifact` on its `"output"` port.
2. WHEN `quantisation` is `"float32"`, THE `TFLiteExporterNode` SHALL convert the
   SavedModel to TFLite without quantisation and write the flatbuffer to
   `output_path/model.tflite`.
3. WHEN `quantisation` is `"float16"`, THE `TFLiteExporterNode` SHALL apply
   `tf.lite.Optimize.DEFAULT` with `target_spec.supported_types = [tf.float16]`.
4. WHEN `quantisation` is `"int8"`, THE `TFLiteExporterNode` SHALL apply full
   integer quantisation using a representative dataset generator that yields
   batches from `"X_train"` (minimum 100 batches), with `inference_input_type`
   and `inference_output_type` set to `tf.uint8`.
5. THE `TFLiteExporterNode` SHALL write a `labels.txt` file (one label per line,
   sorted) alongside the `.tflite` file.
6. THE `TFLiteExporterNode` SHALL record the flatbuffer file size in bytes in
   `TFLiteArtifact.quantisation` metadata.
7. FOR ALL `quantisation` values, the output `.tflite` file SHALL be loadable by
   `tf.lite.Interpreter` without error.
8. IF `quantisation` is not one of `"float32"`, `"float16"`, or `"int8"`, THEN
   THE `TFLiteExporterNode` SHALL raise a `ValueError` at construction time.

---

### Requirement 8: Inference Node

**User Story:** As a developer, I want an inference node that loads a TFLite model
and runs predictions on preprocessed feature arrays, so that the inference pipeline
produces human-readable label predictions.

#### Acceptance Criteria

1. THE `InferenceNode` SHALL accept `list[FeatureArray]` on its `"input"` port and
   produce `list[PredictionResult]` on its `"output"` port.
2. THE `InferenceNode` SHALL load the TFLite flatbuffer from `model_path` and the
   label list from the sibling `labels.txt` file in `setup()`.
3. THE `InferenceNode` SHALL allocate tensors once in `setup()` and reuse the
   `tf.lite.Interpreter` across all `process()` calls.
4. FOR EACH `FeatureArray`, THE `InferenceNode` SHALL reshape the feature to match
   the interpreter's expected input shape, invoke the interpreter, and extract the
   output tensor as a probability vector.
5. THE `InferenceNode` SHALL set `predicted_label` to the label with the highest
   probability in the output vector.
6. THE `InferenceNode` SHALL populate `PredictionResult.probabilities` as a dict
   mapping each label string to its float probability, with all values summing to
   approximately 1.0 (within 1e-5 tolerance).
7. THE `InferenceNode` SHALL release the `tf.lite.Interpreter` in `teardown()`.
8. IF `model_path` does not exist at `setup()` time, THEN THE `InferenceNode`
   SHALL raise a `FileNotFoundError` with the missing path.
9. FOR ALL `FeatureArray` inputs with identical data, THE `InferenceNode` SHALL
   produce identical `PredictionResult` outputs (deterministic inference).

---

### Requirement 9: Training Pipeline Composition

**User Story:** As a data scientist, I want a complete, runnable training pipeline
defined in a YAML file and a Python SDK script, so that I can reproduce the full
training run with a single command.

#### Acceptance Criteria

1. THE Training Pipeline SHALL be defined in
   `examples/06_speech_commands_e2e/pipeline_train.yaml` with nodes in this order:
   `file_input` → `clean` → `trim` → `silence_detector` → `command_validator` →
   `pitch_shift` → `time_stretch` → `duplicate` → `split` →
   `feature_extractor` → `dataset_builder` → `model_builder` →
   `model_trainer` → `model_evaluator` → `tflite_exporter`.
2. THE `run_train.py` script SHALL set `GRAPHYN_PLUGINS_DIR` to the example's
   `plugins/` directory before importing the SDK, so that all plugin nodes are
   auto-discovered.
3. THE `run_train.py` script SHALL process all six command labels (`yes`, `no`,
   `up`, `down`, `go`, `stop`) using the same append-mode pattern as Example 02
   for the data preprocessing stages.
4. THE Training Pipeline SHALL write all outputs (SavedModel, TFLite, metrics,
   plots) to `examples/06_speech_commands_e2e/output/`.
5. WHEN the training pipeline completes successfully, THE `run_train.py` script
   SHALL print a summary including: final val_accuracy, test accuracy, model size
   in KB, and TFLite size in KB.
6. THE Training Pipeline SHALL use `seed: 42` at the pipeline level, and all
   nodes that accept a seed SHALL receive it from the pipeline executor.

---

### Requirement 10: Inference Pipeline Composition

**User Story:** As a developer, I want a complete, runnable inference pipeline that
loads a trained TFLite model and classifies new audio clips, so that I can test
the deployed model without writing custom inference code.

#### Acceptance Criteria

1. THE Inference Pipeline SHALL be defined in
   `examples/06_speech_commands_e2e/pipeline_infer.yaml` with nodes in this order:
   `file_input` → `clean` → `trim` → `feature_extractor` → `inference`.
2. THE `run_infer.py` script SHALL accept a `--model` argument pointing to the
   `.tflite` file and an `--input` argument pointing to a directory of WAV files.
3. THE `run_infer.py` script SHALL print each prediction as:
   `<filename>  →  <predicted_label>  (<confidence>%)`.
4. THE Inference Pipeline SHALL use the same `feature_extractor` configuration
   (identical `feature_type`, `n_mfcc`/`n_mels`, `fixed_length`, `normalize`)
   as the Training Pipeline to ensure feature consistency.
5. WHEN the input directory contains files with no recognised audio content,
   THE Inference Pipeline SHALL skip those files and log a warning rather than
   raising an exception.

---

### Requirement 11: Visualisation Nodes

**User Story:** As a data scientist, I want optional visualisation nodes that
render feature maps, confusion matrices, and training curves as image files, so
that I can inspect model behaviour without writing separate analysis scripts.

#### Acceptance Criteria

1. THE `FeatureVisualizerNode` SHALL accept `list[FeatureArray]` on its `"input"`
   port, save up to `max_samples` (default 5) feature array images as PNG files
   to `output_path`, and pass the list through unchanged on its `"output"` port.
2. THE `FeatureVisualizerNode` SHALL render each feature array using
   `librosa.display.specshow` with appropriate axis labels (`time` and `mel` or
   `MFCC coefficient`).
3. THE `ConfusionMatrixNode` SHALL accept a `ModelArtifact` on its `"input"` port,
   render the confusion matrix stored in `metrics["confusion_matrix"]` as a
   seaborn heatmap, save it to `output_path/confusion_matrix.png`, and pass the
   `ModelArtifact` through unchanged on its `"output"` port.
4. WHEN `normalize` is `true`, THE `ConfusionMatrixNode` SHALL normalise each row
   of the confusion matrix by the row sum before rendering, showing recall per class.
5. THE `TrainingCurvesNode` SHALL accept a `ModelArtifact` on its `"input"` port,
   render loss and accuracy curves from `ModelArtifact.history`, save the figure
   to `output_path/training_curves.png`, and pass the `ModelArtifact` through
   unchanged on its `"output"` port.

---

### Requirement 12: Plugin Architecture Compliance

**User Story:** As a platform engineer, I want all new nodes to comply with the
existing plugin architecture, so that they are auto-discovered, appear in the
NodeRegistry, and work with the existing API and SDK without modification.

#### Acceptance Criteria

1. THE `FeatureExtractorNode` SHALL declare `node_type: ClassVar[str] = "feature_extractor"`.
2. THE `DatasetBuilderNode` SHALL declare `node_type: ClassVar[str] = "dataset_builder"`.
3. THE `ModelBuilderNode` SHALL declare `node_type: ClassVar[str] = "model_builder"`.
4. THE `ModelTrainerNode` SHALL declare `node_type: ClassVar[str] = "model_trainer"`.
5. THE `ModelEvaluatorNode` SHALL declare `node_type: ClassVar[str] = "model_evaluator"`.
6. THE `TFLiteExporterNode` SHALL declare `node_type: ClassVar[str] = "tflite_exporter"`.
7. THE `InferenceNode` SHALL declare `node_type: ClassVar[str] = "inference"`.
8. THE `FeatureVisualizerNode` SHALL declare `node_type: ClassVar[str] = "feature_visualizer"`.
9. THE `ConfusionMatrixNode` SHALL declare `node_type: ClassVar[str] = "confusion_matrix_plot"`.
10. THE `TrainingCurvesNode` SHALL declare `node_type: ClassVar[str] = "training_curves_plot"`.
11. FOR ALL new nodes, THE `NodeConfig` inner class SHALL use `extra="forbid"` (inherited
    from `NodeConfig`) so that unknown YAML fields raise `ValidationError`.
12. FOR ALL new nodes that perform expensive initialisation (model loading, TF session
    creation), THE node SHALL perform that initialisation in `setup()`, not `__init__()`.
13. WHEN `AutoDiscovery` scans `examples/06_speech_commands_e2e/plugins/`, THE
    `NodeRegistry` SHALL contain all ten new node types without raising
    `DuplicateNodeTypeError` or `NodeMetadataError`.

---

### Requirement 13: Reproducibility

**User Story:** As a researcher, I want the training pipeline to produce the same
model weights and metrics when run twice with the same seed, so that experiments
are reproducible and results are comparable.

#### Acceptance Criteria

1. WHEN the Training Pipeline is run twice with `seed: 42` and identical input
   data, THE `ModelTrainerNode` SHALL produce SavedModel checkpoints with
   identical architecture (layer names, shapes, and parameter counts).
2. THE `FeatureExtractorNode` SHALL produce byte-identical `.npy` feature arrays
   for the same input audio and configuration (no random state in feature extraction).
3. THE `DatasetBuilderNode` SHALL produce arrays in a deterministic order (sorted
   by source path within each split) so that `X_train[i]` always corresponds to
   the same sample across runs.
4. WHERE `seed` is set, THE `ModelBuilderNode` SHALL call
   `keras.utils.set_random_seed(seed)` before weight initialisation, ensuring
   identical initial weights across runs.

---

### Requirement 14: Performance and Resource Constraints

**User Story:** As a developer, I want the pipeline to complete training within
reasonable time and memory bounds on a standard workstation, so that iteration
cycles are practical.

#### Acceptance Criteria

1. THE Training Pipeline SHALL complete a full training run (30 epochs, 6 classes,
   ~4800 samples) in under 30 minutes on a CPU-only workstation with 8 GB RAM.
2. THE `FeatureExtractorNode` SHALL process 4800 one-second audio clips in under
   60 seconds on a CPU-only workstation.
3. THE `TFLiteExporterNode` SHALL produce a float32 TFLite model no larger than
   2 MB for the DS-CNN architecture with default configuration.
4. THE `TFLiteExporterNode` SHALL produce an INT8 TFLite model no larger than
   512 KB for the DS-CNN architecture with default configuration.
5. THE `InferenceNode` SHALL classify a single one-second audio clip in under
   100 ms on a CPU-only workstation (excluding model load time).
6. WHILE the Training Pipeline is running, THE `ModelTrainerNode` SHALL not
   accumulate GPU memory across epochs (tensors released after each batch).

---

### Requirement 15: Error Handling and Observability

**User Story:** As a developer, I want clear error messages and progress logging
throughout both pipelines, so that failures are easy to diagnose and progress is
visible during long training runs.

#### Acceptance Criteria

1. IF TensorFlow is not installed, THEN THE `ModelBuilderNode`, `ModelTrainerNode`,
   `ModelEvaluatorNode`, and `TFLiteExporterNode` SHALL each raise `ImportError`
   with a message that includes the install command
   `venv/bin/pip install tensorflow`.
2. IF librosa is not installed, THEN THE `FeatureExtractorNode` SHALL raise
   `ImportError` with a message that includes `venv/bin/pip install librosa`.
3. THE `ModelTrainerNode` SHALL log epoch-level metrics (loss, val_loss, accuracy,
   val_accuracy) to stdout in a format compatible with the existing pipeline
   logging pattern.
4. IF the `output_path` directory cannot be created (e.g. permission denied),
   THEN THE `ModelTrainerNode` SHALL raise `OSError` with the path and reason.
5. THE `run_train.py` script SHALL exit with code 1 and print a human-readable
   error message if any pipeline node raises an exception, without printing a
   raw Python traceback to the user.
6. THE `run_infer.py` script SHALL print a warning (not raise) when an input
   audio file cannot be decoded, and SHALL continue processing remaining files.
