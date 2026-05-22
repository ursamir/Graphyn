# G1 Node System — Second-Pass Deep Review
**Module group:** `app/core/nodes/`
**Date:** 2026-05-19
**Reviewer:** Kiro AI
**Scope:** 12 files, 8 dimensions each, open-item verdicts for N-04 / N-06 / N-10 / N-11

---

## PHASE 1 — EXPLORATION PLAN

| # | File | Stated Purpose | Key Review Questions |
|---|------|---------------|----------------------|
| 1 | `nodes/base.py` | Domain-agnostic base class for all pipeline nodes | Is `setup()` enforced before `process()`? Is the SISO wrapper safe? Does `process_stream` block the event loop? Are lifecycle hooks documented accurately? |
| 2 | `nodes/ports.py` | Port descriptors (`InputPort`/`OutputPort`) and `PortDataType` base | Can `port.name` drift from its dict key? Is the `data_type` validator complete? Are generic aliases handled? |
| 3 | `nodes/config.py` | `NodeConfig` Pydantic base for all node configuration models | Is `extra="forbid"` correct? Is `frozen=False` intentional? Any missing config options? |
| 4 | `nodes/metadata.py` | `NodeMetadata` — node identity, ports, capability fields | Is version validation correct? Are capability field defaults safe? Is the `_non_empty` validator sufficient? |
| 5 | `nodes/retry.py` | `RetryPolicy` — exponential back-off configuration | Is the wait formula correct? Are validators complete? Is `attempt_index` semantics documented clearly? |
| 6 | `nodes/registry.py` | `NodeRegistry` singleton — maps `node_type` → class + metadata | Is thread safety complete? Is `find_compatible_nodes` O(N×M)? Is `from_json` misleading? |
| 7 | `nodes/discovery.py` | `AutoDiscovery` — scans dirs and registers Node/PortDataType subclasses | Is plugin module name collision fixed? Is `_import_file` safe? Are errors handled correctly? |
| 8 | `nodes/catalogue.py` | `TypeCatalogue` — maps FQN strings to Python type objects | Is `find_compatible_nodes` O(N×M) here? Is thread safety present? Is `resolve` error message helpful? |
| 9 | `nodes/compat.py` | `CompatibilityChecker` + JSON Schema helpers | Are Union/Optional types handled? Is `_type_to_schema` fallback valid JSON Schema? Is `check_connection` complete? |
| 10 | `nodes/errors.py` | Custom exception hierarchy for the node system | Is the hierarchy complete? Are exceptions documented? Any missing error types? |
| 11 | `nodes/observers.py` | Observer interfaces and implementations for lifecycle events | Does `CompositeObserver` isolate failures? Is `LoggingObserver` structured correctly? |
| 12 | `nodes/__init__.py` | Public API — triggers AutoDiscovery at import time | Is startup cost acceptable? Is test isolation provided? Is `__all__` complete? |

---

## PHASE 2 — PER-FILE FINDINGS


---

## File 1 — `nodes/base.py`

### D1 — Code Quality & Correctness

**N-04 verdict (setup() enforcement):** See Open Items section below.

**[G1-01] SISO double-wrap guard uses set equality — fragile for partial-output nodes**
The guard added since the first pass is:
```python
if isinstance(result, dict) and set(result.keys()) == set(cls.output_ports.keys()):
    return result
```
This is correct for the common case but silently passes through a dict that happens to have the same keys as the output ports even when the node author intended to return a plain dict as data. For example, a node with `output_ports = {"output": ...}` that returns `{"output": 42}` as its data payload will be passed through unwrapped, producing `{"output": 42}` at the pipeline level — which is correct. However, if the node returns `{"output": None}` intentionally as a null result, the guard still passes it through correctly. The logic is sound but the comment in the code does not explain the edge case where a SISO node's data payload is itself a dict with a key named `"output"`.

**Severity:** 🟡 Medium — D1 / D7
**Evidence:** `base.py` lines 183–186 (`_siso_process` guard)
**Proposed Fix:** Add an inline comment: `# Guard: if result is already in multi-port format (keys == output port names), pass through unchanged.`

---

**[G1-02] `process_stream` uses deprecated `get_event_loop()`**
```python
loop = _asyncio.get_event_loop()
result = await loop.run_in_executor(None, self.process, inputs)
```
`asyncio.get_event_loop()` is deprecated in Python 3.10+ when there is no running event loop; the correct call inside an `async def` is `asyncio.get_running_loop()`.

**Severity:** 🟠 High — D1
**File:** `nodes/base.py`
**Evidence:** Lines ~155–157 (`process_stream` default implementation)
**Proposed Fix:**
```python
async def process_stream(self, inputs):
    import asyncio as _asyncio
    loop = _asyncio.get_running_loop()
    result = await loop.run_in_executor(None, self.process, inputs)
    yield result
```

---

### D2 — Architecture & Design

**[G1-03] `Node` carries observer as an instance attribute but lifecycle hooks are not wired**
`Node.__init__` accepts `observer: Any` and stores it as `self.observer`, but `Node.process()`, `on_start()`, `on_end()`, and `on_error()` never call `self.observer.*`. The observer is only useful if the pipeline executor calls it externally. This creates an implicit contract: the observer field on `Node` implies the node will call it, but it does not. Callers who set `observer=LoggingObserver()` on a node and call `node.process()` directly will receive no events.

**Severity:** 🟠 High — D2 / D7
**File:** `nodes/base.py`
**Evidence:** `__init__` stores `self.observer`; `process()`, `on_start()`, `on_end()`, `on_error()` have no observer calls.
**Proposed Fix:** Either (a) wire observer calls into the lifecycle hooks in `Node` itself, or (b) document clearly in the class docstring that `observer` is consumed by the pipeline executor, not by `Node` directly.

---

### D3 — Error Handling

**[G1-04] `_siso_process` swallows `KeyError` from `inputs.get("input")`**
`inputs.get("input")` returns `None` silently if the key is missing. For a required SISO input port, this means a misconfigured pipeline passes `None` to `process(data)` with no error at the port-binding layer. The error surfaces only inside the node's logic (if at all), making debugging harder.

**Severity:** 🟡 Medium — D3
**File:** `nodes/base.py`
**Evidence:** `_siso_process` line: `data = inputs.get("input")`
**Proposed Fix:**
```python
if "input" not in inputs:
    raise KeyError(
        f"SISO node '{type(self).__name__}' expected key 'input' in inputs dict, "
        f"got keys: {list(inputs)}"
    )
data = inputs["input"]
```

---

### D4 — Performance

No issues found. The SISO wrapper adds one dict lookup and one function call — negligible overhead.

### D5 — Test Coverage Gaps

**[G1-05] No test for `_maybe_wrap_siso` with an already-wrapped class (re-subclassing)**
If a SISO node is subclassed and the subclass does not override `process`, `__init_subclass__` is called again. The `if getattr(raw_process, "__wrapped__", None) is not None: return` guard handles this, but there is no test verifying that double-wrapping does not occur when a SISO node is subclassed.

**Severity:** 🟡 Medium — D5
**File:** `nodes/base.py`
**Proposed Fix:** Add a test: `class SubNode(MySISONode): pass` — verify `SubNode.process.__wrapped__` is the original raw function, not a double-wrapped one.

---

### D6 — Security

No issues found. No I/O, no credential handling, no path operations.

### D7 — Documentation

**[G1-06] `setup()` docstring says "Called once before the first `on_start()`" but nothing enforces this**
The docstring creates a false contract. See N-04 verdict in Open Items.

**Severity:** 🟡 Medium — D7
**File:** `nodes/base.py`
**Evidence:** `setup()` docstring, line ~170
**Proposed Fix:** Add: `"Note: enforcement of this ordering is the responsibility of the pipeline executor. Direct calls to process() bypass this lifecycle."`

---

### D8 — Convention Adherence

No issues found. Imports follow `from __future__ import annotations` pattern; `ClassVar` usage is correct; naming matches steering file conventions.


---

## File 2 — `nodes/ports.py`

### D1 — Code Quality & Correctness

