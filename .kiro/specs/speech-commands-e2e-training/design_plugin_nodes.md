# Design: Plugin Nodes

All nodes live in `examples/06_speech_commands_e2e/plugins/`. Each file is a
standalone plugin that `AutoDiscovery` picks up via `GRAPHYN_PLUGINS_DIR`.

---

## 1. `FeatureExtractorNode` — `feature_extractor.py`

**node_type:** `"feature_extractor"`  
**Category:** `"Feature Extraction"`  
**Pattern:** SISO (`list[AudioSample]` → `list[FeatureArray]`)

### Config

```python
class Config(NodeConfig):
    feature_type: str = "mfcc"      # "mfcc" | "log_mel"
    n_mfcc: int = 40                # coefficients (mfcc mode)
    n_mels: int = 40                # mel bins (log_mel mode)
    n_fft: int = 512
    hop_length: int = 160
    fmax: float = 8000.0
    fixed_length: int = 101         # frames — pad/truncate to this
    normalize: bool = True          # per-sample mean/variance normalisation
```

### process() logic

```
for each AudioSample s:
    if len(s.data) == 0: raise ValueError(s.path)
    if feature_type == "mfcc":
        feat = librosa.feature.mfcc(y=s.data, sr=s.sample_rate,
                                     n_mfcc=n_mfcc, n_fft=n_fft,
                                     hop_length=hop_length, n_mels=n_mels,
                                     fmax=fmax)          # shape [n_mfcc, T]
        feat = feat.T                                    # → [T, n_mfcc]
    else:  # log_mel
        S = librosa.feature.melspectrogram(y=s.data, sr=s.sample_rate,
                                            n_mels=n_mels, n_fft=n_fft,
                                            hop_length=hop_length, fmax=fmax)
        feat = librosa.power_to_db(S, ref=np.max).T     # → [T, n_mels]

    # Pad or truncate to fixed_length frames
    if feat.shape[0] < fixed_length:
        pad = fixed_length - feat.shape[0]
        feat = np.pad(feat, ((0, pad), (0, 0)), mode="constant")
    else:
        feat = feat[:fixed_length]

    # Per-sample normalisation
    if normalize:
        mean = feat.mean()
        std = feat.std() + 1e-8
        feat = (feat - mean) / std

    feat = feat.astype(np.float32)

    yield FeatureArray(
        data=feat,
        label=s.label,
        sample_rate=s.sample_rate,
        source_path=s.path,
        metadata={**s.metadata},
    )
```

**Output shape invariant:** `feat.shape == (fixed_length, n_mfcc_or_n_mels)`

---

## 2. `DatasetBuilderNode` — `dataset_builder.py`

**node_type:** `"dataset_builder"`  
**Category:** `"ML"`  
**Pattern:** SISO (`list[FeatureArray]` → `dict`)

### Config

```python
class Config(NodeConfig):
    pass   # no config — derives everything from FeatureArray metadata
```

### process() logic

```
labels = sorted({f.label for f in features})
label_to_idx = {l: i for i, l in enumerate(labels)}

splits = {"train": [], "val": [], "test": []}
for f in sorted(features, key=lambda x: x.source_path):
    split = f.metadata.get("split")
    if split not in {"train", "val", "test"}:
        raise ValueError(f"Invalid split '{split}' for {f.source_path}")
    splits[split].append(f)

def to_arrays(flist):
    X = np.stack([f.data for f in flist])          # [N, T, F]
    X = X[..., np.newaxis]                          # [N, T, F, 1]
    y = np.array([label_to_idx[f.label] for f in flist])
    return X.astype(np.float32), y.astype(np.int32)

X_train, y_train = to_arrays(splits["train"])
X_val,   y_val   = to_arrays(splits["val"])
X_test,  y_test  = to_arrays(splits["test"])

return {
    "X_train": X_train, "y_train": y_train,
    "X_val":   X_val,   "y_val":   y_val,
    "X_test":  X_test,  "y_test":  y_test,
    "labels":  labels,
    "input_shape": X_train.shape[1:],   # (T, F, 1) — used by ModelBuilderNode
    "n_classes": len(labels),
}
```

