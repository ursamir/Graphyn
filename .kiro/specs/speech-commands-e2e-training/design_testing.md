# Design: Testing Strategy and Correctness Properties

---

## Overview

Tests live in `examples/06_speech_commands_e2e/tests/`. They use `pytest` and
`hypothesis` for property-based testing (PBT). No TensorFlow is required for the
unit and property tests — only `FeatureExtractorNode` and `DatasetBuilderNode` are
tested with PBT since they are pure, deterministic transformations.

Run with:
```bash
venv/bin/pytest examples/06_speech_commands_e2e/tests/ -v
```

---

## Test Files

| File | Scope |
|---|---|
| `tests/test_data_types.py` | PortDataType field contracts |
| `tests/test_feature_extractor.py` | PBT correctness properties for FeatureExtractorNode |
| `tests/test_dataset_builder.py` | PBT correctness properties for DatasetBuilderNode |
| `tests/test_plugin_discovery.py` | AutoDiscovery registers all 10 node types |
| `tests/test_inference_node.py` | InferenceNode unit tests (mocked TFLite) |
| `tests/conftest.py` | Shared fixtures (synthetic AudioSample generators) |

---

## Hypothesis Strategies

### `audio_sample_strategy`

Generates synthetic `AudioSample` objects with:
- `data`: float32 array, length 1600–32000 (0.1s–2s at 16kHz)
- `sample_rate`: always 16000
- `label`: one of `["yes", "no", "up", "down", "go", "stop"]`
- `metadata`: dict with `"split"` key set to one of `"train"`, `"val"`, `"test"`

```python
from hypothesis import given, settings
from hypothesis import strategies as st
import numpy as np

@st.composite
def audio_sample_strategy(draw):
    n = draw(st.integers(min_value=1600, max_value=32000))
    data = draw(st.builds(
        lambda n: np.random.default_rng(42).standard_normal(n).astype(np.float32),
        n=st.just(n)
    ))
    label = draw(st.sampled_from(["yes", "no", "up", "down", "go", "stop"]))
    split = draw(st.sampled_from(["train", "val", "test"]))
    return AudioSample(
        path=f"synthetic/{label}/{draw(st.integers(0, 9999))}.wav",
        sample_rate=16000,
        data=data,
        label=label,
        metadata={"split": split},
    )
```

---

## Correctness Properties

### P1: FeatureExtractor — Fixed Output Shape

**Property:** For any valid `AudioSample` with non-empty waveform, the output
`FeatureArray.data.shape` is always `(fixed_length, n_bins)`.

```python
@given(st.lists(audio_sample_strategy(), min_size=1, max_size=10))
def test_feature_extractor_fixed_shape(samples):
    node = FeatureExtractorNode(config={"feature_type": "mfcc", "n_mfcc": 40,
                                         "fixed_length": 101, "normalize": True})
    node.setup()
    results = node.process(samples)
    for r in results:
        assert r.data.shape == (101, 40)
```

### P2: FeatureExtractor — Float32 dtype

**Property:** All output `FeatureArray.data` arrays have dtype `float32`.

```python
@given(st.lists(audio_sample_strategy(), min_size=1, max_size=10))
def test_feature_extractor_dtype(samples):
    node = FeatureExtractorNode(config={"feature_type": "log_mel", "n_mels": 40,
                                         "fixed_length": 101})
    node.setup()
    results = node.process(samples)
    for r in results:
        assert r.data.dtype == np.float32
```

### P3: FeatureExtractor — Determinism

**Property:** Running the same node on the same input twice produces identical output.

```python
@given(st.lists(audio_sample_strategy(), min_size=1, max_size=5))
def test_feature_extractor_deterministic(samples):
    node = FeatureExtractorNode(config={"feature_type": "mfcc", "n_mfcc": 40,
                                         "fixed_length": 101, "normalize": True})
    node.setup()
    r1 = node.process(samples)
    r2 = node.process(samples)
    for a, b in zip(r1, r2):
        np.testing.assert_array_equal(a.data, b.data)
```

### P4: FeatureExtractor — Label Propagation

**Property:** Output `FeatureArray.label` always equals the source `AudioSample.label`.