**[G1-07] `_must_be_type_or_none` validator does not handle `Union` / `Optional` from `typing`**
`get_origin(Optional[str])` returns `typing.Union`, which is not `None`, so the validator passes it through correctly. However, `get_origin(str | int)` (PEP 604 union syntax, Python 3.10+) returns `types.UnionType`, which is also not `None`. Both cases are handled correctly by the `get_origin(v) is None` check — the validator only rejects values where `get_origin` returns `None` AND the value is not a `type`. This is correct.

**No issue** — the validator is sound for all standard type forms.

### D2 — Architecture & Design

**N-06 verdict (port.name drift):** See Open Items section below.

**[G1-08] `PortDataType` inherits `BaseModel` but is used as a type annotation, not an instance**
`PortDataType` subclasses are used as *type objects* (passed as `data_type=AudioSample`) not as instances. Inheriting from `BaseModel` is intentional (it gives Pydantic schema generation), but the class docstring does not explain this dual role. New contributors may be confused about when to instantiate vs. when to pass the class itself.

**Severity:** 🟡 Medium — D7 (documentation gap)
**File:** `nodes/ports.py`
**Evidence:** `PortDataType` class docstring
**Proposed Fix:** Add to docstring: `"Subclasses are used as type objects (passed as data_type=MyType), not as instances. Pydantic BaseModel inheritance enables JSON Schema generation via model_json_schema()."`

---

### D3 — Error Handling

No issues found. The `_must_be_type_or_none` validator raises `ValueError` with a clear message at port declaration time.

### D4 — Performance

No issues found. Port objects are created once at class definition time.

### D5 — Test Coverage Gaps

**[G1-09] No test for `InputPort` with `cardinality="multi"` and `required=False` combination**
The combination of `cardinality="multi"` and `required=False` is valid but untested. The pipeline runtime presumably passes an empty list `[]` for an unconnected multi-cardinality optional port, but this is not validated or documented.

**Severity:** 🟡 Medium — D5
**File:** `nodes/ports.py`
**Proposed Fix:** Add a test verifying that `InputPort(name="x", data_type=str, cardinality="multi", required=False)` is valid and document what the runtime passes for unconnected multi-optional ports.

---

### D6 — Security

No issues found.

### D7 — Documentation

**[G1-10] `OutputPort` has no `required` or `cardinality` field — asymmetry undocumented**
`InputPort` has `cardinality` and `required`; `OutputPort` has neither. This asymmetry is intentional (outputs always produce a value) but is not explained in the docstring. Developers porting from other frameworks may expect `OutputPort` to have a `required` field.

**Severity:** 🔵 Low — D7
**File:** `nodes/ports.py`
**Proposed Fix:** Add to `OutputPort` docstring: `"Note: output ports always produce a value; cardinality and required are not applicable."`

---

### D8 — Convention Adherence

No issues found. Both port classes use `ConfigDict(arbitrary_types_allowed=True)` correctly.


---

## File 3 — `nodes/config.py`

### D1 — Code Quality & Correctness

No issues found. `extra="forbid"` is correct; `frozen=False` is intentional (configs are mutable post-construction per the docstring).

### D2 — Architecture & Design

**[G1-11] `populate_by_name=True` has no effect without `alias` fields — misleading config**
`populate_by_name=True` only matters when fields have `alias` or `validation_alias` set. Since `NodeConfig` itself has no fields, and the steering file does not mention aliases, this option is set "just in case" but adds no value and may confuse contributors who wonder why it's there.

**Severity:** 🔵 Low — D2 / D7
**File:** `nodes/config.py`
**Proposed Fix:** Add a comment: `# populate_by_name=True: allows subclasses to use field aliases while still accepting the original field name.`

---

### D3 — Error Handling

No issues found. Pydantic's `extra="forbid"` raises `ValidationError` on unknown fields.

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

**[G1-12] No test verifying that `extra="forbid"` is inherited by subclasses**
A subclass that overrides `model_config` without `extra="forbid"` would silently accept unknown fields. There is no test confirming that the base config's `extra="forbid"` is inherited.

**Severity:** 🟡 Medium — D5
**File:** `nodes/config.py`
**Proposed Fix:** Add a test: `class MyConfig(NodeConfig): x: int = 1` — verify `MyConfig.model_validate({"x": 1, "unknown": 2})` raises `ValidationError`.

---

### D6 — Security

No issues found.

### D7 — Documentation

**[G1-13] Docstring example uses `CleanConfig` as an intermediate base — pattern is non-standard**
The docstring shows:
```python
class CleanConfig(NodeConfig):
    sample_rate: int = 16000

class CleanNode(Node):
    class Config(CleanConfig):
        pass
```
This two-level inheritance is unusual and not the pattern shown in `node-base.md`. The steering file shows `class Config(NodeConfig)` directly. The docstring example may mislead contributors into creating unnecessary intermediate config classes.

**Severity:** 🔵 Low — D7
**File:** `nodes/config.py`
**Proposed Fix:** Update the docstring example to match the steering file pattern: `class Config(NodeConfig): sample_rate: int = 16000`

---

### D8 — Convention Adherence

No issues found.


---

## File 4 — `nodes/metadata.py`

### D1 — Code Quality & Correctness

**[G1-14] `_version_format` regex accepts single-digit versions like `"1"` — may be too permissive**
The regex `r"^\d+(\.\d+)*([.\-+][a-zA-Z0-9._\-+]*)?$"` accepts `"1"` and `"1.0"` as valid versions. The docstring says "semver-like" but semver requires three components (`MAJOR.MINOR.PATCH`). This is a deliberate relaxation, but it is not documented as such. A version string of `"1"` will pass validation and be stored, which may cause issues in downstream version comparison logic.

**Severity:** 🟡 Medium — D1 / D7
**File:** `nodes/metadata.py`
**Evidence:** `_version_format` validator, regex pattern
**Proposed Fix:** Either tighten to require at least `MAJOR.MINOR` (`r"^\d+\.\d+.*"`) or add a comment explaining why single-digit versions are accepted.

---

**[G1-15] Mutable default `tags: list[str] = []` and `dependency_requirements: list[str] = []`**
Pydantic handles mutable defaults correctly (it copies them per instance), so this is not a Python gotcha. However, the pattern `tags: list[str] = []` is correct in Pydantic v2 and no issue exists here.

**No issue** — Pydantic v2 handles mutable defaults safely.

### D2 — Architecture & Design

**[G1-16] `input_ports` and `output_ports` stored as `dict[str, dict[str, Any]]` — type information is lost**
Port data types are serialised to FQN strings by `AutoDiscovery._port_to_dict`. When `NodeMetadata` is round-tripped through JSON, the `data_type` field is a string like `"app.models.audio_sample.AudioSample"` — not a Python type. Any code that reads `metadata.input_ports["input"]["data_type"]` and expects a type object will get a string. This is an intentional design trade-off (JSON serializability) but is not documented.

**Severity:** 🟡 Medium — D2 / D7
**File:** `nodes/metadata.py`
**Evidence:** `input_ports: dict[str, dict[str, Any]] = {}`
**Proposed Fix:** Add a docstring note: `"data_type values in input_ports/output_ports are FQN strings after JSON round-trip. Use TypeCatalogue.resolve() to get the Python type object."`

---

### D3 — Error Handling

**[G1-17] `_non_empty` validator strips whitespace but does not normalise — `"  "` becomes `"  "` after strip check**
The validator checks `if not v.strip()` but returns `v` unchanged. A value of `"  "` (all spaces) raises `ValueError` correctly. A value of `" clean "` (leading/trailing spaces) passes validation and is stored with the spaces intact. This may cause display issues in the UI.

**Severity:** 🔵 Low — D3
**File:** `nodes/metadata.py`
**Evidence:** `_non_empty` validator: `return v` (not `return v.strip()`)
**Proposed Fix:** Return `v.strip()` to normalise whitespace: `return v.strip()`

---

### D4 — Performance

No issues found. `NodeMetadata` is created once per node class at startup.

### D5 — Test Coverage Gaps

**[G1-18] No test for `version` validator with pre-release strings like `"1.0.0-beta.1+build.123"`**
The regex allows complex pre-release strings but this is not tested. A malformed string like `"1.0.0--"` may pass or fail unexpectedly.

**Severity:** 🔵 Low — D5
**File:** `nodes/metadata.py`
**Proposed Fix:** Add parametrised tests for valid (`"1.0.0"`, `"2.1"`, `"1.0.0-beta"`) and invalid (`"not-a-version"`, `""`, `"1.0.0--"`) version strings.

