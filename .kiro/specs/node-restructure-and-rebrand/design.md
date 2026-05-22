# Design Document — Node Restructure and Rebrand

## Overview

This document describes the technical design for restructuring `app/core/nodes/` into category subfolders, absorbing example/plugin nodes as built-in nodes, introducing new model types, and rebranding the system as a general-purpose pipeline engine.

The design is driven by three goals:
1. **Physical organisation** — separate framework infrastructure from node implementations; group implementations by domain.
2. **Node absorption** — promote 16 nodes from `examples/*/plugins/` and `plugins/` into first-class built-in nodes with proper absolute imports.
3. **Rebranding** — update all documentation and steering files to present the system as domain-agnostic.

---

## Architecture

### Final Directory Layout

```
app/
├── core/
│   └── nodes/
│       ├── __init__.py          ← singleton registry + AutoDiscovery (updated)
│       ├── base.py              ← Node base class (unchanged)
│       ├── catalogue.py         ← TypeCatalogue (unchanged)
│       ├── compat.py            ← CompatibilityChecker (unchanged)
│       ├── config.py            ← NodeConfig (unchanged)
│       ├── discovery.py         ← AutoDiscovery (updated: recursive scan)
│       ├── errors.py            ← exception hierarchy (unchanged)
│       ├── metadata.py          ← NodeMetadata (unchanged)
│       ├── observers.py         ← NodeObserver (unchanged)
│       ├── ports.py             ← InputPort, OutputPort, PortDataType (unchanged)
│       ├── registry.py          ← NodeRegistry (unchanged)
│       ├── retry.py             ← RetryPolicy (unchanged)
│       │
│       ├── audio/               ← NEW category folder
│       │   ├── __init__.py
│       │   ├── augment.py       ← moved from nodes/augment.py
│       │   ├── background_noise_generator.py  ← absorbed from examples/01
│       │   ├── clean.py         ← moved
│       │   ├── command_validator.py           ← absorbed from examples/02
│       │   ├── compose.py       ← moved
│       │   ├── compress.py      ← moved
│       │   ├── degradation_pipeline.py        ← absorbed from examples/05
│       │   ├── duration_filter.py             ← absorbed from examples/03
│       │   ├── export.py        ← moved
│       │   ├── file_export.py   ← moved
│       │   ├── file_input.py    ← moved
│       │   ├── hf_export.py     ← moved
│       │   ├── input.py         ← moved
│       │   ├── mic_input.py     ← moved
│       │   ├── noise.py         ← absorbed from plugins/noise_node.py
│       │   ├── noise_mix.py     ← moved
│       │   ├── process.py       ← moved
│       │   ├── segment.py       ← moved
│       │   ├── speaker_embedder.py            ← absorbed from examples/04
│       │   ├── spectrogram.py   ← moved
│       │   ├── split.py         ← moved
│       │   ├── stratified_split.py ← moved
│       │   └── tfrecord_export.py  ← moved
│       │
│       └── ml/                  ← NEW category folder
│           ├── __init__.py
│           ├── confusion_matrix_node.py  ← absorbed from examples/06
│           ├── dataset_builder.py        ← absorbed from examples/06
│           ├── feature_extractor.py      ← absorbed from examples/06
│           ├── feature_visualizer.py     ← absorbed from examples/06
│           ├── inference_node.py         ← absorbed from examples/06
│           ├── model_builder.py          ← absorbed from examples/06
│           ├── model_evaluator.py        ← absorbed from examples/06
│           ├── model_trainer.py          ← absorbed from examples/06
│           ├── tflite_exporter.py        ← absorbed from examples/06
│           └── training_curves_node.py   ← absorbed from examples/06
│
└── models/
    ├── __init__.py              ← updated: re-exports all 6 types
    ├── audio_sample.py          ← unchanged
    ├── data_sample.py           ← NEW: DataSample base type
    ├── feature_array.py         ← NEW: migrated from examples/06/data_types.py
    ├── model_artifact.py        ← NEW: migrated from examples/06/data_types.py
    ├── prediction_result.py     ← NEW: migrated from examples/06/data_types.py
    └── tflite_artifact.py       ← NEW: migrated from examples/06/data_types.py

app/core/nodes/
    ├── augment.py               ← SHIM: deprecation warning + re-export
    ├── clean.py                 ← SHIM
    ├── compose.py               ← SHIM
    ├── compress.py              ← SHIM
    ├── export.py                ← SHIM
    ├── file_export.py           ← SHIM
    ├── file_input.py            ← SHIM
    ├── hf_export.py             ← SHIM
    ├── input.py                 ← SHIM
    ├── mic_input.py             ← SHIM
    ├── noise_mix.py             ← SHIM
    ├── process.py               ← SHIM
    ├── segment.py               ← SHIM
    ├── spectrogram.py           ← SHIM
    ├── split.py                 ← SHIM
    ├── stratified_split.py      ← SHIM
    └── tfrecord_export.py       ← SHIM
```

