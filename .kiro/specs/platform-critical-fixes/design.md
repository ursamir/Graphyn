# Technical Design — Platform Critical Fixes

## Overview

Five surgical fixes to `app/core/pipeline.py`, `app/core/nodes/errors.py`,
`app/core/run_manager.py`, `app/core/artifact_store.py`, `app/core/executor.py`,
and `app/core/sdk.py`. No new abstractions are introduced. No public APIs change.
All fixes are backward-compatible.

**Fix order is mandatory.** Bug 3 must be applied before Bug 1 because the dead
function being deleted in Bug 1 also contains a `ResumeError` class definition
that must already be relocated before deletion.

---

## Bug Details

### Bug 1 — Duplicate `run_pipeline_ir_async` definition

`app/core/pipeline.py` contains two definitions of `run_pipeline_ir_async` with
identical signatures. Python module loading silently shadows the first with the
second. The first definition is dead code — any changes to it have no runtime
effect. The second definition is the live one that actually executes.

### Bug 2 — Dual `run_id`: RunManager ID vs executor UUID4

Inside `run_pipeline_ir_async`, after constructing `RunManager` (which generates
`run.run_id` as a 16-char hex string), the function creates a second independent
`run_id = str(uuid.uuid4())` — a full UUID4 string — and passes it to every
`NodeExecutor`. Observer callbacks receive the UUID4. `RunManager` persists the
16-char hex to `meta.json` and uses it as the run directory name. The two values
are never equal, so observer events cannot be correlated with persisted run data.

### Bug 3 — Circular import: `ResumeError` defined in `pipeline.py`

`ResumeError` is defined in `pipeline.py`. `run_manager.py` needs to raise it,
but importing from `pipeline.py` at module load time creates a circular import
(`pipeline` → `run_manager` → `pipeline`). The workaround is two deferred
in-method imports inside `run_manager.py`. `ResumeError` belongs in
`app/core/nodes/errors.py` alongside all other execution error classes.

### Bug 4 — `_infer_artifact_type` is domain logic in the orchestration layer

`_infer_artifact_type()` in `pipeline.py` encodes domain knowledge about
`AudioSample`, `DatasetArtifact`, and feature-array duck-typing. It is also
imported by `executor.py` via `from app.core.pipeline import _infer_artifact_type`,
creating a cross-layer dependency from the executor into the orchestration module.
This function belongs in `app/core/artifact_store.py` alongside `ArtifactStore`
and `SUPPORTED_ARTIFACT_TYPES`.

### Bug 5 — `Pipeline.validate()` always raises `TypeError`

`Pipeline.validate()` in `sdk.py` calls `validate_pipeline(pipeline_cfg)` with
one argument. `validate_pipeline` requires two: `(config, registry)`. Every call
raises `TypeError`, which is caught by a bare `except Exception` and appended to
the errors list. The method always returns a non-empty list, making it impossible
to distinguish a valid pipeline from an invalid one.

---

## Expected Behavior

After all fixes are applied:

- `app/core/pipeline.py` contains exactly one definition of `run_pipeline_ir_async`.
- All observer events carry the same `run_id` that `RunManager` writes to `meta.json`.
- `ResumeError` is importable from `app/core/nodes/errors.py` with no circular import.
- `_infer_artifact_type` is importable from `app/core/artifact_store.py`.
- `Pipeline.validate()` returns `[]` for a valid pipeline and a list of error strings for an invalid one.

---

## Hypothesized Root Cause

**Bug 1:** Iterative development added a second implementation of
`run_pipeline_ir_async` without removing the first. Python does not warn on
duplicate function definitions in the same module.

**Bug 2:** The executor `run_id` was introduced before `RunManager` existed as
the authoritative source of run identity. When `RunManager` was added, the
executor's UUID4 was not replaced with `run.run_id`.

**Bug 3:** `ResumeError` was defined in `pipeline.py` for convenience during
initial development. When `run_manager.py` needed it, the circular import was
worked around with deferred imports rather than relocating the class.

**Bug 4:** `_infer_artifact_type` was added to `pipeline.py` during the artifact
integration phase for convenience. The correct home (`artifact_store.py`) was not
chosen at the time.

**Bug 5:** `Pipeline.validate()` was added after `validate_pipeline` already
required two arguments. The `registry` argument was omitted by mistake.

---

## Fix Implementation

### Fix Order

```
Fix 1 (Bug 3: move ResumeError)
  └── enables Fix 2 (Bug 1: delete dead function safely)
        └── enables Fix 3 (Bug 2: fix run_id in surviving function)

Fix 4 (Bug 4: move _infer_artifact_type)   ← independent, apply after Fix 2
Fix 5 (Bug 5: fix validate())              ← fully independent
```