**Invariants:**
- `len(X_train) + len(X_val) + len(X_test) == len(features)`
- `X_train.shape == (N_train, fixed_length, n_bins, 1)`
- Sorted by `source_path` within each split → deterministic ordering

---

## 3. `ModelBuilderNode` — `model_builder.py`

**node_type:** `"model_builder"`  
**Category:** `"ML"`  
**Pattern:** Multi-port (`dataset` → `model`)

### Ports

```python
input_ports = {
    "dataset": InputPort(name="dataset", data_type=dict, description="Dataset dict from DatasetBuilderNode")
}
output_ports = {
    "model": OutputPort(name="model", data_type=object, description="Compiled keras.Model")
}
```

### Config

```python
class Config(NodeConfig):
    architecture: str = "ds_cnn"   # "ds_cnn" | "mobilenet"
    filters: int = 64
    num_layers: int = 4            # DS-CNN depth
    alpha: float = 1.0             # MobileNet width multiplier
    dropout_rate: float = 0.25
    learning_rate: float = 0.001
```

### DS-CNN architecture

```
Input(shape=(T, F, 1))
Conv2D(filters, (3,3), padding="same") → BN → ReLU
for _ in range(num_layers):
    DepthwiseConv2D((3,3), padding="same") → BN → ReLU
    Conv2D(filters, (1,1), padding="same") → BN → ReLU
GlobalAveragePooling2D()
Dropout(dropout_rate)
Dense(n_classes, activation="softmax")
```

### MobileNet-style architecture

```
Input(shape=(T, F, 1))
Conv2D(int(32*alpha), (3,3), strides=(2,2), padding="same") → BN → ReLU6
# Inverted residual blocks (3 blocks)
for expansion, filters, stride in [(6,16,1),(6,24,2),(6,32,2)]:
    _inverted_residual_block(x, int(filters*alpha), expansion, stride)
GlobalAveragePooling2D()
Dropout(dropout_rate)
Dense(n_classes, activation="softmax")
```

### process() logic

```python
def process(self, inputs):
    import keras
    dataset = inputs["dataset"]
    keras.utils.set_random_seed(self.seed)

    input_shape = dataset["input_shape"]   # (T, F, 1)
    n_classes   = dataset["n_classes"]

    if self.config.architecture == "ds_cnn":
        model = _build_ds_cnn(input_shape, n_classes, self.config)
    else:
        model = _build_mobilenet(input_shape, n_classes, self.config)

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=self.config.learning_rate),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    model.summary()
    return {"model": model}
```

---

## 4. `ModelTrainerNode` — `model_trainer.py`

**node_type:** `"model_trainer"`  
**Category:** `"ML"`  
**Pattern:** Multi-port (`model` + `dataset` → `output`)

### Ports

```python
input_ports = {
    "model":   InputPort(name="model",   data_type=object, description="Compiled keras.Model"),
    "dataset": InputPort(name="dataset", data_type=dict,   description="Dataset dict"),
}
output_ports = {
    "output": OutputPort(name="output", data_type=ModelArtifact)
}
```

### Config

```python
class Config(NodeConfig):
    epochs: int = 30
    batch_size: int = 32
    output_path: str = "examples/06_speech_commands_e2e/output"
    checkpoint_path: str = ""      # defaults to output_path/checkpoints/best.keras
    min_val_accuracy: float = 0.0  # warn if below this
    patience: int = 5              # EarlyStopping patience
```

### setup() / teardown()

```python
def setup(self):
    try:
        import tensorflow as tf  # noqa: F401
    except ImportError:
        raise ImportError("TensorFlow not found. Run: venv/bin/pip install tensorflow")
```