---

## Component Design

### 1. AutoDiscovery — Recursive Category Scanning

**File:** `app/core/nodes/discovery.py`

The existing `AutoDiscovery._scan_directory()` scans a single flat directory. It must be extended to also scan one level of subdirectories (Category_Folders).

**Design decision:** scan exactly one level deep (not arbitrarily recursive). This keeps the behaviour predictable and avoids accidentally scanning nested test fixtures or data directories. Category_Folders are identified as subdirectories that contain an `__init__.py` (i.e. they are Python packages).

**Updated `run()` method logic:**

```python
def run(self, nodes_dir, plugins_dir=None):
    nodes_path = Path(nodes_dir)
    # 1. Scan framework root (existing behaviour — skips framework files)
    self._scan_directory(nodes_path, package_prefix="app.core.nodes")

    # 2. Scan each Category_Folder (subdirectory with __init__.py)
    for subdir in sorted(nodes_path.iterdir()):
        if subdir.is_dir() and (subdir / "__init__.py").exists():
            category_prefix = f"app.core.nodes.{subdir.name}"
            self._scan_directory(subdir, package_prefix=category_prefix)

    # 3. Scan plugins_dir (existing flat behaviour, unchanged)
    ...
```

The `_scan_directory()` method itself is unchanged — it already handles the `package_prefix` parameter correctly for subdirectory imports.

**`_EXCLUDED_FILES` set:** unchanged. Framework files are only in the root, not in Category_Folders, so the exclusion list does not need updating.

**`__init__.py` in Category_Folders:** `_scan_directory` already skips `__init__.py` (it is in `_EXCLUDED_FILES`), so no change needed there.

---

### 2. Backward-Compatibility Shim Pattern

**Files:** `app/core/nodes/clean.py`, `augment.py`, etc. (all moved node files)

Each shim follows this exact pattern:

```python
# app/core/nodes/clean.py
"""Deprecated shim — use app.core.nodes.audio.clean instead."""
import warnings
warnings.warn(
    "Importing from 'app.core.nodes.clean' is deprecated. "
    "Use 'app.core.nodes.audio.clean' instead.",
    DeprecationWarning,
    stacklevel=2,
)
from app.core.nodes.audio.clean import (  # noqa: F401, E402
    CleanNode,
    TrimNode,
    ResampleNode,
    NormalizeNode,
    GainNode,
    FormatConvertNode,
)
```