---

### D6 — Security

No issues found.

### D7 — Documentation

**[G1-19] `memory_requirements` field has no validation — accepts arbitrary strings**
`memory_requirements: str | None = None` accepts `"512MB"`, `"2GB"`, or `"banana"` equally. The docstring says `"e.g. '512MB', '2GB'"` but no validator enforces this format. Downstream code that parses this string (e.g. a scheduler) will fail silently on malformed values.

**Severity:** 🟡 Medium — D7 / D1
**File:** `nodes/metadata.py`
**Proposed Fix:** Add a validator: `r"^\d+(\.\d+)?\s*(B|KB|MB|GB|TB)$"` or document that the field is a free-form hint with no guaranteed format.

---

### D8 — Convention Adherence

No issues found. `from __future__ import annotations` is present; `field_validator` usage is correct.


---

## File 5 — `nodes/retry.py`

### D1 — Code Quality & Correctness

**[G1-20] `wait_before_attempt(0)` always returns `0.0` when `backoff_seconds=0.0` regardless of multiplier**
With the default `backoff_seconds=0.0`, `wait_before_attempt(i)` returns `0.0 * multiplier^i = 0.0` for all `i`. This is mathematically correct but means a `RetryPolicy(max_attempts=3, backoff_multiplier=2.0)` with no `backoff_seconds` set produces zero wait — which may surprise users who set a multiplier expecting some delay.

**Severity:** 🔵 Low — D1 / D7
**File:** `nodes/retry.py`
**Evidence:** `wait_before_attempt` formula; default `backoff_seconds=0.0`
**Proposed Fix:** Add a note to the class docstring: `"If backoff_seconds=0.0 (default), all waits are 0 regardless of backoff_multiplier."`

---

**[G1-21] `attempt_index` semantics are off-by-one relative to common retry libraries**
The docstring says `attempt_index=0` is "wait before the 2nd overall attempt (first retry)". Most retry libraries (tenacity, backoff) use `attempt_number` starting at 1 for the first attempt. The 0-indexed convention is valid but non-standard and may cause integration bugs when wrapping this class.

**Severity:** 🟡 Medium — D1 / D7
**File:** `nodes/retry.py`
**Evidence:** `wait_before_attempt` docstring
**Proposed Fix:** Add a warning: `"Note: attempt_index is 0-indexed (0 = first retry). This differs from tenacity/backoff which use 1-indexed attempt numbers."`

---

### D2 — Architecture & Design

No issues found. `RetryPolicy` is a clean, immutable value object. Pydantic `BaseModel` is appropriate.

### D3 — Error Handling

**[G1-22] No upper bound on `max_attempts` — unbounded retry loops possible**
`max_attempts` is validated to be `>= 1` but has no upper bound. A misconfigured node with `max_attempts=1000000` will retry indefinitely in practice. For a production pipeline this is a denial-of-service risk.

**Severity:** 🟡 Medium — D3 / D6
**File:** `nodes/retry.py`
**Evidence:** `_min_attempts` validator — only checks `v < 1`
**Proposed Fix:** Add an upper bound: `if v > 100: raise ValueError("max_attempts must be <= 100")` or make it configurable via a class variable.

---

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

**[G1-23] No test for `wait_before_attempt` with `backoff_multiplier=1.0` (constant backoff)**
With `multiplier=1.0`, all waits should equal `backoff_seconds`. This is a common use case (constant retry delay) that is not explicitly tested.

**Severity:** 🔵 Low — D5
**File:** `nodes/retry.py`
**Proposed Fix:** Add test: `RetryPolicy(max_attempts=3, backoff_seconds=2.0, backoff_multiplier=1.0)` — verify `wait_before_attempt(0) == wait_before_attempt(1) == 2.0`.

---

### D6 — Security

See G1-22 (unbounded `max_attempts`).

### D7 — Documentation

No issues found beyond those noted in G1-20 and G1-21.

### D8 — Convention Adherence

No issues found. `field_validator` with `@classmethod` is correct Pydantic v2 usage.


---

## File 6 — `nodes/registry.py`

### D1 — Code Quality & Correctness

**[G1-24] `find_compatible_nodes` acquires `_lock` per-node inside the loop — lock contention and TOCTOU**
```python
with self._lock:
    items = list(self._classes.items())   # snapshot
# ... loop without lock ...
for node_type, node_class in items:
    ...
    with self._lock:                       # re-acquires per result append
        result.append(self._metadata[node_type])
```
The snapshot of `_classes` is taken under the lock, but `_metadata` is accessed per-node inside the loop without holding the lock continuously. Between the snapshot and the per-node `_metadata` lookup, `unregister()` could remove the node, causing a `KeyError` on `self._metadata[node_type]`.

**Severity:** 🔴 Critical — D1 / D6
**File:** `nodes/registry.py`
**Evidence:** `find_compatible_nodes` method, lines ~80–100
**Proposed Fix:** Take a single snapshot of both dicts under one lock acquisition:
```python
with self._lock:
    items = list(self._classes.items())
    meta_snapshot = dict(self._metadata)
# ... loop without lock, use meta_snapshot.get(node_type) ...
```

---

**[G1-25] `get_config_schema` calls `node_class.Config.model_json_schema()` — `Config` may not exist**
If a `Node` subclass does not define an inner `Config` class, `node_class.Config` falls back to `Node.Config` (the empty base). This is correct. However, if a plugin node defines `Config` as a non-Pydantic class (e.g. a plain dataclass), `model_json_schema()` will raise `AttributeError` with no helpful error message.

**Severity:** 🟡 Medium — D3
**File:** `nodes/registry.py`
**Evidence:** `get_config_schema` method
**Proposed Fix:**
```python
def get_config_schema(self, node_type: str) -> dict[str, Any]:
    node_class = self.get_class(node_type)
    cfg = node_class.Config
    if not hasattr(cfg, "model_json_schema"):
        raise TypeError(f"Node '{node_type}'.Config is not a Pydantic model")
    return cfg.model_json_schema()
```

---

### D2 — Architecture & Design

**N-10 verdict (find_compatible_nodes O(N×M)):** See Open Items section below.

**[G1-26] `from_json` deprecated alias is a `@staticmethod` on `NodeRegistry` — breaks if subclassed**
`from_json` delegates to `parse_metadata_list` via `NodeRegistry.parse_metadata_list(json_str)`. If `NodeRegistry` is subclassed and `parse_metadata_list` is overridden, `from_json` will still call the base class version. This is a minor LSP violation.

**Severity:** 🔵 Low — D2
**File:** `nodes/registry.py`
**Evidence:** `from_json` static method
**Proposed Fix:** Change to `return cls.parse_metadata_list(json_str)` — but since it's a `@staticmethod`, `cls` is not available. Either make it a `@classmethod` or document the limitation.

---

### D3 — Error Handling

See G1-24 (TOCTOU `KeyError`) and G1-25 (missing `model_json_schema`).

### D4 — Performance

**[G1-27] `list_nodes` copies all metadata on every call — no pagination**
`list_nodes()` returns `list(self._metadata.values())` — a full copy of all metadata. With hundreds of registered nodes, this is a non-trivial allocation on every API call. No pagination or lazy iteration is provided.

**Severity:** 🟡 Medium — D4
**File:** `nodes/registry.py`
**Evidence:** `list_nodes` method
**Proposed Fix:** For the current 29-node scale this is fine. Add a `TODO` comment noting that pagination should be added when node count exceeds ~500.

---

### D5 — Test Coverage Gaps

**[G1-28] No test for concurrent `register` + `find_compatible_nodes` race**
The thread-safety fix (N-08) added `_lock`, but there is no concurrent test verifying that simultaneous `register` and `find_compatible_nodes` calls do not produce `KeyError` or stale results.

**Severity:** 🟡 Medium — D5
**File:** `nodes/registry.py`
**Proposed Fix:** Add a threading test using `concurrent.futures.ThreadPoolExecutor` that registers nodes while `find_compatible_nodes` runs concurrently.

---

### D6 — Security

See G1-24 (TOCTOU race condition).

### D7 — Documentation

