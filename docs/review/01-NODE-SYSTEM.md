# Node System Review — `app/core/nodes/`

**Date:** 2026-05-18

---

## `base.py`

### N-01 🟡 `__init__` type annotation excludes `None`
```python
# Current
def __init__(self, config: "Config | dict[str, Any]" = None, ...):

# Fix
def __init__(self, config: "Config | dict[str, Any] | None" = None, ...):
```
The default is `None` but the type hint doesn't include `None`. Mypy/Pyright will flag every call that omits `config`.

---

### N-02 🟠 SISO wrapper silently double-wraps dict returns
`_siso_process` always returns `{"output": result}`. If a SISO node's `process()` is refactored to return a dict (e.g. during migration to multi-port), the dict is wrapped again as `{"output": {...}}` instead of being returned directly. No guard exists.

```python
# Dangerous: if raw_process returns {"output": [...]}, result becomes
# {"output": {"output": [...]}}
def _siso_process(self, inputs):
    data = inputs.get("input")
    result = raw_process(self, data)
    return {"output": result}   # no isinstance(result, dict) check
```

**Fix:** Add a guard:
```python
if isinstance(result, dict) and set(result.keys()) == set(cls.output_ports.keys()):
    return result  # already in multi-port format
return {"output": result}
```

---

### N-03 🟠 `process_stream` default blocks the event loop
The default `process_stream` calls `self.process(inputs)` synchronously inside an `async def`. For CPU-bound nodes this blocks the asyncio event loop during streaming execution.

```python
# Current — blocks event loop
async def process_stream(self, inputs):
    result = self.process(inputs)   # synchronous call
    yield result

# Fix
async def process_stream(self, inputs):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, self.process, inputs)
    yield result
```

---

### N-04 🔵 `setup()` not called before `process()` — no enforcement
`setup()` is documented as "called once before the first `on_start()`" but nothing enforces this. A node used outside `NodeExecutor` (e.g. in a unit test) will silently skip `setup()`. Consider adding a `_setup_done` guard on `Node` itself, or document that direct `process()` calls bypass lifecycle.

---

## `ports.py`

### N-05 🟡 `data_type: Any` accepts non-type values silently
`InputPort.data_type` and `OutputPort.data_type` are typed as `Any`. A string like `"AudioSample"` is silently accepted and will cause a `TypeError` deep inside `CompatibilityChecker.are_compatible()` at runtime.

**Fix:** Add a validator:
```python
@field_validator("data_type")
@classmethod
def _must_be_type_or_none(cls, v):
    if v is not None and not isinstance(v, type) and get_origin(v) is None:
        raise ValueError(f"data_type must be a Python type or None, got {v!r}")
    return v
```

---

### N-06 🔵 `InputPort.name` / `OutputPort.name` can drift from dict key
The port name is stored both as `port.name` and as the key in `Node.input_ports`. They can drift out of sync with no validation. `AutoDiscovery._port_to_dict` uses `port.name` for the serialized dict key, not the registry key.

---

## `metadata.py`

### N-07 🔵 `version` field has no format validation
`NodeMetadata.version` accepts any string including `"not-a-version"`. Should validate against a semver or PEP 440 pattern for consistency with `PluginManifest.version`.

---

## `registry.py`

### N-08 🟠 No thread safety on `_classes` / `_metadata`
`register()` and `unregister()` mutate `_classes` and `_metadata` dicts without a lock. Concurrent plugin installs during a running pipeline (e.g. via the REST API) can cause:
- `RuntimeError: dictionary changed size during iteration` in `find_compatible_nodes`
- Silent key overwrites in `register()`

**Fix:** Add `self._lock = threading.RLock()` and wrap all mutations.

---

### N-09 🔵 `from_json` name is misleading
`NodeRegistry.from_json()` is a `@staticmethod` that returns `list[NodeMetadata]` — it does NOT reconstruct or populate a registry. The name implies registry reconstruction. Should be renamed to `parse_metadata_list()` or `metadata_from_json()`.