**Key properties of this design:**
- The warning fires at import time, not at class instantiation, so it is visible in test output and CI logs.
- `stacklevel=2` points the warning at the caller's import statement, not at the shim file itself.
- The shim is a plain `.py` file at the old path — no `sys.modules` manipulation needed.
- AutoDiscovery skips shim files because they do not define any `Node` subclasses in their own module (the classes' `__module__` attribute points to the canonical `app.core.nodes.audio.*` module, not the shim). The `_process_module` check `obj.__module__ == module.__name__` ensures this.

**Shim files to create** (one per moved implementation file):

| Shim path | Re-exports from |
|---|---|
| `app/core/nodes/augment.py` | `app.core.nodes.audio.augment` |
| `app/core/nodes/clean.py` | `app.core.nodes.audio.clean` |
| `app/core/nodes/compose.py` | `app.core.nodes.audio.compose` |
| `app/core/nodes/compress.py` | `app.core.nodes.audio.compress` |
| `app/core/nodes/export.py` | `app.core.nodes.audio.export` |
| `app/core/nodes/file_export.py` | `app.core.nodes.audio.file_export` |
| `app/core/nodes/file_input.py` | `app.core.nodes.audio.file_input` |
| `app/core/nodes/hf_export.py` | `app.core.nodes.audio.hf_export` |
| `app/core/nodes/input.py` | `app.core.nodes.audio.input` |
| `app/core/nodes/mic_input.py` | `app.core.nodes.audio.mic_input` |
| `app/core/nodes/noise_mix.py` | `app.core.nodes.audio.noise_mix` |
| `app/core/nodes/process.py` | `app.core.nodes.audio.process` |
| `app/core/nodes/segment.py` | `app.core.nodes.audio.segment` |
| `app/core/nodes/spectrogram.py` | `app.core.nodes.audio.spectrogram` |
| `app/core/nodes/split.py` | `app.core.nodes.audio.split` |
| `app/core/nodes/stratified_split.py` | `app.core.nodes.audio.stratified_split` |
| `app/core/nodes/tfrecord_export.py` | `app.core.nodes.audio.tfrecord_export` |

**Note:** `test_process.py` is a test file, not a node implementation. It stays in `app/core/nodes/` and is not shimmed.

---

### 3. `app/models/` — New Model Files

#### 3a. `DataSample` (new)

```python
# app/models/data_sample.py
from __future__ import annotations
from typing import Any
from app.core.nodes.ports import PortDataType

class DataSample(PortDataType):
    """Domain-agnostic base type for pipeline data.

    Subclass this for new domains: TextSample, ImageSample, etc.
    AutoDiscovery registers every subclass in TypeCatalogue automatically.
    """
    id: str = ""
    source: str = ""
    metadata: dict[str, Any] = {}
```

`DataSample` does NOT extend `AudioSample` and `AudioSample` does NOT extend `DataSample`. They are independent `PortDataType` subclasses. This preserves full backward compatibility for `AudioSample` users.

#### 3b. ML Data Types (migrated from `examples/06/plugins/data_types.py`)

Four files, one class each. The migration makes two changes only:
1. Remove the `importlib.util.spec_from_file_location` loading pattern (no longer needed — these are proper package modules).
2. No `from __future__ import annotations` (Pydantic v2 requirement — already the case in the originals).

All field definitions, validators, and `model_config` are preserved verbatim.

**`app/models/feature_array.py`** — `FeatureArray(PortDataType)` with `data: np.ndarray`, `label`, `sample_rate`, `source_path`, `metadata`.

**`app/models/model_artifact.py`** — `ModelArtifact(PortDataType)` with `model_path`, `labels`, `history`, `metrics`.

**`app/models/tflite_artifact.py`** — `TFLiteArtifact(PortDataType)` with `tflite_path`, `labels`, `quantisation`, `file_size_bytes`.

**`app/models/prediction_result.py`** — `PredictionResult(PortDataType)` with `source_path`, `predicted_label`, `probabilities`, `metadata`.

#### 3c. `app/models/__init__.py` (updated)

```python
from app.models.audio_sample import AudioSample
from app.models.data_sample import DataSample
from app.models.feature_array import FeatureArray
from app.models.model_artifact import ModelArtifact
from app.models.tflite_artifact import TFLiteArtifact
from app.models.prediction_result import PredictionResult

__all__ = [
    "AudioSample",
    "DataSample",
    "FeatureArray",
    "ModelArtifact",
    "TFLiteArtifact",
    "PredictionResult",
]
```

---

### 4. Absorbed Node Import Rewriting

#### 4a. Audio nodes (examples/01–05 + plugins/noise_node.py)

These nodes already use correct absolute imports (`from app.core.nodes.base import Node`, `from app.models.audio_sample import AudioSample`). The only change needed is:
- Move the file to `app/core/nodes/audio/<name>.py`.
- Remove the `# examples/*/plugins/` header comment and replace with the canonical path.
- No import changes required for the five example audio nodes.
- `plugins/noise_node.py` → `app/core/nodes/audio/noise.py`: rename file (class name `NoiseNode` and `node_type="noise"` are unchanged).

#### 4b. ML nodes (examples/06 plugins)

These nodes use the `importlib.util.spec_from_file_location` lazy-loading pattern to import `FeatureArray`, `ModelArtifact`, etc. from the sibling `data_types.py`. This pattern must be replaced with direct absolute imports.

**Before (in each ML node):**
```python
_DATA_TYPES_PATH = Path(__file__).parent / "data_types.py"

def _load_data_types():
    spec = importlib.util.spec_from_file_location("data_types", str(_DATA_TYPES_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class SomeNode(Node):
    def setup(self):
        self._dt = _load_data_types()

    def process(self, ...):
        FeatureArray = self._dt.FeatureArray
        ...
```

**After (in each ML node):**
```python
from app.models.feature_array import FeatureArray
from app.models.model_artifact import ModelArtifact
from app.models.tflite_artifact import TFLiteArtifact
from app.models.prediction_result import PredictionResult

class SomeNode(Node):
    def setup(self):
        pass  # no lazy loading needed

    def process(self, ...):
        # Use FeatureArray, ModelArtifact, etc. directly
        ...
```

Only the imports that each node actually uses need to be added. For example, `FeatureExtractorNode` only needs `FeatureArray`; `ModelTrainerNode` only needs `ModelArtifact`.

**Nodes and their required model imports:**

| Node file | Imports needed |
|---|---|
| `feature_extractor.py` | `FeatureArray` |
| `dataset_builder.py` | `FeatureArray` (input type reference) |
| `model_builder.py` | none (uses `dict` and `object` ports) |
| `model_trainer.py` | `ModelArtifact` |
| `model_evaluator.py` | `ModelArtifact` |
| `tflite_exporter.py` | `ModelArtifact`, `TFLiteArtifact` |
| `inference_node.py` | `FeatureArray`, `PredictionResult` |
| `confusion_matrix_node.py` | `ModelArtifact` (pass-through) |
| `training_curves_node.py` | `ModelArtifact` (pass-through) |
| `feature_visualizer.py` | `FeatureArray` |

Also remove: `import importlib.util`, `from pathlib import Path` (if only used for `_DATA_TYPES_PATH`), `_DATA_TYPES_PATH`, `_load_data_types()`, and `self._dt = _load_data_types()` in `setup()`.

---

### 5. `app/core/nodes/__init__.py` — Updated AutoDiscovery Call

The `__init__.py` currently calls `AutoDiscovery(registry).run(nodes_dir=_nodes_dir, plugins_dir=_plugins_dir)`. With the updated `run()` method that recursively scans Category_Folders, no change to `__init__.py` is needed — the recursive scan is handled inside `AutoDiscovery.run()` itself.

However, `__init__.py` must also trigger discovery of `app/models/` so that `DataSample` and the four ML types are registered in `TypeCatalogue`. The cleanest approach is to have `AutoDiscovery` also scan `app/models/` for `PortDataType` subclasses.

**Design decision:** Add an optional `models_dir` parameter to `AutoDiscovery.run()`:

```python
def run(self, nodes_dir, plugins_dir=None, models_dir=None):
    # ... existing node scanning ...

    if models_dir is not None:
        models_path = Path(models_dir)
        if models_path.exists():
            self._scan_directory(models_path, package_prefix="app.models")
```

Updated `__init__.py`:

```python
_models_dir = Path(__file__).parent.parent.parent / "models"

AutoDiscovery(registry).run(
    nodes_dir=_nodes_dir,
    plugins_dir=_plugins_dir,
    models_dir=_models_dir,
)
```

`_scan_directory` already handles `PortDataType` subclass registration via `_process_module`. The `_EXCLUDED_FILES` set excludes `__init__.py`, so the models package init is skipped automatically.

---

### 6. Category `__init__.py` Files

Both `app/core/nodes/audio/__init__.py` and `app/core/nodes/ml/__init__.py` are empty (just a docstring). They exist solely to make the directories valid Python packages, enabling `importlib.import_module("app.core.nodes.audio.clean")` to work.

```python
# app/core/nodes/audio/__init__.py
"""Audio domain node implementations."""
```

```python
# app/core/nodes/ml/__init__.py
"""ML training, inference, and model-management node implementations."""
```

---

### 7. `test_process.py` — Handling the Existing Test File

`app/core/nodes/test_process.py` is a test file that lives in the nodes directory. It is not a node implementation and must not be moved to `audio/`. It stays at `app/core/nodes/test_process.py`. AutoDiscovery already skips it because it starts with `test_` — wait, it does not start with `_`. Let's check: `_EXCLUDED_PREFIXES = {"_"}` — `test_process.py` does not start with `_`.

However, `test_process.py` does not define any `Node` subclasses with `metadata: ClassVar[NodeMetadata]`, so AutoDiscovery will attempt to import it but `_process_module` will find nothing to register and move on silently. This is the existing behaviour and is unchanged.

The file stays in place. No action needed.

---

### 8. Example YAML Pipeline Configs

The example YAML configs in `examples/*/` reference nodes by `node_type` string (e.g. `node_type: background_noise_generator`). Since all absorbed nodes preserve their `node_type` strings exactly, these YAML configs continue to work without modification.

The example configs do NOT need to be updated as part of this change.

---

## Data Models

### `DataSample` Schema

```
DataSample(PortDataType)
├── id: str = ""          # unique identifier (caller-assigned)
├── source: str = ""      # origin path, URL, or identifier
└── metadata: dict[str, Any] = {}  # arbitrary annotations
```

Intentionally minimal and domain-agnostic. No `data` field — subclasses add domain-specific payload fields.

### ML Type Schemas (unchanged from originals)

```
FeatureArray(PortDataType)
├── data: np.ndarray        # float32, shape [T, F]
├── label: str = ""
├── sample_rate: int = 16000
├── source_path: str = ""
└── metadata: dict = {}

ModelArtifact(PortDataType)
├── model_path: str = ""
├── labels: list = []
├── history: dict = {}
└── metrics: dict = {}

TFLiteArtifact(PortDataType)
├── tflite_path: str = ""
├── labels: list = []
├── quantisation: str = "float32"   # validated: float32|float16|int8
└── file_size_bytes: int = 0

PredictionResult(PortDataType)
├── source_path: str = ""
├── predicted_label: str = ""
├── probabilities: dict = {}
└── metadata: dict = {}
```

---

## Implementation Plan

The implementation is broken into sequential phases to minimise risk. Each phase leaves the system in a working state.

### Phase 1: Create `app/models/` additions

1. Create `app/models/data_sample.py` — `DataSample`
2. Create `app/models/feature_array.py` — `FeatureArray`
3. Create `app/models/model_artifact.py` — `ModelArtifact`
4. Create `app/models/tflite_artifact.py` — `TFLiteArtifact`
5. Create `app/models/prediction_result.py` — `PredictionResult`
6. Update `app/models/__init__.py` — re-export all six types

### Phase 2: Update `AutoDiscovery`

7. Update `app/core/nodes/discovery.py` — add recursive Category_Folder scanning and `models_dir` parameter
8. Update `app/core/nodes/__init__.py` — pass `models_dir` to `AutoDiscovery.run()`

### Phase 3: Create Category Folders and Move Audio Nodes

9. Create `app/core/nodes/audio/__init__.py`
10. Move each existing audio node file to `app/core/nodes/audio/` (no import changes needed — they already use absolute imports)
11. Absorb `examples/01–05` audio plugin nodes into `app/core/nodes/audio/` with import cleanup
12. Absorb `plugins/noise_node.py` → `app/core/nodes/audio/noise.py`
13. Create backward-compatibility shim files at the old flat paths

### Phase 4: Create ML Category Folder and Absorb ML Nodes

14. Create `app/core/nodes/ml/__init__.py`
15. Absorb each of the 10 ML nodes from `examples/06/plugins/` into `app/core/nodes/ml/`, replacing `_load_data_types()` with direct absolute imports from `app.models.*`

### Phase 5: Clean Up Source Files

16. Delete `examples/01_wake_word/plugins/background_noise_generator.py`
17. Delete `examples/02_speech_commands/plugins/command_validator.py`
18. Delete `examples/03_environmental_sounds/plugins/duration_filter.py`
19. Delete `examples/04_speaker_verification/plugins/speaker_embedder.py`
20. Delete `examples/05_speech_enhancement/plugins/degradation_pipeline.py`
21. Delete all `examples/06_speech_commands_e2e/plugins/*.py` files (including `data_types.py`)
22. Delete `plugins/noise_node.py`

### Phase 6: Update Tests

23. Update any test files that import from old flat paths to use canonical paths (or rely on shims)
24. Add a test verifying AutoDiscovery correctly scans Category_Folders

### Phase 7: Update Documentation and Steering Files

25. Update `docs/ARCHITECTURE.md` — rebrand + updated file map
26. Update `docs/README.md` — rebrand
27. Update `docs/NODE_SYSTEM.md` — new layout, `DataSample`, ML types, shim deprecation notice
28. Update `.kiro/steering/project-overview.md` — new file map, updated Key Concepts
29. Update `.kiro/steering/node-catalogue.md` — nodes under category subfolder paths
30. Update `.kiro/steering/node-registry.md` — recursive scanning behaviour
31. Update `.kiro/steering/data-models.md` — `DataSample` + ML types

---

## Correctness Properties

### Property 1: AutoDiscovery finds all nodes after restructuring

**Type:** Example-based integration test

After `AutoDiscovery.run()` completes, `registry` must contain every node that was registered before the restructuring, plus the 16 newly absorbed nodes.

**Verification:** `assert len(registry) >= len(original_node_types) + 16`

All pre-existing `node_type` strings must still be present:
```python
for node_type in ["clean", "augment", "split", "stratified_split", "export", ...]:
    assert node_type in registry
```

All absorbed node types must be present:
```python
for node_type in [
    "background_noise_generator", "command_validator", "duration_filter",
    "speaker_embedder", "degradation_pipeline", "noise",
    "feature_extractor", "dataset_builder", "model_builder", "model_trainer",
    "model_evaluator", "tflite_exporter", "inference",
    "confusion_matrix_plot", "training_curves_plot", "feature_visualizer",
]:
    assert node_type in registry
```

### Property 2: Shim imports emit DeprecationWarning

**Type:** Example-based unit test

```python
import warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    from app.core.nodes.clean import CleanNode  # noqa: F401
    assert len(w) == 1
    assert issubclass(w[0].category, DeprecationWarning)
    assert "app.core.nodes.audio.clean" in str(w[0].message)
```

### Property 3: Canonical imports do not emit DeprecationWarning

**Type:** Example-based unit test

```python
import warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    from app.core.nodes.audio.clean import CleanNode  # noqa: F401
    dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(dep_warnings) == 0
```

### Property 4: `node_type` strings are preserved after absorption

**Type:** Example-based test

For each absorbed node, the `node_type` string in the registry must match the original plugin's `node_type` exactly:

```python
assert registry.get_metadata("noise").node_type == "noise"
assert registry.get_metadata("background_noise_generator").node_type == "background_noise_generator"
# ... etc.
```

### Property 5: ML model types are registered in TypeCatalogue

**Type:** Example-based test

```python
catalogue = registry.type_catalogue
assert "app.models.feature_array.FeatureArray" in catalogue
assert "app.models.model_artifact.ModelArtifact" in catalogue
assert "app.models.tflite_artifact.TFLiteArtifact" in catalogue
assert "app.models.prediction_result.PredictionResult" in catalogue
assert "app.models.data_sample.DataSample" in catalogue
assert "app.models.audio_sample.AudioSample" in catalogue
```

### Property 6: `DataSample` is constructable without arguments

**Type:** Example-based unit test

```python
from app.models.data_sample import DataSample
s = DataSample()
assert s.id == ""
assert s.source == ""
assert s.metadata == {}
```

### Property 7: No `DuplicateNodeTypeError` on startup

**Type:** Example-based integration test

`AutoDiscovery.run()` must complete without raising `DuplicateNodeTypeError`. This verifies that no absorbed node accidentally shares a `node_type` with an existing built-in node.

### Property 8: Existing pipeline YAML configs remain valid

**Type:** Example-based integration test

For each example YAML config in `examples/*/`, `validate_pipeline(config, registry)` must return the same result as before the restructuring (no new validation errors introduced by the restructuring).

### Property 9: `app/models/__init__.py` re-exports all six types

**Type:** Example-based unit test

```python
from app.models import (
    AudioSample, DataSample, FeatureArray,
    ModelArtifact, TFLiteArtifact, PredictionResult,
)
# All imports must succeed without ImportError
```