**[G1-29] `to_json` / `parse_metadata_list` round-trip is lossy — not documented**
`to_json` serialises `NodeMetadata` to JSON. `parse_metadata_list` reconstructs `NodeMetadata` objects. However, the reconstructed objects have `input_ports`/`output_ports` with `data_type` as FQN strings, not Python types. The docstring does not warn about this.

**Severity:** 🟡 Medium — D7
**File:** `nodes/registry.py`
**Proposed Fix:** Add to `to_json` docstring: `"Note: data_type fields in port dicts are serialised as FQN strings. Use TypeCatalogue.resolve() to recover Python type objects after deserialisation."`

---

### D8 — Convention Adherence

No issues found. `threading.RLock` usage is correct; `__contains__` and `__len__` are properly implemented.


---

## File 7 — `nodes/discovery.py`

### D1 — Code Quality & Correctness

**N-11 verdict (plugin module name collision):** See Open Items section below.

**[G1-30] `_register_node` mutates `meta.input_ports` / `meta.output_ports` in-place on the ClassVar**
```python
if not meta.input_ports:
    meta.input_ports = {k: _port_to_dict(v) for k, v in cls.input_ports.items()}
```
`meta` is `cls.metadata` — a `ClassVar` shared across all instances of the node class. Mutating it in-place means that if `_register_node` is called twice for the same class (e.g. during a hot-reload), the second call sees `meta.input_ports` already populated and skips the update. This is the intended guard (`if not meta.input_ports`), but it also means that if `cls.input_ports` changes between calls (e.g. during testing), the stale port dict is never refreshed.

**Severity:** 🟡 Medium — D1
**File:** `nodes/discovery.py`
**Evidence:** `_register_node` lines: `if not meta.input_ports: meta.input_ports = ...`
**Proposed Fix:** Document that `metadata.input_ports` is populated once and is not refreshed on re-registration. Add a comment explaining the guard.

---

**[G1-31] `_pascal_to_snake` produces incorrect output for all-uppercase class names**
`_PASCAL_RE1` handles `TFLite → TF_Lite` correctly. But a class named `FFTNode` produces:
- Pass 1: `FFT_Node` (correct)
- Pass 2: no change (no lowercase-to-uppercase boundary)
- After strip: `fft`

A class named `FFTProcessorNode`:
- Pass 1: `FFT_ProcessorNode` → `FFT_Processor_Node`
- Pass 2: no change
- After strip: `fft_processor`

This is correct. However, a class named `IONode`:
- Pass 1: `I_ONode` (incorrect — `IO` is split as `I_O`)
- After strip: `i_o`

Expected: `io`. The regex `([A-Z]+)([A-Z][a-z])` matches `IO` as `I` + `On` → `I_On` which is wrong.

**Severity:** 🟡 Medium — D1
**File:** `nodes/discovery.py`
**Evidence:** `_pascal_to_snake("IONode")` → `"i_o"` instead of `"io"`
**Proposed Fix:** Add `IONode` to the docstring examples and either accept the current behaviour or add a special-case for 2-letter acronyms. Alternatively, use a well-tested library like `inflection.underscore()`.

---

### D2 — Architecture & Design

**[G1-32] `AutoDiscovery` imports `PluginLoader` inside a loop — repeated import overhead**
```python
from app.core.plugins.loader import PluginLoader  # noqa: PLC0415
loader = PluginLoader(self._registry)
loader.load(subdir)
```
This import is inside the `for subdir in sorted(plugins_path.iterdir())` loop. Python caches module imports, so the overhead is minimal after the first call, but the pattern is non-idiomatic and triggers the `PLC0415` lint warning (import not at top of file).

**Severity:** 🔵 Low — D2 / D8
**File:** `nodes/discovery.py`
**Evidence:** `run()` method, plugin subdirectory loop
**Proposed Fix:** Move the import to the top of the `run()` method (before the loop) or to the module level under `TYPE_CHECKING`.

---

### D3 — Error Handling

**[G1-33] `_scan_directory` catches all `Exception` for `_process_module` — masks `KeyboardInterrupt` and `SystemExit`**
```python
except Exception as exc:
    log.warning("AutoDiscovery: error processing module '%s': %s", ...)
```
`Exception` does not catch `KeyboardInterrupt` or `SystemExit` (they inherit from `BaseException`), so this is technically correct. However, catching bare `Exception` for module processing means that `MemoryError`, `RecursionError`, and other fatal errors are silently logged and skipped. These should propagate.

**Severity:** 🟡 Medium — D3
**File:** `nodes/discovery.py`
**Evidence:** `_scan_directory` final `except Exception` block
**Proposed Fix:** Narrow the catch to expected errors: `except (ImportError, AttributeError, TypeError, ValueError) as exc:` and let unexpected errors propagate.

---

### D4 — Performance

**[G1-34] `sorted(directory.glob("*.py"))` materialises the full file list before iteration**
`glob("*.py")` returns a generator; wrapping it in `sorted()` forces full materialisation. For large plugin directories with hundreds of files, this is a non-trivial memory allocation. For the current scale (< 50 files per directory) this is fine.

**Severity:** 🔵 Low — D4
**File:** `nodes/discovery.py`
**Evidence:** `_scan_directory`: `for py_file in sorted(directory.glob("*.py"))`
**Proposed Fix:** Add a `TODO` comment for future optimisation if plugin directories grow large.

---

### D5 — Test Coverage Gaps

**[G1-35] No test for `_pascal_to_snake` with edge cases: single-letter names, all-caps, numbers**
The docstring shows 6 examples but does not cover: `"A"`, `"ABCNode"`, `"Node123"`, `"MP3Node"`.

**Severity:** 🟡 Medium — D5
**File:** `nodes/discovery.py`
**Proposed Fix:** Add parametrised tests for all documented examples plus edge cases.

---

### D6 — Security

**[G1-36] `_import_file` with `package_prefix=None` executes arbitrary Python files from the filesystem**
Plugin files loaded via `spec_from_file_location` execute arbitrary code. There is no sandboxing, signature verification, or checksum validation. A malicious plugin file placed in the plugins directory will be executed with full process privileges.

**Severity:** 🟠 High — D6
**File:** `nodes/discovery.py`
**Evidence:** `_import_file` with `package_prefix=None`: `spec.loader.exec_module(module)`
**Proposed Fix:** This is a known limitation of Python plugin systems. Document it explicitly: `"Warning: plugin files are executed with full process privileges. Only load plugins from trusted sources."` Consider adding a manifest signature check in `PluginLoader`.

---

### D7 — Documentation

**[G1-37] `_PLUGINS_DIR_DEFAULT` sentinel is not documented — confusing for contributors**
`_PLUGINS_DIR_DEFAULT = object()` is used as a sentinel to distinguish "not passed" from `None`. This pattern is valid but unusual. The `run()` docstring explains it, but the sentinel itself has no comment.

**Severity:** 🔵 Low — D7
**File:** `nodes/discovery.py`
**Evidence:** `_PLUGINS_DIR_DEFAULT = object()` line
**Proposed Fix:** Add comment: `# Sentinel: distinguishes "not passed" (use config default) from None (skip scan).`

---

### D8 — Convention Adherence

No issues found. `from __future__ import annotations` is present; `TYPE_CHECKING` guard is used correctly.


---

## File 8 — `nodes/catalogue.py`

### D1 — Code Quality & Correctness

No issues found. `register`, `resolve`, `list_types`, and `__contains__` are all correct.

### D2 — Architecture & Design

**[G1-38] `TypeCatalogue` has no thread safety — concurrent plugin installs can corrupt `_types`**
`TypeCatalogue.register()` and `resolve()` mutate and read `self._types` without a lock. `NodeRegistry` has `_lock` but `TypeCatalogue` (accessed via `registry.type_catalogue`) does not. Concurrent plugin installs that call `type_catalogue.register()` from different threads can cause `RuntimeError: dictionary changed size during iteration` or silent key overwrites.

**Severity:** 🔴 Critical — D2 / D6
**File:** `nodes/catalogue.py`
**Evidence:** `TypeCatalogue.__init__` — no lock; `register()` and `resolve()` — no lock
**Proposed Fix:**
```python
import threading

class TypeCatalogue:
    def __init__(self) -> None:
        self._types: dict[str, type] = {}
        self._lock = threading.RLock()

    def register(self, type_class: type) -> None:
        with self._lock:
            ...

    def resolve(self, type_name: str) -> type:
        with self._lock:
            ...
```

