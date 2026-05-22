# Design: New PortDataTypes

All four types live in `examples/06_speech_commands_e2e/plugins/data_types.py`.
They are `PortDataType` subclasses so `AutoDiscovery` registers them in `TypeCatalogue`
automatically when the plugins directory is scanned.

---

## `FeatureArray`

Carries a computed acoustic feature (MFCC or log-mel spectrogram) for one audio clip.

```python
from __future__ import annotations
from typing import Any
import numpy as np
from pydantic import field_validator
from app.core.nodes.ports import PortDataType

class FeatureArray(PortDataType):
    """Acoustic feature array for one audio clip."""
    data: Any                    # np.ndarray float32, shape [T, F] or [T, F, 1]
    label: str = ""
    sample_rate: int = 16000
    source_path: str = ""
    metadata: dict[str, Any] = {}

    @field_validator("data", mode="before")
    @classmethod
    def _coerce_float32(cls, v):
        if v is None:
            return np.zeros((0, 0), dtype=np.float32)
        arr = np.asarray(v, dtype=np.float32)
        return arr
```

**Field contracts:**
- `data.dtype` is always `numpy.float32` (enforced by validator)
- `data.shape` is `[fixed_length, n_bins]` after `FeatureExtractorNode`
- `metadata["split"]` is set by the upstream `split` node: `"train"`, `"val"`, or `"test"`
- `metadata["augmented"]`, `metadata["pitch_shift_semitones"]`, etc. propagated from `AudioSample`

---

## `ModelArtifact`

Carries the filesystem path to a trained Keras SavedModel plus training metadata.

```python
class ModelArtifact(PortDataType):
    """Trained Keras model artifact."""
    model_path: str              # path to SavedModel directory
    labels: list[str] = []       # sorted label list, e.g. ["down","go","no","stop","up","yes"]
    history: dict[str, Any] = {} # Keras history.history dict: {"loss": [...], "val_loss": [...], ...}
    metrics: dict[str, Any] = {} # populated by ModelEvaluatorNode
```

**Field contracts:**
- `model_path` points to a directory loadable by `keras.saving.load_model(model_path)`
- `labels` is sorted alphabetically (matches integer encoding in `DatasetBuilderNode`)
- `history` keys: `"loss"`, `"val_loss"`, `"accuracy"`, `"val_accuracy"` (list per epoch)
- `metrics` keys after evaluation: `"test_accuracy"`, `"per_class"` (dict), `"confusion_matrix"` (nested list)

---

## `TFLiteArtifact`

Carries the filesystem path to a TFLite flatbuffer and its metadata.

```python
class TFLiteArtifact(PortDataType):
    """TFLite model artifact."""
    tflite_path: str             # path to .tflite file
    labels: list[str] = []       # sorted label list (mirrors ModelArtifact.labels)
    quantisation: str = "float32"  # "float32" | "float16" | "int8"
    file_size_bytes: int = 0     # flatbuffer size in bytes
```

**Field contracts:**
- `tflite_path` is loadable by `tf.lite.Interpreter(model_path=tflite_path)`
- A sibling `labels.txt` file always exists at `Path(tflite_path).parent / "labels.txt"`
- `quantisation` is one of the three allowed values (validated at construction)

---

## `PredictionResult`

Carries the inference output for one audio clip.

```python
class PredictionResult(PortDataType):
    """Inference result for one audio clip."""
    source_path: str = ""
    predicted_label: str = ""
    probabilities: dict[str, float] = {}  # label → probability, sums to ~1.0
    metadata: dict[str, Any] = {}
```

**Field contracts:**
- `sum(probabilities.values())` ≈ 1.0 (within 1e-5)
- `predicted_label == max(probabilities, key=probabilities.get)`
- `probabilities` contains exactly one key per label in the model's label list

---

## TypeCatalogue Registration

`AutoDiscovery` registers all four types when it imports `data_types.py`. The
fully-qualified names will be:

```
examples.06_speech_commands_e2e.plugins.data_types.FeatureArray
examples.06_speech_commands_e2e.plugins.data_types.ModelArtifact
examples.06_speech_commands_e2e.plugins.data_types.TFLiteArtifact
examples.06_speech_commands_e2e.plugins.data_types.PredictionResult
```

Because `AutoDiscovery` uses `spec_from_file_location` for plugin files, the
module name will be the stem of the file (`data_types`), so the FQN will be
`data_types.FeatureArray` etc. in the catalogue.