### process() logic

```python
def process(self, inputs):
    import keras
    keras.utils.set_random_seed(self.seed)

    model   = inputs["model"]
    dataset = inputs["dataset"]

    out_path = Path(self.config.output_path)
    out_path.mkdir(parents=True, exist_ok=True)

    ckpt_path = self.config.checkpoint_path or str(out_path / "checkpoints" / "best.keras")
    Path(ckpt_path).parent.mkdir(parents=True, exist_ok=True)

    callbacks = [
        keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=self.config.patience,
            restore_best_weights=True
        ),
        keras.callbacks.ModelCheckpoint(
            ckpt_path, monitor="val_accuracy",
            save_best_only=True, verbose=1
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=3, verbose=1
        ),
    ]

    history = model.fit(
        dataset["X_train"], dataset["y_train"],
        validation_data=(dataset["X_val"], dataset["y_val"]),
        epochs=self.config.epochs,
        batch_size=self.config.batch_size,
        callbacks=callbacks,
        verbose=1,
    )

    saved_model_path = str(out_path / "saved_model")
    model.save(saved_model_path)

    best_val_acc = max(history.history.get("val_accuracy", [0.0]))
    if best_val_acc < self.config.min_val_accuracy:
        print(f"  WARNING: val_accuracy {best_val_acc:.4f} < min_val_accuracy {self.config.min_val_accuracy}")

    return {"output": ModelArtifact(
        model_path=saved_model_path,
        labels=dataset["labels"],
        history=history.history,
        metrics={},
    )}
```

---

## 5. `ModelEvaluatorNode` — `model_evaluator.py`

**node_type:** `"model_evaluator"`  
**Category:** `"ML"`  
**Pattern:** Multi-port (`model_artifact` + `dataset` → `output`)

### Ports

```python
input_ports = {
    "model_artifact": InputPort(name="model_artifact", data_type=ModelArtifact),
    "dataset":        InputPort(name="dataset",        data_type=dict),
}
output_ports = {
    "output": OutputPort(name="output", data_type=ModelArtifact)
}
```

### Config

```python
class Config(NodeConfig):
    output_path: str = "examples/06_speech_commands_e2e/output"
    plot_confusion_matrix: bool = True
    plot_training_curves: bool = True
```

### setup() / teardown()

```python
def setup(self):
    # model loaded lazily in process() since model_path not known at setup time
    pass

def teardown(self):
    if hasattr(self, "_model"):
        del self._model
```

### process() logic

```python
def process(self, inputs):
    import keras
    import json
    from sklearn.metrics import precision_recall_fscore_support, confusion_matrix

    artifact = inputs["model_artifact"]
    dataset  = inputs["dataset"]

    model = keras.saving.load_model(artifact.model_path)

    X_test, y_test = dataset["X_test"], dataset["y_test"]
    labels = artifact.labels

    y_pred_probs = model.predict(X_test, verbose=0)
    y_pred = np.argmax(y_pred_probs, axis=1)

    test_acc = float(np.mean(y_pred == y_test))
    prec, rec, f1, _ = precision_recall_fscore_support(y_test, y_pred, average=None)
    cm = confusion_matrix(y_test, y_pred).tolist()

    metrics = {
        "test_accuracy": test_acc,
        "per_class": {
            labels[i]: {"precision": float(prec[i]), "recall": float(rec[i]), "f1": float(f1[i])}
            for i in range(len(labels))
        },
        "confusion_matrix": cm,
    }

    out_path = Path(self.config.output_path)
    out_path.mkdir(parents=True, exist_ok=True)

    with open(out_path / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    if self.config.plot_confusion_matrix:
        _plot_confusion_matrix(cm, labels, out_path / "confusion_matrix.png")

    if self.config.plot_training_curves:
        _plot_training_curves(artifact.history, out_path / "training_curves.png")

    return {"output": ModelArtifact(
        model_path=artifact.model_path,
        labels=labels,
        history=artifact.history,
        metrics=metrics,
    )}
```