---

### D3 — Error Handling

**[G1-39] `resolve()` error message lists all registered types — can be very long in production**
```python
raise PortTypeNotFoundError(
    f"Port type '{type_name}' is not registered in TypeCatalogue. "
    f"Registered types: {sorted(self._types)}"
)
```
With hundreds of registered types, this error message can be kilobytes long, flooding logs and making the actual error harder to find.

**Severity:** 🟡 Medium — D3
**File:** `nodes/catalogue.py`
**Evidence:** `resolve()` error message
**Proposed Fix:** Truncate the list: `f"Registered types (first 20): {sorted(self._types)[:20]}"`

---

### D4 — Performance

**N-10 verdict (find_compatible_nodes O(N×M)):** `TypeCatalogue` itself does not implement `find_compatible_nodes` — that lives in `NodeRegistry`. See Open Items section.

No performance issues in `TypeCatalogue` itself.

### D5 — Test Coverage Gaps

**[G1-40] No test for `register()` with a non-`PortDataType` subclass**
The `TypeError` path (`if not (isinstance(type_class, type) and issubclass(type_class, PortDataType))`) is not tested.

**Severity:** 🔵 Low — D5
**File:** `nodes/catalogue.py`
**Proposed Fix:** Add test: `catalogue.register(str)` → verify `TypeError` is raised.

---

### D6 — Security

See G1-38 (thread safety).

### D7 — Documentation

No issues found. The class docstring is clear and accurate.

### D8 — Convention Adherence

No issues found.


---

## File 9 — `nodes/compat.py`

### D1 — Code Quality & Correctness

**[G1-41] Rule 4b (`out_origin is Union, in_origin is None`) is overly strict**
```python
if out_origin is Union and in_origin is None:
    return all(
        CompatibilityChecker.are_compatible(oa, input_type)
        for oa in get_args(output_type)
    )
```
This requires ALL union members to be compatible with `input_type`. But `Union[AudioSample, None]` (i.e. `Optional[AudioSample]`) should be compatible with `AudioSample` input only if the pipeline guarantees non-None values. The current rule rejects `Optional[AudioSample] → AudioSample` because `NoneType` is not compatible with `AudioSample`. This is arguably correct (strict typing), but it means optional outputs cannot connect to required inputs without an explicit unwrap node. This should be documented as a design decision.

**Severity:** 🟡 Medium — D1 / D7
**File:** `nodes/compat.py`
**Evidence:** Rule 4b in `are_compatible`
**Proposed Fix:** Document the design decision: `"Optional[X] output is NOT compatible with X input — use an explicit null-check node to unwrap Optional values."`

---

**[G1-42] `_type_to_schema` does not handle `Union` / `Optional` types**
`get_origin(Optional[str])` returns `Union`. The function has no `Union` branch, so it falls through to the `_BUILTIN_TYPE_MAP` check (fails) and then to the fallback `{"type": "object", "title": "Optional[str]"}`. This is not valid JSON Schema for an optional string.

**Severity:** 🟠 High — D1
**File:** `nodes/compat.py`
**Evidence:** `_type_to_schema` — no `Union` / `Optional` branch
**Proposed Fix:**
```python
if origin is Union:
    args = [a for a in get_args(t) if a is not type(None)]
    if len(args) == 1:
        schema = _type_to_schema(args[0])
        return {**schema, "nullable": True} if schema else {"nullable": True}
    return {"oneOf": [_type_to_schema(a) for a in args if a is not type(None)]}
```

---

### D2 — Architecture & Design

**[G1-43] `check_connection` accepts node instances but `are_compatible` accepts types — inconsistent API**
`check_connection(src_node, src_port, dst_node, dst_port)` takes node *instances* and extracts `output_ports[src_port].data_type`. `are_compatible(output_type, input_type)` takes *types*. The API surface is inconsistent — callers working with node classes (not instances) must instantiate nodes just to call `check_connection`.

**Severity:** 🟡 Medium — D2
**File:** `nodes/compat.py`
**Evidence:** `check_connection` signature vs `are_compatible` signature
**Proposed Fix:** Add an overload or a class-level variant: `check_connection_classes(src_class, src_port, dst_class, dst_port)`.

---

### D3 — Error Handling

**[G1-44] `check_connection` error message for missing port does not show available ports for `dst_node`**
The error for a missing output port shows `list(src_node.output_ports)`, but the error for a missing input port shows `list(dst_node.input_ports)`. Both are correct. However, the error message format is inconsistent — one says "has no output port" and the other says "has no input port" but both use the same template. This is fine.

**No issue** — error messages are clear and consistent.

### D4 — Performance

No issues found. `are_compatible` is called at pipeline build time, not at execution time.

### D5 — Test Coverage Gaps

**[G1-45] No test for `are_compatible` with `tuple` generic types**
`_type_to_schema` handles `tuple` but `are_compatible` has no `tuple` branch. `get_origin(tuple[int, str])` returns `tuple`, which falls through to Rule 4 (generic alias comparison). This works correctly but is not tested.

**Severity:** 🔵 Low — D5
**File:** `nodes/compat.py`
**Proposed Fix:** Add test: `are_compatible(tuple[int, str], tuple[int, str])` → `True`; `are_compatible(tuple[int, str], tuple[str, int])` → `False`.

---

### D6 — Security

No issues found.

### D7 — Documentation

**[G1-46] `are_compatible` docstring does not document Rules 3b, 3c, 3d (added since first pass)**
The docstring lists Rules 1–4 but Rules 3b (`list` plain input), 3c (`object` universal sink), and 3d (`object` universal source) are not documented. These are important for understanding why `object`-typed ports accept anything.

**Severity:** 🟡 Medium — D7
**File:** `nodes/compat.py`
**Evidence:** `are_compatible` docstring — only lists 4 rules
**Proposed Fix:** Add Rules 3b–3d to the docstring.

---

### D8 — Convention Adherence

No issues found.


---

## File 10 — `nodes/errors.py`

### D1 — Code Quality & Correctness

No issues found. All exception classes are correctly defined.

### D2 — Architecture & Design

**[G1-47] `PipelineGraphError` is in `nodes/errors.py` but is a pipeline-level concern**
`PipelineGraphError` is raised for "invalid pipeline graph structure (cycles, missing ports, etc.)" — this is a pipeline executor concern, not a node system concern. Placing it in `nodes/errors.py` creates a coupling between the node system and the pipeline layer. If the pipeline module is ever separated, this error class will need to move.

**Severity:** 🟡 Medium — D2
**File:** `nodes/errors.py`
**Evidence:** `PipelineGraphError` class
**Proposed Fix:** Move `PipelineGraphError` to `app/core/pipeline_errors.py` or `app/core/ir/errors.py` and import it from there in `nodes/errors.py` for backward compatibility.

---

### D3 — Error Handling

**[G1-48] No `__init__` with structured fields on any exception — all errors are string-only**
All exceptions accept only a string message. For programmatic error handling (e.g. the API returning structured error responses), callers must parse the string. `NodeNotFoundError` should carry `node_type: str` as a structured field; `DuplicateNodeTypeError` should carry `existing_class` and `new_class`.

**Severity:** 🟡 Medium — D3
**File:** `nodes/errors.py`
**Evidence:** All exception classes — no `__init__` with structured fields
**Proposed Fix:**
```python
class NodeNotFoundError(NodeSystemError):
    def __init__(self, node_type: str, registered: list[str] | None = None):
        self.node_type = node_type
        self.registered = registered or []
        super().__init__(f"Node type '{node_type}' is not registered.")
```

---

### D4 — Performance

No issues found.

### D5 — Test Coverage Gaps

**[G1-49] No test verifying the full exception hierarchy (`isinstance` checks)**
There is no test confirming that `NodeNotFoundError` is a `NodeSystemError`, etc. If the hierarchy is accidentally broken (e.g. by a copy-paste error), callers catching `NodeSystemError` would miss specific subclasses.

**Severity:** 🔵 Low — D5
**File:** `nodes/errors.py`
**Proposed Fix:** Add a test: `assert issubclass(NodeNotFoundError, NodeSystemError)` for all subclasses.

---

### D6 — Security

No issues found.

### D7 — Documentation

