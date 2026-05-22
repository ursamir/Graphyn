# SDK & Utilities Review

**Date:** 2026-05-18  
**Files:** `sdk.py`, `utils/hash.py`, `utils/__init__.py`, `__init__.py`

---

## `sdk.py`

### S-01 🟠 `Pipeline.run()` and `run_with_manager()` duplicate ~30 lines
Both methods contain identical execution logic: create `RunManager`, serialize IR, wrap logger, call `run_pipeline_ir`, build `ArtifactCollection`. Any change to execution behavior must be made in two places.

**Fix:** `run()` should delegate to `run_with_manager()` and discard the manager:
```python
def run(self, **kwargs) -> ArtifactCollection:
    collection, _ = self.run_with_manager(**kwargs)
    return collection
```

---

### S-02 🟠 `Pipeline.run()` accesses `RunManager._artifacts` — private attribute coupling
```python
return ArtifactCollection(
    artifacts=_internal_run_manager._artifacts,   # ← private
    ...
)
```
`_artifacts` is a private list on `RunManager`. This creates fragile coupling — any rename or restructuring of `RunManager` internals breaks `sdk.py`.

**Fix:** Add a public property to `RunManager`:
```python
@property
def artifacts(self) -> list[ArtifactRecord]:
    return list(self._artifacts)
```

---

### S-03 🟠 `Pipeline.run()` serializes and deserializes IR on every run for no reason
```python
graph = load_ir(dump_ir(self._graph_ir))
```
`self._graph_ir` is already a valid, validated `GraphIR`. This round-trip through JSON is used as a deep-copy mechanism but is expensive and lossy (any non-JSON-serializable metadata would be dropped).

**Fix:**
```python
import copy
graph = copy.deepcopy(self._graph_ir)
```

---

### S-04 🟡 `from_json()` and `from_yaml()` call `_build_ir()` in `__init__` then immediately overwrite
```python
@classmethod
def from_json(cls, path: str) -> "Pipeline":
    graph = load_ir_from_file(path)
    nodes = [PipelineNode(node.node_type, dict(node.config)) for node in graph.nodes]
    pipeline = cls(nodes=nodes, ...)   # ← _build_ir() called here, validates all node types
    pipeline._graph_ir = graph         # ← immediately overwritten
    return pipeline
```
`_build_ir()` is called during `cls(nodes=nodes, ...)` which triggers `PipelineNode._validate()` for every node — this hits the registry and validates configs. Then `_graph_ir` is overwritten with the loaded IR. The validation work is wasted, and if a node type is not registered yet, `from_json()` raises even though the IR is valid.

**Fix:** Add a `_skip_build` parameter or a `_from_ir` classmethod that bypasses `_build_ir()`:
```python
@classmethod
def _from_ir(cls, graph: GraphIR) -> "Pipeline":
    pipeline = object.__new__(cls)
    pipeline._graph_ir = graph
    pipeline._subscribers = []
    pipeline._last_run_id = None
    # populate other fields from graph.metadata
    return pipeline
```

---

### S-05 🟡 `_make_subscriber_logger` creates a new class on every call
```python
def _make_subscriber_logger(self, base_logger):
    class _SubscriberLogger(PipelineLogger):
        def _emit(self, event):
            ...
    return _SubscriberLogger(...)
```
Python creates a new class object on every call to `_make_subscriber_logger`. For pipelines that call `run()` many times, this creates many class objects that are never garbage collected (Python caches class objects).

**Fix:** Define `_SubscriberLogger` at module level, parameterized by the subscribers list:
```python
class _SubscriberLogger(PipelineLogger):
    def __init__(self, subscribers, **kwargs):
        super().__init__(**kwargs)
        self._subscribers = subscribers

    def _emit(self, event):
        super()._emit(event)
        for cb in list(self._subscribers):
            try:
                cb(event)
            except Exception:
                pass
```

---

### S-06 🟡 Subscriber exceptions are silently swallowed
```python
try:
    cb(event)
except Exception:
    pass  # subscriber errors must not abort execution
```
A subscriber with a bug (e.g. `KeyError` on `event["node_type"]`) fails silently. The developer has no way to know their subscriber is broken.

**Fix:** Log the exception at WARNING level:
```python
except Exception:
    log.warning("Pipeline subscriber %r raised an exception", cb, exc_info=True)
```

---

## `utils/hash.py`

### S-07 🔴 Separator collision — false cache hits
```python
def stable_hash(*args) -> int:
    s = "|".join(str(a) for a in args)
    return int(hashlib.md5(s.encode(), usedforsecurity=False).hexdigest(), 16)
```
The `"|"` separator is part of the hash input. If any argument contains `"|"`, the hash collides with a different argument split:

```python
stable_hash("a|b", "c") == stable_hash("a", "b|c")  # True — same string "a|b|c"
```

This is used in `PipelineGraph._build()` to derive node seeds:
```python
node_seed = stable_hash(seed, spec.node_type, i) % (2 ** 32)
```
If `spec.node_type` contains `"|"` (unlikely but possible for plugin node types), two different nodes could get the same seed.

Also: `None` and `"None"` collide because `str(None) == "None"`.

**Fix:** Use a length-prefixed or JSON-encoded representation:
```python
import json

def stable_hash(*args) -> int:
    s = json.dumps(list(args), sort_keys=True, default=str)
    return int(hashlib.md5(s.encode(), usedforsecurity=False).hexdigest(), 16)
```

---

### S-08 🔵 `utils/__init__.py` is empty — `stable_hash` not re-exported
`stable_hash` is not re-exported from `app.core.utils`, requiring callers to use the deep import `from app.core.utils.hash import stable_hash`. Should be re-exported:

```python
# utils/__init__.py
from app.core.utils.hash import stable_hash

__all__ = ["stable_hash"]
```

---

## `app/core/__init__.py`

### S-09 🟠 Eager import of `pipeline.py` at package init time
```python
# app/core/__init__.py
from app.core.pipeline import ResumeError
```
Importing `app.core` (or any submodule that does `from app.core import ...`) triggers the full import of `pipeline.py`, which imports `nodes/base.py`, `nodes/registry.py`, `ir/models.py`, etc. This makes `app.core` a heavyweight import.

**Fix:** Either move `ResumeError` to a lightweight exceptions module, or use a lazy import:
```python
# Option A: move ResumeError to app/core/exceptions.py
# Option B: lazy import
def __getattr__(name):
    if name == "ResumeError":
        from app.core.pipeline import ResumeError
        return ResumeError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

---

## Test Coverage Gaps

The following areas have zero or near-zero test coverage based on the test files reviewed:

| Area | Gap |
|---|---|
| `stable_hash()` | No tests at all — the collision bug (S-07) is undetected |
| `Pipeline.subscribe()` / unsubscribe | No tests |
| `Pipeline.get_last_run_id()` | No tests |
| `PipelineNode.to_dict()` | No tests |
| `PipelineNode.to_ir_node()` | No tests |
| `Pipeline.from_json()` edge routing preservation | Not tested |
| `Pipeline.from_yaml()` edge routing preservation | Not tested |
| `ArtifactCollection.lineage()` with real `ProvenanceStore` | Only mocked |
| `_make_subscriber_logger` subscriber exception isolation | Not tested |
| `Pipeline.run()` with `parallel=True` | Not tested in SDK tests |
| `conftest.py` / shared fixtures | Missing — `GRAPHYN_PROJECT_DIR` monkeypatch duplicated across 10+ test files |

**Recommendation:** Create a shared `tests/conftest.py` with:
```python
@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    yield tmp_path
```
This eliminates the repeated `monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))` in every test class.