### Fix 1 — Bug 3: Relocate `ResumeError` to `app/core/nodes/errors.py`

**Change 1a — `app/core/nodes/errors.py`**

Append to the bottom of the existing error hierarchy:

```python
class ResumeError(RuntimeError):
    """Raised when a resume operation cannot be completed."""
```

`ResumeError` subclasses `RuntimeError` (not `NodeSystemError`) because it is a
runtime execution error, not a node-system structural error.

**Change 1b — `app/core/pipeline.py`**

Remove the inline class definition:
```python
class ResumeError(RuntimeError):
    """Raised when a resume operation cannot be completed."""
```

Add to the top-level imports:
```python
from app.core.nodes.errors import ResumeError
```

**Change 1c — `app/core/run_manager.py`**

Add to top-level imports (after the existing `from app.core.config import ...` line):
```python
from app.core.nodes.errors import ResumeError
```

In `load_resume_state()`, remove the deferred import:
```python
# REMOVE:
from app.core.pipeline import ResumeError
```

In `find_latest_checkpoint()`, remove the deferred import of `_load_checkpoint_outputs`:
```python
# REMOVE:
from app.core.pipeline import _load_checkpoint_outputs
```

`_load_checkpoint_outputs` is still needed in `find_latest_checkpoint()`. It
remains as a lazy import but the `ResumeError` import line is removed. The
`_load_checkpoint_outputs` lazy import stays in `pipeline.py` — it is a function
import, not an error class, and lazy function imports are acceptable.

### Fix 2 — Bug 1: Remove the dead `run_pipeline_ir_async` definition

**Change 2a — `app/core/pipeline.py`**

Delete the entire first definition of `run_pipeline_ir_async` — from its
`async def run_pipeline_ir_async(` line through to (but not including) the
second `async def run_pipeline_ir_async(` line. The second definition and all
code after it remain untouched.

The first (dead) definition is identified by its docstring beginning:
> "Execute a pipeline from a GraphIR object (async-native entry point). This is
> the async implementation of the pipeline executor. All execution logic lives
> here; `run_pipeline_ir()` is a synchronous shim that calls
> `asyncio.run(run_pipeline_ir_async(...))`."

### Fix 3 — Bug 2: Unify `run_id` to use `run.run_id`

**Change 3a — `app/core/pipeline.py`, inside `run_pipeline_ir_async`**

Locate:
```python
run_id = str(uuid.uuid4())
```

Replace with:
```python
run_id = run.run_id
```

After this change, verify whether `uuid` is still used elsewhere in `pipeline.py`.
If not, remove `import uuid` from the imports.

### Fix 4 — Bug 4: Move `_infer_artifact_type` to `app/core/artifact_store.py`

**Change 4a — `app/core/artifact_store.py`**

Add `_infer_artifact_type` as a module-level function immediately after the
`SUPPORTED_ARTIFACT_TYPES` frozenset definition. The function body is identical
to the current implementation in `pipeline.py`:

```python
def _infer_artifact_type(value: Any) -> str:
    """Infer the ArtifactStore artifact_type string from a node output value."""
    try:
        from app.models.dataset_artifact import DatasetArtifact  # noqa: PLC0415
        if isinstance(value, DatasetArtifact):
            return "generic"
    except ImportError:
        pass

    if isinstance(value, list) and value:
        first = value[0]
        if hasattr(first, "data") and hasattr(first, "sample_rate"):
            return "audio_samples"
        if hasattr(first, "model_dump"):
            return "generic"

    if isinstance(value, dict):
        if any(k in value for k in ("train", "val", "test")):
            return "generic"
        if any(k in value for k in ("features", "feature_array")):
            return "feature_array"

    try:
        import numpy as np
        if isinstance(value, np.ndarray):
            return "feature_array"
    except ImportError:
        pass

    return "generic"
```

**Change 4b — `app/core/pipeline.py`**

Remove the `_infer_artifact_type` function definition entirely.

Add to the imports section:
```python
from app.core.artifact_store import _infer_artifact_type
```

**Change 4c — `app/core/executor.py`**

Change:
```python
from app.core.pipeline import _infer_artifact_type
```
To:
```python
from app.core.artifact_store import _infer_artifact_type
```

### Fix 5 — Bug 5: Fix `Pipeline.validate()` missing `registry` argument

**Change 5a — `app/core/sdk.py`, `Pipeline.validate()` method**

Locate:
```python
validate_pipeline(pipeline_cfg)
```