**[G1-50] `NodeTypeError` docstring says "incompatible port types" but it is also raised for missing ports**
`CompatibilityChecker.check_connection` raises `NodeTypeError` for both "port does not exist" and "types are incompatible". The docstring only mentions the latter.

**Severity:** 🔵 Low — D7
**File:** `nodes/errors.py`
**Evidence:** `NodeTypeError` docstring; `check_connection` raises it for missing ports too
**Proposed Fix:** Update docstring: `"Raised when a port does not exist or when an output port type is incompatible with an input port type."`

---

### D8 — Convention Adherence

No issues found.


---

## File 11 — `nodes/observers.py`

### D1 — Code Quality & Correctness

**[G1-51] `LoggingObserver.on_node_error` logs at `ERROR` level but does not include the traceback**
```python
self._log.error(json.dumps({
    "event": "node_error",
    "error": str(exc),
    "error_type": type(exc).__name__,
}))
```
`str(exc)` captures the exception message but not the traceback. In production, the traceback is essential for debugging. The `LoggingObserver` should log `exc_info=True` or include the formatted traceback in the JSON payload.

**Severity:** 🟠 High — D1 / D3
**File:** `nodes/observers.py`
**Evidence:** `on_node_error` in `LoggingObserver`
**Proposed Fix:**
```python
import traceback as _traceback

def on_node_error(self, node_type: str, run_id: str, exc: Exception) -> None:
    self._log.error(json.dumps({
        "event": "node_error",
        "node_type": node_type,
        "run_id": run_id,
        "error": str(exc),
        "error_type": type(exc).__name__,
        "traceback": _traceback.format_exc(),
    }))
```

---

**[G1-52] `CompositeObserver` warning log does not include the observer's repr in a useful way**
```python
self._log.warning(
    "CompositeObserver: %r raised in on_node_start for node '%s'",
    obs, node_type, exc_info=True,
)
```
`%r` on an observer object produces something like `<LoggingObserver object at 0x...>` which is not useful for identifying which observer failed. If observers implement `__repr__`, this is fine; if not, the log is unhelpful.

**Severity:** 🔵 Low — D7
**File:** `nodes/observers.py`
**Evidence:** `CompositeObserver` warning log format
**Proposed Fix:** Recommend that `NodeObserver` subclasses implement `__repr__`. Add a note to the `NodeObserver` docstring.

---

### D2 — Architecture & Design

**[G1-53] `NodeObserver` is an ABC but `CompositeObserver` is a concrete class — no interface for "no-op" observer**
There is no `NullObserver` or no-op implementation. Code that conditionally uses an observer must check `if self.observer is not None` before calling methods. A `NullObserver` would simplify this pattern.

**Severity:** 🟡 Medium — D2
**File:** `nodes/observers.py`
**Proposed Fix:**
```python
class NullObserver(NodeObserver):
    """No-op observer — discards all events."""
    def on_node_start(self, node_type, run_id): pass
    def on_node_end(self, node_type, run_id, duration_s, input_counts, output_counts): pass
    def on_node_error(self, node_type, run_id, exc): pass
```

---

### D3 — Error Handling

See G1-51 (missing traceback in `on_node_error`).

**[G1-54] `CompositeObserver` catches `Exception` in `on_node_error` — can mask the original exception**
If an observer's `on_node_error` raises, the `CompositeObserver` logs a warning. But the original `exc` passed to `on_node_error` is still available to the caller. This is correct — the `CompositeObserver` does not swallow the original exception. No issue.

**No issue** — the design is correct.

### D4 — Performance

No issues found. Observer calls are synchronous and lightweight.

### D5 — Test Coverage Gaps

**[G1-55] No test for `CompositeObserver` with a failing child observer**
The N-15 fix added try/except isolation, but there is no test verifying that a failing observer does not prevent subsequent observers from receiving events.

**Severity:** 🟡 Medium — D5
**File:** `nodes/observers.py`
**Proposed Fix:** Add test: `CompositeObserver([FailingObserver(), LoggingObserver()])` — verify `LoggingObserver` still receives events after `FailingObserver` raises.

---

### D6 — Security

No issues found.

### D7 — Documentation

**[G1-56] `NodeObserver` docstring says "node_type: The class name" but it should be the `node_type` string**
The `on_node_start` docstring says `"node_type: The class name of the node being executed."` But in practice, the pipeline executor passes `type(node).__name__` or `node.node_type` — these may differ (e.g. `CleanNode` vs `"clean"`). The docstring should clarify which value is passed.

**Severity:** 🟡 Medium — D7
**File:** `nodes/observers.py`
**Evidence:** `on_node_start` docstring: `"node_type: The class name of the node being executed."`
**Proposed Fix:** Clarify: `"node_type: The node_type string (e.g. 'clean'), not the class name (e.g. 'CleanNode')."`

---

### D8 — Convention Adherence

No issues found. `ABC` and `@abstractmethod` usage is correct.


---

## File 12 — `nodes/__init__.py`

### D1 — Code Quality & Correctness

**[G1-57] `_models_dir` path construction assumes a fixed directory layout**
```python
_models_dir = Path(__file__).parent.parent.parent / "models"
```
This resolves to `app/models/` relative to `app/core/nodes/__init__.py`. If the package is installed (e.g. via `pip install -e .`) or if the directory structure changes, this path will silently point to a non-existent directory. `AutoDiscovery.run()` checks `models_path.exists()` before scanning, so it fails silently rather than raising an error.

**Severity:** 🟡 Medium — D1
**File:** `nodes/__init__.py`
**Evidence:** `_models_dir = Path(__file__).parent.parent.parent / "models"`
**Proposed Fix:** Use a config-driven path or an environment variable: `_models_dir = Path(os.environ.get("GRAPHYN_MODELS_DIR", Path(__file__).parent.parent.parent / "models"))`. Add a `DEBUG`-level log if the directory does not exist.

---

### D2 — Architecture & Design

**[G1-58] Module-level side effects at import time violate the principle of least surprise**
Importing `app.core.nodes` triggers:
1. `PluginManager().load_enabled_plugins()` — filesystem I/O, potential network calls
2. `AutoDiscovery.run()` — filesystem scanning, module imports

Any module that does `from app.core.nodes import Node` pays this full startup cost. This makes the module unsuitable for use in lightweight scripts, CLI tools that don't need the full registry, or test files that only need the `Node` base class.

**Severity:** 🟠 High — D2
**File:** `nodes/__init__.py`
**Evidence:** Module-level `PluginManager().load_enabled_plugins()` and `AutoDiscovery(registry).run(...)` calls
**Proposed Fix:** The `GRAPHYN_SKIP_PLUGIN_LOAD` env var provides test isolation (N-16 fix), but a lazy-init pattern would be cleaner:
```python
_initialized = False

def initialize() -> None:
    global _initialized
    if _initialized:
        return
    # ... run discovery ...
    _initialized = True
```
This is a larger refactor; document the current behaviour clearly in the module docstring.

---

### D3 — Error Handling

**[G1-59] `AutoDiscovery(registry).run(...)` at module level — any unhandled exception aborts the entire import**
If `AutoDiscovery.run()` raises an unhandled exception (e.g. `DuplicateNodeTypeError` from a malformed plugin), the entire `app.core.nodes` import fails. This means the API server, CLI, and SDK all fail to start with a cryptic `ImportError`. The error message will reference `app/core/nodes/__init__.py` rather than the offending plugin file.

**Severity:** 🟠 High — D3
**File:** `nodes/__init__.py`
**Evidence:** `AutoDiscovery(registry).run(...)` — no try/except wrapper
**Proposed Fix:** Wrap in a try/except that logs the error and re-raises with a more helpful message:
```python
try:
    AutoDiscovery(registry).run(...)
except Exception as exc:
    _log.critical("AutoDiscovery failed during startup: %s", exc, exc_info=True)
    raise ImportError(
        f"app.core.nodes failed to initialise: {exc}. "
        "Check plugin files for duplicate node_type declarations."
    ) from exc
```

---

### D4 — Performance

**[G1-60] `PluginManager()` is instantiated with no arguments — may re-read config on every import**
`PluginManager()` is called at module level. If `PluginManager.__init__` reads config files or environment variables, this happens on every fresh import (e.g. in a subprocess). This is acceptable for a singleton pattern but should be documented.