---

## 6. `TFLiteExporterNode` — `tflite_exporter.py`

**node_type:** `"tflite_exporter"`  
**Category:** `"Export"`  
**Pattern:** SISO (`ModelArtifact` → `TFLiteArtifact`)

### Config

```python
class Config(NodeConfig):
    quantisation: str = "int8"     # "float32" | "float16" | "int8"
    output_path: str = "examples/06_speech_commands_e2e/output/tflite"
    representative_samples: int = 100  # batches for INT8 calibration
```

### Validation

`quantisation` validated in `__init__` — raises `ValueError` if not one of the three values.

### process() logic

```python
def process(self, artifact):
    import tensorflow as tf

    out_path = Path(self.config.output_path)
    out_path.mkdir(parents=True, exist_ok=True)

    converter = tf.lite.TFLiteConverter.from_saved_model(artifact.model_path)

    if self.config.quantisation == "float16":
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        converter.target_spec.supported_types = [tf.float16]

    elif self.config.quantisation == "int8":
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        # representative_dataset loaded from X_train saved alongside model
        converter.representative_dataset = _make_representative_dataset(
            artifact, self.config.representative_samples
        )
        converter.inference_input_type  = tf.uint8
        converter.inference_output_type = tf.uint8

    tflite_model = converter.convert()

    tflite_path = str(out_path / "model.tflite")
    with open(tflite_path, "wb") as f:
        f.write(tflite_model)

    labels_path = out_path / "labels.txt"
    with open(labels_path, "w") as f:
        f.write("\n".join(artifact.labels))

    return TFLiteArtifact(
        tflite_path=tflite_path,
        labels=artifact.labels,
        quantisation=self.config.quantisation,
        file_size_bytes=len(tflite_model),
    )
```

**Note on INT8 representative dataset:** `ModelTrainerNode` saves `X_train` as a
numpy `.npy` file alongside the SavedModel (`output/saved_model/X_train_repr.npy`).
`TFLiteExporterNode` loads this file to build the representative dataset generator.

---

## 7. `InferenceNode` — `inference_node.py`

**node_type:** `"inference"`  
**Category:** `"Inference"`  
**Pattern:** SISO (`list[FeatureArray]` → `list[PredictionResult]`)

### Config

```python
class Config(NodeConfig):
    model_path: str   # required — path to .tflite file
```

### setup() / teardown()

```python
def setup(self):
    import tensorflow as tf
    if not Path(self.config.model_path).exists():
        raise FileNotFoundError(f"TFLite model not found: {self.config.model_path}")

    labels_path = Path(self.config.model_path).parent / "labels.txt"
    with open(labels_path) as f:
        self._labels = [l.strip() for l in f.readlines()]

    self._interpreter = tf.lite.Interpreter(model_path=self.config.model_path)
    self._interpreter.allocate_tensors()
    self._input_details  = self._interpreter.get_input_details()
    self._output_details = self._interpreter.get_output_details()

def teardown(self):
    if hasattr(self, "_interpreter"):
        del self._interpreter
```

### process() logic

```python
def process(self, features):
    results = []
    for f in features:
        # Reshape to [1, T, F, 1] matching interpreter input
        inp = f.data[np.newaxis, ..., np.newaxis].astype(np.float32)
        # Handle INT8 quantisation
        input_detail = self._input_details[0]
        if input_detail["dtype"] == np.uint8:
            scale, zero_point = input_detail["quantization"]
            inp = (inp / scale + zero_point).astype(np.uint8)

        self._interpreter.set_tensor(input_detail["index"], inp)
        self._interpreter.invoke()

        output = self._interpreter.get_tensor(self._output_details[0]["index"])
        # Dequantise if INT8
        if self._output_details[0]["dtype"] == np.uint8:
            scale, zero_point = self._output_details[0]["quantization"]
            output = (output.astype(np.float32) - zero_point) * scale

        probs = output[0].tolist()
        predicted_idx = int(np.argmax(probs))

        results.append(PredictionResult(
            source_path=f.source_path,
            predicted_label=self._labels[predicted_idx],
            probabilities={self._labels[i]: float(probs[i]) for i in range(len(self._labels))},
            metadata=f.metadata,
        ))
    return results
```