Replace with:
```python
from app.core.registry_runtime import get_registry  # noqa: PLC0415
registry = get_registry()
validate_pipeline(pipeline_cfg, registry)
```

The import is placed inline (lazy) to match the existing pattern in `sdk.py`
where other imports are deferred to avoid circular dependencies at module load.

---

## Files Modified

| File | Bugs Fixed | Nature of Change |
|---|---|---|
| `app/core/nodes/errors.py` | Bug 3 | Add `ResumeError` class |
| `app/core/pipeline.py` | Bugs 1, 2, 3, 4 | Remove dead function, fix run_id, relocate ResumeError import, relocate _infer_artifact_type import |
| `app/core/run_manager.py` | Bug 3 | Replace deferred import with top-level import |
| `app/core/artifact_store.py` | Bug 4 | Add `_infer_artifact_type` function |
| `app/core/executor.py` | Bug 4 | Update import source |
| `app/core/sdk.py` | Bug 5 | Add `registry` argument to `validate_pipeline` call |

---

## Testing Strategy

Each fix has a corresponding verification command that can be run immediately
after applying it:

**After Fix 1 (Bug 3):**
```bash
python -c "from app.core.nodes.errors import ResumeError; print('OK')"
python -c "from app.core.run_manager import RunManager; print('OK')"
```

**After Fix 2 (Bug 1):**
```bash
grep -c "^async def run_pipeline_ir_async" app/core/pipeline.py
# Expected output: 1
```

**After Fix 3 (Bug 2):**
```bash
grep "run_id = " app/core/pipeline.py | grep -v "run\.run_id"
# Expected: no output (no remaining UUID4 run_id assignments)
```

**After Fix 4 (Bug 4):**
```bash
python -c "from app.core.artifact_store import _infer_artifact_type; print('OK')"
grep "_infer_artifact_type" app/core/pipeline.py
# Expected: only the import line, no function definition
```

**After Fix 5 (Bug 5):**
```bash
python -c "
from app.core.sdk import Pipeline, PipelineNode
# A pipeline with no nodes is invalid — should return errors, not raise TypeError
p = Pipeline.__new__(Pipeline)
p.nodes = []
p.seed = 42
p.name = 'test'
p.description = ''
p._explicit_edges = None
p._subscribers = []
p._last_run_id = None
from app.core.ir.loader import CURRENT_IR_VERSION
from app.core.ir.models import GraphIR, IRMetadata
p._graph_ir = GraphIR(schema_version=CURRENT_IR_VERSION, metadata=IRMetadata(name='test', seed=42), nodes=[], edges=[])
result = p.validate()
print(type(result), result)
# Expected: <class 'list'> [...] — a list, not a TypeError
"
```

---

## Correctness Properties

### Property 1: Single function definition

After Fix 2, `app/core/pipeline.py` contains exactly one definition of
`run_pipeline_ir_async`. Verified by:
```
grep -c "^async def run_pipeline_ir_async" app/core/pipeline.py == 1
```

**Validates: Requirements 2.1, 2.2, 2.3**

### Property 2: Unified run_id

For any pipeline execution, the `run_id` value in `meta.json` equals the
`run_id` received by all observer `on_node_start`, `on_node_end`, and
`on_node_error` callbacks.

**Validates: Requirements 2.4, 2.5, 2.6**

### Property 3: No circular import at module load

`python -c "from app.core.run_manager import RunManager"` succeeds without
importing `app.core.pipeline` at module load time.

**Validates: Requirements 2.7, 2.8**

### Property 4: ResumeError importable from errors module

`python -c "from app.core.nodes.errors import ResumeError"` succeeds.

**Validates: Requirements 2.9, 2.10**

### Property 5: _infer_artifact_type importable from artifact_store

`python -c "from app.core.artifact_store import _infer_artifact_type"` succeeds.

**Validates: Requirements 2.11, 2.12, 2.13**

### Property 6: validate() returns correct type

`Pipeline.validate()` returns `list[str]` in all cases — never raises `TypeError`.
Returns `[]` for a valid pipeline, non-empty list for an invalid one.

**Validates: Requirements 2.14, 2.15, 2.16**

---

## Glossary

| Term | Definition |
|---|---|
| Dead code | Code that is syntactically valid but never executed at runtime |
| Circular import | Two modules that each import from the other at module load time |
| Deferred import | An import statement placed inside a function body rather than at module top level, used to break circular import cycles |
| run_id | A string identifier unique to one pipeline execution, used to correlate run metadata, observer events, and persisted artifacts |
| Observer | An object passed to `NodeExecutor` that receives lifecycle events (`on_node_start`, `on_node_end`, `on_node_error`) |