**Severity:** 🔵 Low — D4
**File:** `nodes/__init__.py`
**Evidence:** `PluginManager().load_enabled_plugins()` — new instance created each time
**Proposed Fix:** Document that `PluginManager` is instantiated once at startup and that subsequent imports use the cached `registry` singleton.

---

### D5 — Test Coverage Gaps

**[G1-61] `GRAPHYN_SKIP_PLUGIN_LOAD` env var is not tested for all three values (`"1"`, `"true"`, `"yes"`)**
The env var check is:
```python
os.environ.get("GRAPHYN_SKIP_PLUGIN_LOAD", "").strip().lower() in ("1", "true", "yes")
```
All three values should be tested. Currently only `"1"` is likely tested (it's the most common).

**Severity:** 🔵 Low — D5
**File:** `nodes/__init__.py`
**Proposed Fix:** Add parametrised tests for `"1"`, `"true"`, `"yes"`, `"TRUE"`, `"YES"`, and `"0"` (should not skip).

---

### D6 — Security

No issues found beyond the plugin execution concern noted in G1-36.

### D7 — Documentation

**[G1-62] `__all__` lists `"Node"` but `Node` is imported after `__all__` is defined — ordering is confusing**
```python
__all__ = ["registry", "Node", "InputPort", ...]

# Re-export the full public API surface
from app.core.nodes.base import Node  # noqa: E402
```
`__all__` is defined before the imports that make those names available. This works correctly in Python (module-level `__all__` is evaluated at import time, not at definition time), but the ordering is confusing and the `# noqa: E402` suppression is a code smell.

**Severity:** 🔵 Low — D7 / D8
**File:** `nodes/__init__.py`
**Evidence:** `__all__` defined before the `from ... import` statements
**Proposed Fix:** Move the `from ... import` statements before `__all__`, or add a comment explaining why they are at the bottom.

---

### D8 — Convention Adherence

No issues found. `from __future__ import annotations` is present; `GRAPHYN_SKIP_PLUGIN_LOAD` follows the project's env var naming convention.


---

## OPEN ITEM VERDICTS

### N-04 — Is `setup()` enforced before `process()`?

**Verdict: DEFER**

**Evidence:**
- `Node.setup()` is a no-op method with a docstring stating "Called once before the first `on_start()`."
- `Node.__init__` does NOT call `setup()`.
- `Node.process()` does NOT check whether `setup()` has been called.
- There is no `_setup_done: bool` flag or any guard on `Node`.
- The pipeline executor (not reviewed in this group) is responsible for calling `setup()` before the first `process()` invocation.

**Analysis:** The first-pass finding (N-04) rated this 🔵 Low and suggested adding a `_setup_done` guard. The current code has not implemented this guard. The risk is real: any code that calls `node.process()` directly (unit tests, scripts, SDK users) will silently skip `setup()`. However, adding enforcement at the `Node` level would require either:
1. A `_setup_done` flag checked in `process()` — adds overhead to every process call.
2. A `setup_required` ClassVar — opt-in enforcement.

**Recommendation:** DEFER the enforcement guard to the pipeline executor layer. Add a clear warning to the `setup()` docstring and to `docs/NODE_SYSTEM.md` that direct `process()` calls bypass the lifecycle. The 🔵 Low severity from the first pass is confirmed — this is a documentation gap, not a runtime bug in normal pipeline execution.

---

### N-06 — Can `port.name` drift from its dict key?

**Verdict: OPEN — NOT FIXED**

**Evidence:**
- `InputPort` and `OutputPort` both have a `name: str` field.
- `Node.input_ports` is `ClassVar[dict[str, InputPort]]` where the dict key is the port name.
- There is no validator in `Node`, `InputPort`, `OutputPort`, or `AutoDiscovery` that checks `port.name == dict_key`.
- `AutoDiscovery._port_to_dict` uses `port.model_dump()` which includes `port.name` — but the dict key in `meta.input_ports` is set from `cls.input_ports.items()` (the dict key), not from `port.name`.
- Example of drift: `input_ports = {"audio": InputPort(name="sound", data_type=AudioSample)}` — the dict key is `"audio"` but `port.name` is `"sound"`. `_siso_process` uses `inputs.get("input")` (dict key), while serialised metadata uses `port.name` for display. These will disagree.

**Impact:** Medium — UI rendering and API responses will show the wrong port name. Pipeline connections that use the dict key will work, but any code that reads `port.name` for routing will use the wrong name.

**Proposed Fix:**
```python
# In Node.__init_subclass__ or in AutoDiscovery._register_node:
for key, port in cls.input_ports.items():
    if port.name != key:
        raise ValueError(
            f"Node '{cls.__name__}': input_ports key '{key}' does not match "
            f"port.name '{port.name}'. They must be identical."
        )
```

---

### N-10 — Is `find_compatible_nodes` still O(N×M)?

**Verdict: CONFIRMED O(N×M) — DEFER**

**Evidence:**
```python
def find_compatible_nodes(self, port_type, direction):
    with self._lock:
        items = list(self._classes.items())   # O(N) snapshot
    result = []
    for node_type, node_class in items:       # O(N) outer loop
        if direction == "input":
            ports = node_class.input_ports.values()
            if any(                            # O(M) inner loop
                CompatibilityChecker.are_compatible(port_type, p.data_type)
                for p in ports
            ):
```
With N registered nodes and M ports per node, this is O(N×M) per call. For the current 29-node registry with ~2 ports per node, this is O(58) — negligible. For a large plugin ecosystem with 500 nodes and 10 ports each, this is O(5000) per call.

**Analysis:** The first-pass finding (N-10) rated this 🟡 Medium. The fix (inverted index at registration time) would reduce lookup to O(1) amortised but adds complexity to `register()` and `unregister()`. At the current scale (29 nodes), the optimisation is premature.

**Recommendation:** DEFER. Add a `TODO` comment in `find_compatible_nodes` noting the O(N×M) complexity and the inverted-index optimisation path. Re-evaluate when node count exceeds 200.

---

### N-11 — Is plugin module name collision in `_import_file` fixed?

**Verdict: PARTIALLY FIXED — RESIDUAL RISK REMAINS**

**Evidence (current code):**
```python
def _import_file(self, path: Path, package_prefix: str | None):
    if package_prefix:
        module_name = f"{package_prefix}.{path.stem}"
        return importlib.import_module(module_name)
    else:
        parent = path.parent.name
        module_name = f"{parent}.{path.stem}" if parent else path.stem
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
```

**Analysis:**
- The first-pass finding (N-11) identified that two plugins with a file named `nodes.py` would collide on `sys.modules["<plugin>.nodes"]`.
- The current fix uses `f"{parent}.{path.stem}"` where `parent = path.parent.name` — the plugin directory name.
- **This fixes the case where two plugins have the same filename** (e.g. both have `nodes.py`) because the parent directory names differ (`audio_denoiser.nodes` vs `audio_classifier.nodes`).
- **Residual risk:** Two plugins with the same directory name AND the same filename will still collide. This can happen if a plugin is installed twice under different paths but with the same directory name. The `sys.modules[module_name] = module` line overwrites the first registration.
- **Additional risk:** The `_process_module` guard `obj.__module__ == module.__name__` relies on `module.__name__` being the `f"{parent}.{path.stem}"` string. If two plugins have the same parent directory name (e.g. both are named `audio_plugin`), their modules will have the same `__name__` and the guard will incorrectly filter classes from one plugin as belonging to the other.

**Verdict: PARTIALLY FIXED.** The common case (same filename, different plugin directories) is fixed. The edge case (same directory name across different install paths) is not fixed. The fix is adequate for the current plugin ecosystem where directory names are unique by convention.

**Recommended additional fix:** Use the full absolute path as the module name:
```python
module_name = str(path.resolve()).replace(os.sep, "_").replace(".", "_")
```
This guarantees uniqueness at the cost of less readable module names.


---

## SUMMARY TABLE

### All Findings by Severity

| ID | File | Severity | Dimension | Short Title |
|----|------|----------|-----------|-------------|
| G1-01 | `base.py` | 🟡 Medium | D1/D7 | SISO double-wrap guard comment missing |
| G1-02 | `base.py` | 🟠 High | D1 | `get_event_loop()` deprecated in Python 3.10+ |
| G1-03 | `base.py` | 🟠 High | D2/D7 | Observer stored but never called by Node |
| G1-04 | `base.py` | 🟡 Medium | D3 | SISO `inputs.get("input")` silently returns None |
| G1-05 | `base.py` | 🟡 Medium | D5 | No test for SISO re-subclassing double-wrap |
| G1-06 | `base.py` | 🟡 Medium | D7 | `setup()` docstring implies false enforcement contract |
| G1-07 | `ports.py` | — | — | *(No issue — validator is sound)* |
| G1-08 | `ports.py` | 🟡 Medium | D7 | `PortDataType` dual-role (type vs instance) undocumented |
| G1-09 | `ports.py` | 🟡 Medium | D5 | No test for `cardinality="multi"` + `required=False` |
| G1-10 | `ports.py` | 🔵 Low | D7 | `OutputPort` asymmetry (no `required`/`cardinality`) undocumented |
| G1-11 | `config.py` | 🔵 Low | D2/D7 | `populate_by_name=True` has no effect without aliases |
| G1-12 | `config.py` | 🟡 Medium | D5 | No test that `extra="forbid"` is inherited |
| G1-13 | `config.py` | 🔵 Low | D7 | Docstring example uses non-standard two-level inheritance |
| G1-14 | `metadata.py` | 🟡 Medium | D1/D7 | `_version_format` accepts single-digit versions |
| G1-16 | `metadata.py` | 🟡 Medium | D2/D7 | `input_ports` type loss after JSON round-trip undocumented |
| G1-17 | `metadata.py` | 🔵 Low | D3 | `_non_empty` validator does not strip whitespace |
| G1-18 | `metadata.py` | 🔵 Low | D5 | No test for pre-release version strings |
| G1-19 | `metadata.py` | 🟡 Medium | D7/D1 | `memory_requirements` accepts arbitrary strings |
| G1-20 | `retry.py` | 🔵 Low | D1/D7 | Zero `backoff_seconds` + non-zero multiplier produces zero wait |
| G1-21 | `retry.py` | 🟡 Medium | D1/D7 | `attempt_index` 0-indexed — non-standard, integration risk |
| G1-22 | `retry.py` | 🟡 Medium | D3/D6 | No upper bound on `max_attempts` |
| G1-23 | `retry.py` | 🔵 Low | D5 | No test for constant backoff (`multiplier=1.0`) |
| G1-24 | `registry.py` | 🔴 Critical | D1/D6 | TOCTOU `KeyError` in `find_compatible_nodes` |
| G1-25 | `registry.py` | 🟡 Medium | D3 | `get_config_schema` no guard for non-Pydantic `Config` |
| G1-26 | `registry.py` | 🔵 Low | D2 | `from_json` deprecated alias breaks LSP if subclassed |
| G1-27 | `registry.py` | 🟡 Medium | D4 | `list_nodes` full copy — no pagination |
| G1-28 | `registry.py` | 🟡 Medium | D5 | No concurrent test for `register` + `find_compatible_nodes` |
| G1-29 | `registry.py` | 🟡 Medium | D7 | `to_json`/`parse_metadata_list` round-trip lossiness undocumented |
| G1-30 | `discovery.py` | 🟡 Medium | D1 | `_register_node` mutates ClassVar `metadata` in-place |
| G1-31 | `discovery.py` | 🟡 Medium | D1 | `_pascal_to_snake` incorrect for 2-letter acronyms (`IONode`) |
| G1-32 | `discovery.py` | 🔵 Low | D2/D8 | `PluginLoader` import inside loop — non-idiomatic |
| G1-33 | `discovery.py` | 🟡 Medium | D3 | Bare `except Exception` masks fatal errors in `_scan_directory` |
| G1-34 | `discovery.py` | 🔵 Low | D4 | `sorted(glob(...))` materialises full file list |
| G1-35 | `discovery.py` | 🟡 Medium | D5 | No test for `_pascal_to_snake` edge cases |
| G1-36 | `discovery.py` | 🟠 High | D6 | Plugin files executed with full process privileges — no sandboxing |
| G1-37 | `discovery.py` | 🔵 Low | D7 | `_PLUGINS_DIR_DEFAULT` sentinel undocumented |
| G1-38 | `catalogue.py` | 🔴 Critical | D2/D6 | `TypeCatalogue` has no thread safety |
| G1-39 | `catalogue.py` | 🟡 Medium | D3 | `resolve()` error message can be very long |
| G1-40 | `catalogue.py` | 🔵 Low | D5 | No test for `register()` with non-`PortDataType` class |
| G1-41 | `compat.py` | 🟡 Medium | D1/D7 | `Optional[X] → X` rejected — design decision undocumented |
| G1-42 | `compat.py` | 🟠 High | D1 | `_type_to_schema` does not handle `Union`/`Optional` |
| G1-43 | `compat.py` | 🟡 Medium | D2 | `check_connection` takes instances; `are_compatible` takes types |
| G1-45 | `compat.py` | 🔵 Low | D5 | No test for `are_compatible` with `tuple` generics |
| G1-46 | `compat.py` | 🟡 Medium | D7 | `are_compatible` docstring missing Rules 3b–3d |
| G1-47 | `errors.py` | 🟡 Medium | D2 | `PipelineGraphError` belongs in pipeline layer, not node layer |
| G1-48 | `errors.py` | 🟡 Medium | D3 | All exceptions are string-only — no structured fields |
| G1-49 | `errors.py` | 🔵 Low | D5 | No test for exception hierarchy (`isinstance` checks) |
| G1-50 | `errors.py` | 🔵 Low | D7 | `NodeTypeError` docstring incomplete |
| G1-51 | `observers.py` | 🟠 High | D1/D3 | `LoggingObserver.on_node_error` missing traceback |
| G1-52 | `observers.py` | 🔵 Low | D7 | `CompositeObserver` warning log unhelpful without `__repr__` |
| G1-53 | `observers.py` | 🟡 Medium | D2 | No `NullObserver` — callers must check `observer is not None` |
| G1-55 | `observers.py` | 🟡 Medium | D5 | No test for `CompositeObserver` with failing child |
| G1-56 | `observers.py` | 🟡 Medium | D7 | `NodeObserver` docstring says "class name" but should say "node_type string" |
| G1-57 | `__init__.py` | 🟡 Medium | D1 | `_models_dir` hardcoded path — breaks on package install |
| G1-58 | `__init__.py` | 🟠 High | D2 | Module-level side effects at import time |
| G1-59 | `__init__.py` | 🟠 High | D3 | Unhandled `AutoDiscovery` exception aborts entire import |
| G1-60 | `__init__.py` | 🔵 Low | D4 | `PluginManager()` instantiated fresh — may re-read config |
| G1-61 | `__init__.py` | 🔵 Low | D5 | `GRAPHYN_SKIP_PLUGIN_LOAD` not tested for all valid values |
| G1-62 | `__init__.py` | 🔵 Low | D7/D8 | `__all__` defined before the imports it references |

---

### Totals by Severity

| Severity | Count |
|----------|-------|
| 🔴 Critical | 2 |
| 🟠 High | 7 |
| 🟡 Medium | 27 |
| 🔵 Low | 19 |
| **Total** | **55** |

### Totals by Dimension

| Dimension | Count |
|-----------|-------|
| D1 Code Quality & Correctness | 14 |
| D2 Architecture & Design | 9 |
| D3 Error Handling | 9 |
| D4 Performance | 3 |
| D5 Test Coverage Gaps | 12 |
| D6 Security | 5 |
| D7 Documentation | 18 |
| D8 Convention Adherence | 2 |

*(Many findings span multiple dimensions; counts reflect primary dimension.)*

---

### Open Item Disposition

| Item | Description | Verdict |
|------|-------------|---------|
| N-04 | `setup()` enforced before `process()`? | **DEFER** — document the gap; enforcement belongs in the executor |
| N-06 | `port.name` can drift from dict key? | **OPEN / NOT FIXED** — no validator exists; add one in `__init_subclass__` |
| N-10 | `find_compatible_nodes` O(N×M)? | **CONFIRMED O(N×M) — DEFER** — acceptable at current scale (29 nodes) |
| N-11 | Plugin module name collision fixed? | **PARTIALLY FIXED** — common case fixed; same-directory-name edge case remains |

---

*End of report.*