---

### N-10 🟡 `find_compatible_nodes` is O(N×M)
Iterates all registered nodes × all ports per node on every call. Fine for 29 nodes but degrades with large plugin ecosystems. Should cache results or build an inverted index at registration time.

---

## `discovery.py`

### N-11 🔴 Plugin module name collision
`_import_file` with `package_prefix=None` uses `parent.name` as the module prefix:
```python
module_name = f"{parent}.{path.stem}"  # e.g. "audio_denoiser.nodes"
sys.modules[module_name] = module
```
If two plugins both have a file named `nodes.py`, the second import overwrites `sys.modules["<plugin>.nodes"]` with the first plugin's module name, causing the first plugin's classes to be re-registered under the wrong module. This is a silent correctness bug.

**Fix:** Use the full install path as the module name:
```python
module_name = str(path).replace(os.sep, ".").rstrip(".py")
```

---

### N-12 🟡 `object.__setattr__` on non-frozen model is unnecessary
In `_register_node`:
```python
object.__setattr__(meta, "input_ports", {...})
```
`NodeMetadata` is not frozen (`ConfigDict` does not set `frozen=True`). The `object.__setattr__` bypass is unnecessary and fragile. Should use direct assignment:
```python
meta.input_ports = {k: _port_to_dict(v) for k, v in cls.input_ports.items()}
```

---

## `compat.py`

### N-13 🟡 `Union` / `Optional` types not handled
`get_origin(Optional[X])` returns `typing.Union`. This falls through to Rule 4 in `are_compatible()` and fails the `out_origin != in_origin` check. Ports typed as `Optional[AudioSample]` will always be reported as incompatible with `Optional[AudioSample]`.

**Fix:** Add a Union rule before Rule 4:
```python
if out_origin is Union and in_origin is Union:
    # Both are Union — check if out args are a subset of in args
    ...
```

---

### N-14 🔵 `_type_to_schema` fallback is not valid JSON Schema
```python
return {"type": type_name}  # e.g. {"type": "AudioSample"}
```
`"AudioSample"` is not a valid JSON Schema type. Should be:
```python
return {"type": "object", "title": type_name}
```

---

## `observers.py`

### N-15 🟠 `CompositeObserver` does not isolate observer failures
If one child observer raises an exception, the remaining observers are skipped and the exception propagates to the node executor, potentially aborting the pipeline.

**Fix:**
```python
def on_node_start(self, node_type: str, run_id: str) -> None:
    for obs in self._observers:
        try:
            obs.on_node_start(node_type, run_id)
        except Exception:
            log.warning("Observer %r raised in on_node_start", obs, exc_info=True)
```

---

## `__init__.py`

### N-16 🟠 Full startup cost on every `import app.core.nodes`
Importing `app.core.nodes` triggers `PluginManager().load_enabled_plugins()` + `AutoDiscovery.run()` synchronously. Any test or module that imports from `app.core.nodes` pays this cost. There is no lazy-init option.

**Recommendation:** Wrap in a `_initialized` guard and expose an explicit `initialize()` function for test isolation.

---

### N-17 🟡 Silent swallow of `PluginManager` startup failure
```python
except Exception as exc:
    logging.getLogger(__name__).warning(...)
    # _plugins_loaded_by_manager stays False
```
When `PluginManager` fails, `_plugins_loaded_by_manager = False` causes AutoDiscovery to re-scan the plugins dir. A partial load can result in duplicate registration attempts logged as warnings, masking the root cause.

---

### N-18 🔵 Minimal `__all__` — deep imports required
Only `registry` is exported. `NodeRegistry`, `AutoDiscovery`, `PortDataType`, `InputPort`, `OutputPort`, `NodeMetadata`, `NodeObserver` etc. require deep imports like `from app.core.nodes.base import Node`. Consider re-exporting the full public API surface.