```python
@given(st.lists(audio_sample_strategy(), min_size=1, max_size=10))
def test_feature_extractor_label_propagation(samples):
    node = FeatureExtractorNode(config={"feature_type": "mfcc", "n_mfcc": 40,
                                         "fixed_length": 101})
    node.setup()
    results = node.process(samples)
    for s, r in zip(samples, results):
        assert r.label == s.label
```

### P5: FeatureExtractor — Count Preservation

**Property:** Output list length equals input list length (one feature per sample).

```python
@given(st.lists(audio_sample_strategy(), min_size=0, max_size=20))
def test_feature_extractor_count(samples):
    node = FeatureExtractorNode(config={"feature_type": "mfcc", "n_mfcc": 40,
                                         "fixed_length": 101})
    node.setup()
    results = node.process(samples)
    assert len(results) == len(samples)
```

### P6: DatasetBuilder — No Sample Loss

**Property:** Total samples across all splits equals input count.

```python
@given(st.lists(feature_array_strategy(), min_size=3, max_size=50))
def test_dataset_builder_no_loss(features):
    node = DatasetBuilderNode(config={})
    node.setup()
    dataset = node.process(features)
    total = len(dataset["X_train"]) + len(dataset["X_val"]) + len(dataset["X_test"])
    assert total == len(features)
```

### P7: DatasetBuilder — Shape Consistency

**Property:** X arrays have shape `[N, fixed_length, n_bins, 1]` and y arrays have
shape `[N]` with matching N.

```python
@given(st.lists(feature_array_strategy(), min_size=3, max_size=30))
def test_dataset_builder_shapes(features):
    node = DatasetBuilderNode(config={})
    node.setup()
    dataset = node.process(features)
    for split in ["train", "val", "test"]:
        X, y = dataset[f"X_{split}"], dataset[f"y_{split}"]
        assert X.ndim == 4
        assert X.shape[-1] == 1
        assert len(X) == len(y)
```

### P8: DatasetBuilder — Label Encoding Consistency

**Property:** All integer labels in y arrays are valid indices into `dataset["labels"]`.

```python
@given(st.lists(feature_array_strategy(), min_size=3, max_size=30))
def test_dataset_builder_label_encoding(features):
    node = DatasetBuilderNode(config={})
    node.setup()
    dataset = node.process(features)
    n_classes = len(dataset["labels"])
    for split in ["train", "val", "test"]:
        y = dataset[f"y_{split}"]
        assert np.all(y >= 0) and np.all(y < n_classes)
```

### P9: DatasetBuilder — Deterministic Ordering

**Property:** Running twice on the same input produces identical X_train arrays.

```python
@given(st.lists(feature_array_strategy(), min_size=3, max_size=20))
def test_dataset_builder_deterministic(features):
    node = DatasetBuilderNode(config={})
    node.setup()
    d1 = node.process(features)
    d2 = node.process(features)
    np.testing.assert_array_equal(d1["X_train"], d2["X_train"])
    np.testing.assert_array_equal(d1["y_train"], d2["y_train"])
```

### P10: FeatureArray — dtype invariant

**Property:** `FeatureArray.data.dtype` is always `float32` regardless of how it
was constructed.

```python
@given(st.integers(min_value=1, max_value=200),
       st.integers(min_value=1, max_value=80))
def test_feature_array_dtype(t, f):
    data = np.ones((t, f), dtype=np.float64)  # intentionally wrong dtype
    fa = FeatureArray(data=data, label="yes", sample_rate=16000, source_path="x.wav")
    assert fa.data.dtype == np.float32
```

---

## Plugin Discovery Test

```python
# tests/test_plugin_discovery.py
import os
from pathlib import Path

def test_all_nodes_registered():
    os.environ["GRAPHYN_PLUGINS_DIR"] = str(
        Path(__file__).parent.parent / "plugins"
    )
    from app.core.registry_runtime import get_registry
    registry = get_registry()

    expected = [
        "feature_extractor", "dataset_builder", "model_builder",
        "model_trainer", "model_evaluator", "tflite_exporter",
        "inference", "feature_visualizer",
        "confusion_matrix_plot", "training_curves_plot",
        "command_validator",  # from Example 02 plugins
    ]
    for node_type in expected:
        assert node_type in registry, f"Node '{node_type}' not registered"
```

---

## Hypothesis Settings

```python
# conftest.py
from hypothesis import settings, HealthCheck

settings.register_profile("ci", max_examples=50,
                           suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("dev", max_examples=20)
settings.load_profile("dev")
```