---

## 8. `FeatureVisualizerNode` — `feature_visualizer.py`

**node_type:** `"feature_visualizer"`  
**Category:** `"Visualization"`  
**Pattern:** SISO pass-through (`list[FeatureArray]` → `list[FeatureArray]`)

### Config

```python
class Config(NodeConfig):
    output_path: str = "examples/06_speech_commands_e2e/output/features"
    max_samples: int = 5
    feature_type: str = "mfcc"   # "mfcc" | "log_mel" — controls axis labels
```

### process() logic

Saves up to `max_samples` PNG files using `librosa.display.specshow`, then returns
the input list unchanged. Files named `{label}_{i:03d}.png`.

---

## 9. `ConfusionMatrixNode` — `confusion_matrix_node.py`

**node_type:** `"confusion_matrix_plot"`  
**Category:** `"Visualization"`  
**Pattern:** SISO pass-through (`ModelArtifact` → `ModelArtifact`)

### Config

```python
class Config(NodeConfig):
    output_path: str = "examples/06_speech_commands_e2e/output"
    normalize: bool = False   # normalise rows to show recall per class
    figsize: list[int] = [8, 6]
```

### process() logic

Reads `artifact.metrics["confusion_matrix"]`, renders a seaborn heatmap with
`annot=True`, saves to `output_path/confusion_matrix.png`, returns artifact unchanged.

When `normalize=True`, divides each row by its sum before rendering.

---

## 10. `TrainingCurvesNode` — `training_curves_node.py`

**node_type:** `"training_curves_plot"`  
**Category:** `"Visualization"`  
**Pattern:** SISO pass-through (`ModelArtifact` → `ModelArtifact`)

### Config

```python
class Config(NodeConfig):
    output_path: str = "examples/06_speech_commands_e2e/output"
    figsize: list[int] = [12, 4]
```

### process() logic

Reads `artifact.history`, creates a 2-subplot figure:
- Left: `loss` and `val_loss` over epochs
- Right: `accuracy` and `val_accuracy` over epochs

Saves to `output_path/training_curves.png`, returns artifact unchanged.

---

## Node Summary Table

| node_type | File | Pattern | Input type | Output type |
|---|---|---|---|---|
| `feature_extractor` | `feature_extractor.py` | SISO | `list[AudioSample]` | `list[FeatureArray]` |
| `dataset_builder` | `dataset_builder.py` | SISO | `list[FeatureArray]` | `dict` |
| `model_builder` | `model_builder.py` | Multi-port | `dict` (dataset) | `keras.Model` |
| `model_trainer` | `model_trainer.py` | Multi-port | `keras.Model` + `dict` | `ModelArtifact` |
| `model_evaluator` | `model_evaluator.py` | Multi-port | `ModelArtifact` + `dict` | `ModelArtifact` |
| `tflite_exporter` | `tflite_exporter.py` | SISO | `ModelArtifact` | `TFLiteArtifact` |
| `inference` | `inference_node.py` | SISO | `list[FeatureArray]` | `list[PredictionResult]` |
| `feature_visualizer` | `feature_visualizer.py` | SISO pass-through | `list[FeatureArray]` | `list[FeatureArray]` |
| `confusion_matrix_plot` | `confusion_matrix_node.py` | SISO pass-through | `ModelArtifact` | `ModelArtifact` |
| `training_curves_plot` | `training_curves_node.py` | SISO pass-through | `ModelArtifact` | `ModelArtifact` |
