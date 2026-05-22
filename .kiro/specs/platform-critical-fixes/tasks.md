# Implementation Plan: Platform Critical Fixes

## Overview

Nine implementation tasks across six files, fixing five critical bugs in strict
dependency order. Bug 3 (circular import) must be resolved first because it
unblocks safe deletion of the dead function (Bug 1), which in turn exposes the
correct location for the run_id fix (Bug 2). Bug 4 and Bug 5 are independent
and follow after the pipeline.py cleanup.

## Tasks

- [x] 1. Add `ResumeError` to `app/core/nodes/errors.py`
- [x] 2. Update `app/core/pipeline.py` — remove inline `ResumeError` class, add import from `errors.py`
- [x] 3. Update `app/core/run_manager.py` — replace deferred imports with top-level `ResumeError` import
- [x] 4. Remove the dead first `run_pipeline_ir_async` definition from `app/core/pipeline.py`
- [x] 5. Fix dual `run_id` — replace `str(uuid.uuid4())` with `run.run_id` in `run_pipeline_ir_async`
- [x] 6. Add `_infer_artifact_type` function to `app/core/artifact_store.py`
- [x] 7. Update `app/core/pipeline.py` — remove `_infer_artifact_type` definition, add import from `artifact_store.py`
- [x] 8. Update `app/core/executor.py` — change `_infer_artifact_type` import source to `artifact_store.py`
- [x] 9. Fix `Pipeline.validate()` in `app/core/sdk.py` — pass `registry` argument to `validate_pipeline`

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": [1, 9], "description": "Foundation: add ResumeError to errors.py (unblocks wave 2); fix Pipeline.validate() independently" },
    { "wave": 2, "tasks": [2], "description": "Remove ResumeError from pipeline.py, add import — requires Task 1" },
    { "wave": 3, "tasks": [3], "description": "Fix run_manager.py deferred imports — requires Task 2" },
    { "wave": 4, "tasks": [4], "description": "Delete dead run_pipeline_ir_async — requires Task 3 (no ResumeError class in pipeline.py)" },
    { "wave": 5, "tasks": [5], "description": "Fix dual run_id — requires Task 4 (single surviving function)" },
    { "wave": 6, "tasks": [6], "description": "Add _infer_artifact_type to artifact_store.py — requires Task 5 (pipeline.py stable)" },
    { "wave": 7, "tasks": [7], "description": "Remove _infer_artifact_type from pipeline.py, add import — requires Task 6" },
    { "wave": 8, "tasks": [8], "description": "Fix executor.py import source — requires Task 7" }
  ]
}
```

## Notes

**Task 1** must complete before Task 2. The class must exist in `errors.py`
before it is removed from `pipeline.py`, so that any import of `ResumeError`
from `pipeline.py` continues to work during the transition.

**Task 3** removes two deferred in-method imports from `run_manager.py`. The
`_load_checkpoint_outputs` lazy import in `find_latest_checkpoint()` is removed
as an import line — the function call itself stays. If `_load_checkpoint_outputs`
was the only thing imported from `pipeline.py` in that method, add back a lazy
import immediately before the call:
```python
from app.core.pipeline import _load_checkpoint_outputs  # noqa: PLC0415
```

**Task 4** deletes the first (dead) `run_pipeline_ir_async` definition. It is
identified by its docstring: *"This is the async implementation of the pipeline
executor. All execution logic lives here; `run_pipeline_ir()` is a synchronous
shim..."*. Delete from its `async def` line through to (but not including) the
second `async def run_pipeline_ir_async` line.

**Task 5** — after replacing `run_id = str(uuid.uuid4())` with `run_id = run.run_id`,
check whether `uuid` is still used elsewhere in `pipeline.py`. If not, remove
`import uuid` from the imports block.

**Task 6** — place `_infer_artifact_type` immediately after the
`SUPPORTED_ARTIFACT_TYPES` frozenset definition and before the error classes.
The function body is identical to the current implementation in `pipeline.py`.

**Task 9** — the `get_registry()` import is placed inline (lazy) inside
`Pipeline.validate()` to match the existing deferred-import pattern in `sdk.py`.

### Verification commands (run after all tasks complete)

```bash
# Property 1: exactly one run_pipeline_ir_async definition
grep -c "^async def run_pipeline_ir_async" app/core/pipeline.py
# Expected: 1

# Property 3: no circular import at module load
venv/bin/python -c "from app.core.run_manager import RunManager; print('OK')"

# Property 4: ResumeError importable from errors module
venv/bin/python -c "from app.core.nodes.errors import ResumeError; print('OK')"

# Property 5: _infer_artifact_type importable from artifact_store
venv/bin/python -c "from app.core.artifact_store import _infer_artifact_type; print('OK')"

# Property 6: validate() returns list, never raises TypeError
venv/bin/python -c "from app.core.sdk import Pipeline; print('import OK')"

# Full test suite
venv/bin/pytest --tb=short -q
```
