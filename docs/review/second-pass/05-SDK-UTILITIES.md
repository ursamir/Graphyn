# G5 SDK & Utilities — Second-Pass Deep Review

**Module group:** `app/core/` — SDK & Utilities  
**Reviewer:** Kiro AI  
**Date:** 2025-07-14  
**Files reviewed:** 4  
**Files:** `sdk.py`, `utils/hash.py`, `utils/__init__.py`, `__init__.py`

---

## PHASE 1 — EXPLORATION PLAN

| # | File | Stated Purpose | Key Review Questions |
|---|------|---------------|----------------------|
| 1 | `sdk.py` | Programmatic Python API for defining and running pipelines without the UI. Exposes `PipelineNode`, `Pipeline`, and `ArtifactCollection`. | Does `Pipeline.run()` correctly delegate to `run_with_manager()`? Is `_from_ir()` safe (bypasses `__init__`)? Is `_make_subscriber_logger` thread-safe? Does `ArtifactCollection.lineage()` create a new `ProvenanceStore` per call? Does the SDK expose all operations the REST API and CLI expose? Is `to_yaml()` safe against YAML injection? |
| 2 | `utils/hash.py` | Non-cryptographic stable hash using MD5 + JSON encoding to avoid separator-collision bugs. | Is the S-07 separator collision fix present? What exact encoding is used? Does `stable_hash("a", "b") != stable_hash("a|b")` hold? Is `usedforsecurity=False` present for FIPS compliance? Are `None` and `"None"` correctly distinguished? |
| 3 | `utils/__init__.py` | Public re-export surface for the `app.core.utils` package. | Is `__all__` complete? Are there any missing exports? Does the import trigger any side effects? |
| 4 | `__init__.py` | Lazy-loading package init for `app.core` — exports `ResumeError` without pulling in the full pipeline module at import time. | Is the lazy `__getattr__` pattern correct? Does it handle the `AttributeError` fallback correctly? Is `__all__` consistent with what `__getattr__` exposes? |

---

## PHASE 2 — PER-FILE FINDINGS

---

### File 1 — `sdk.py`

#### D1 — Code Quality & Correctness

**[G5-01] `ArtifactCollection.get()` checks `_raw` first, masking artifact lookup by `node_id`**

`get(key)` returns `self._raw[key]` if `key in self._raw`, otherwise falls back to artifact lookup by `node_id`. The `_raw` dict is keyed by node ID (e.g. `"clean_0"`). If a node ID happens to collide with a key that was also stored in `_raw` for a different purpose, the artifact lookup is silently bypassed. More critically, the docstring says the method "checks `_raw` first, then falls back to artifact lookup by `node_id`" — but this means `get("clean_0")` always returns the raw dict value, never an `ArtifactRecord`, even when the caller explicitly wants the artifact. The dual-purpose semantics are confusing and the priority order is not obvious to callers.

**Severity:** 🟡 Medium  
**Dimension:** D1 — Code Quality & Correctness  
**Evidence:** `sdk.py` `ArtifactCollection.get()` — `if key in self._raw: return self._raw[key]` before artifact lookup.  
**Proposed Fix:** Separate the two access patterns into distinct methods: keep `get(key)` for raw dict access only, and rename the artifact lookup to `get_artifact(node_id)`. Update the docstring to remove the dual-purpose claim.

---

**[G5-02] `Pipeline._from_ir()` creates `PipelineNode` shells via `object.__new__` — bypasses `__init__` and `_validate()`**

`_from_ir()` calls `PipelineNode.__new__(PipelineNode)` and manually sets `node_type`, `config`, and `_ir_node` without calling `_validate()`. This is intentional (the IR is already validated), but it means a `PipelineNode` created via `_from_ir()` has no guarantee that `node_type` is registered in the current runtime registry. If the pipeline was saved with a plugin that has since been uninstalled, `_from_ir()` silently creates a shell node that will crash at execution time rather than at load time.

**Severity:** 🟡 Medium  
**Dimension:** D1 — Code Quality & Correctness  
**Evidence:** `sdk.py` `Pipeline._from_ir()` lines: `pn = PipelineNode.__new__(PipelineNode)` — no `_validate()` call.  
**Proposed Fix:** Add an optional `validate: bool = False` parameter to `_from_ir()`. When `True`, call `pn._validate()` for each node. Default to `False` for the fast path. Document the trade-off in the docstring.


---

**[G5-03] `Pipeline.to_yaml()` uses `yaml.dump` without `allow_unicode=True` — non-ASCII node names are escaped**

`to_yaml()` calls `yaml.dump(config, f, sort_keys=False)` without `allow_unicode=True`. PyYAML defaults to ASCII-safe output, escaping non-ASCII characters as `\uXXXX` sequences. A pipeline with a description or node label containing non-ASCII characters (e.g. Japanese, Arabic) will produce a YAML file that is technically valid but unreadable. This is a minor correctness issue for international users.

**Severity:** 🔵 Low  
**Dimension:** D1 — Code Quality & Correctness  
**Evidence:** `sdk.py` `Pipeline.to_yaml()`: `yaml.dump(config, f, sort_keys=False)` — no `allow_unicode=True`.  
**Proposed Fix:** `yaml.dump(config, f, sort_keys=False, allow_unicode=True)`

---

#### D2 — Architecture & Design

**[G5-04] `ArtifactCollection.lineage()` instantiates a new `ProvenanceStore()` on every call**

`lineage()` calls `ProvenanceStore()` inside the method body. `ProvenanceStore.__init__` constructs the base path and creates directories. For a caller that calls `lineage()` in a loop (e.g. iterating over all artifacts), this creates N `ProvenanceStore` instances, each doing filesystem work. The `ProvenanceStore` is stateless (all state is on disk), so a single shared instance would be correct and more efficient.

**Severity:** 🟡 Medium  
**Dimension:** D2 — Architecture & Design  
**Evidence:** `sdk.py` `ArtifactCollection.lineage()`: `store = ProvenanceStore()` — new instance per call.  
**Proposed Fix:** Cache the `ProvenanceStore` as a module-level singleton (matching the pattern used by `ArtifactStore` in `run_manager.py`), or accept it as a constructor parameter for testability.

---

**[G5-05] `_SubscriberLoggerClass` global is not thread-safe for concurrent first-use initialisation**

`_SubscriberLoggerClass` is a module-level global initialised to `None` and lazily set by `_make_subscriber_logger`. The check-then-set pattern (`if _SubscriberLoggerClass is None: _SubscriberLoggerClass = ...`) is not atomic. Two threads calling `_make_subscriber_logger` simultaneously for the first time could both see `None` and both call `_make_subscriber_logger_class()`, creating two different class objects. The second assignment wins, but any `_SubscriberLogger` instances created from the first class object will not be `isinstance` of the final class. In practice this is benign (both classes are functionally identical), but it is a latent correctness issue.

**Severity:** 🟡 Medium  
**Dimension:** D2 — Architecture & Design  
**Evidence:** `sdk.py` lines: `global _SubscriberLoggerClass; if _SubscriberLoggerClass is None: _SubscriberLoggerClass = _make_subscriber_logger_class()`  
**Proposed Fix:** Use a module-level `threading.Lock` to protect the lazy initialisation, or use `functools.lru_cache` on `_make_subscriber_logger_class` (which is thread-safe in CPython 3.2+).


---

#### D3 — Error Handling

**[G5-06] `PipelineNode._validate()` catches bare `Exception` for registry lookup — masks unexpected errors**

In `_validate()`, the `try/except Exception` block around `registry.get_class(self.node_type)` catches all exceptions and re-raises as `ValueError`. This means a `MemoryError`, `RecursionError`, or `ImportError` from a broken plugin entry point is silently converted to `ValueError: Unknown node type '...'`, hiding the real cause. The available-types list in the error message may also be misleading if the registry itself failed to populate.

**Severity:** 🟡 Medium  
**Dimension:** D3 — Error Handling  
**Evidence:** `sdk.py` `PipelineNode._validate()`: `except Exception: available = ...; raise ValueError(...)` — bare `Exception` catch.  
**Proposed Fix:** Narrow the catch to `(KeyError, LookupError)` which are the expected exceptions from `registry.get_class()` for unknown types. Let unexpected exceptions propagate with their original type and traceback.

---

**[G5-07] `Pipeline.subscribe()` unsubscribe function silently ignores double-unsubscribe**

The `_unsubscribe` closure catches `ValueError` from `list.remove()` and passes silently. This is intentional (idempotent unsubscribe), but it also silently ignores the case where the callback was never registered (e.g. a programming error where the wrong unsubscribe function is called). There is no way for the caller to distinguish "already unsubscribed" from "was never subscribed".

**Severity:** 🔵 Low  
**Dimension:** D3 — Error Handling  
**Evidence:** `sdk.py` `_unsubscribe()`: `except ValueError: pass`  
**Proposed Fix:** No code change required, but document the idempotent behaviour explicitly in the `subscribe()` docstring: `"The returned unsubscribe function is idempotent — calling it multiple times is safe."`

---

#### D4 — Performance

**[G5-08] `Pipeline._build_ir()` is called in `__init__` AND `_from_ir()` avoids it — inconsistency documented but asymmetric**

`__init__` always calls `_build_ir()`, which constructs `IRNode` and `IREdge` objects. `_from_ir()` bypasses this. The asymmetry is intentional and documented (S-04 fix), but it means that `Pipeline(nodes, ...)` followed by `pipeline.to_ir()` produces a `GraphIR` that was built from scratch, while `Pipeline.from_json(path)` produces a `GraphIR` loaded from disk. Both are correct, but the two construction paths have different performance characteristics that are not documented in `__init__`'s docstring.

**Severity:** 🔵 Low  
**Dimension:** D4 — Performance  
**Evidence:** `sdk.py` `Pipeline.__init__` calls `self._build_ir()`. `Pipeline._from_ir()` sets `pipeline._graph_ir = graph` directly.  
**Proposed Fix:** No code change required. Add a note to `__init__` docstring: `"For loading from a serialised file, prefer Pipeline.from_json() which avoids rebuilding the IR."`

---

No other performance issues found. `copy.deepcopy(self._graph_ir)` in `_execute()` is the correct approach (S-03 fix) and is O(N) in graph size — acceptable.


---

#### D5 — Test Coverage Gaps

**[G5-09] No test for `ArtifactCollection.get()` priority order — raw vs. artifact lookup**

The dual-priority semantics of `get()` (raw dict first, then artifact lookup) are not tested. A test should verify that when a key exists in both `_raw` and `artifacts`, the raw value is returned, and that when a key exists only in `artifacts`, the `ArtifactRecord` is returned.

**Severity:** 🟡 Medium  
**Dimension:** D5 — Test Coverage Gaps  
**Evidence:** No test in the test suite exercises the fallback artifact-lookup path of `ArtifactCollection.get()`.  
**Proposed Fix:** Add tests: (a) `collection.get("node_0")` returns raw value when `"node_0"` is in `_raw`; (b) `collection.get("node_0")` returns `ArtifactRecord` when `"node_0"` is not in `_raw` but is a `node_id` in `artifacts`.

---

**[G5-10] No test for concurrent `subscribe()` + `run()` — subscriber list mutation during iteration**

`_make_subscriber_logger` copies `self._subscribers` via `list(self._subscribers)` inside `_SL._emit`. However, `subscribe()` and the returned `_unsubscribe()` mutate `self._subscribers` directly. If a subscriber calls `unsubscribe()` from within its own callback (a common pattern), `list.remove()` is called while `_emit` is iterating over `list(self._subscribers)` — the copy makes this safe, but this is not tested.

**Severity:** 🟡 Medium  
**Dimension:** D5 — Test Coverage Gaps  
**Evidence:** `sdk.py` `_SL._emit`: `for cb in list(self._subscribers)` — copy is correct but untested for the self-unsubscribe case.  
**Proposed Fix:** Add a test where a subscriber calls its own unsubscribe function during the callback and verify no exception is raised and subsequent events are not delivered to the unsubscribed callback.

---

**[G5-11] No test for `Pipeline.run_with_manager()` returning the same `run_id` as `get_last_run_id()`**

`run_with_manager()` returns `(collection, run_manager)` and also sets `self._last_run_id`. There is no test verifying that `pipeline.get_last_run_id() == run_manager.run_id` after a call to `run_with_manager()`.

**Severity:** 🔵 Low  
**Dimension:** D5 — Test Coverage Gaps  
**Evidence:** No test exercises `get_last_run_id()` in conjunction with `run_with_manager()`.  
**Proposed Fix:** Add a test asserting `pipeline.get_last_run_id() == run_manager.run_id` after `run_with_manager()`.


---

#### D6 — Security

**[G5-12] `Pipeline.to_yaml()` writes user-controlled `name` and `description` fields to YAML without sanitisation**

`to_yaml()` serialises `graph.metadata.name` and `graph.metadata.description` into YAML via `yaml.dump`. PyYAML's `dump` correctly escapes special YAML characters, so there is no YAML injection risk for the file itself. However, if the resulting YAML file is later consumed by an unsafe YAML loader (`yaml.load()` without `Loader=yaml.SafeLoader`), a crafted `description` containing YAML tags (e.g. `!!python/object/apply:os.system`) could execute arbitrary code. The risk is in the consumer, not in `to_yaml()` itself, but it is worth documenting.

**Severity:** 🔵 Low  
**Dimension:** D6 — Security  
**Evidence:** `sdk.py` `Pipeline.to_yaml()`: `yaml.dump(config, f, sort_keys=False)` — output is safe, but downstream consumers using `yaml.load()` without `SafeLoader` are at risk.  
**Proposed Fix:** Add a docstring note: `"The output YAML is safe when loaded with yaml.safe_load(). Do not load it with yaml.load() without an explicit Loader."` Consider adding a comment in the YAML output header: `# Generated by Graphyn SDK — load with yaml.safe_load()`.

---

No other security issues found. `PipelineNode._validate()` correctly validates config against the Pydantic model before execution. `Pipeline._execute()` uses `copy.deepcopy` to prevent IR mutation. No path traversal risks in the SDK layer itself.

---

#### D7 — Documentation

**[G5-13] `ArtifactCollection` docstring says "NOT a dict subclass — `isinstance(collection, dict)` is `False`" but does not document `__contains__` and `keys()`/`values()`/`items()` behaviour**

The class implements the dict protocol (`__getitem__`, `__contains__`, `keys`, `items`, `values`) but is not a `dict` subclass. Code that uses `isinstance(x, dict)` to decide whether to call `.keys()` will fail. The docstring warns about `isinstance` but does not explain which dict methods are available, leaving callers to discover the protocol by reading the source.

**Severity:** 🟡 Medium  
**Dimension:** D7 — Documentation  
**Evidence:** `sdk.py` `ArtifactCollection` class docstring — no list of supported dict-protocol methods.  
**Proposed Fix:** Add to the class docstring: `"Supported dict-protocol methods: __getitem__, __contains__, keys(), items(), values(), get(). Not supported: __setitem__, __delitem__, update(), pop(), len()."`

---

**[G5-14] `Pipeline.run()` docstring does not document what happens when `resume_run_id` refers to a non-existent run**

The `resume_run_id` parameter is documented as "Resume from a previous run's checkpoint" but there is no documentation of the error raised when the run ID does not exist or has no checkpoints. Callers must read `run_manager.py` to discover the behaviour.

**Severity:** 🟡 Medium  
**Dimension:** D7 — Documentation  
**Evidence:** `sdk.py` `Pipeline.run()` docstring — `resume_run_id` parameter has no `Raises` section.  
**Proposed Fix:** Add a `Raises` section: `"ResumeError: if resume_run_id is provided but no checkpoint is found for that run."`

---

**[G5-15] `Pipeline.install_plugin()` return type annotation says `PluginRecord` but `PluginRecord` is not imported at the top level**

The return type annotation `-> "PluginRecord"` is a forward reference string. `PluginRecord` is never imported in `sdk.py` (not even under `TYPE_CHECKING`). Type checkers will report an unresolved forward reference, and `help(pipeline.install_plugin)` will show the string `"PluginRecord"` rather than the resolved type.

**Severity:** 🟡 Medium  
**Dimension:** D7 — Documentation  
**Evidence:** `sdk.py` `Pipeline.install_plugin()` signature: `-> "PluginRecord"` — no `from app.core.plugins.store import PluginRecord` under `TYPE_CHECKING`.  
**Proposed Fix:** Add to the `TYPE_CHECKING` block: `from app.core.plugins.store import PluginRecord`


---

#### D8 — Convention Adherence

**[G5-16] `Pipeline.to_yaml()` uses `import yaml` inside the method body — inconsistent with project import pattern**

All other lazy imports in `sdk.py` are justified by circular-import avoidance (e.g. `from app.core.pipeline import run_pipeline_ir`). The `import yaml` in `to_yaml()` has no such justification — `yaml` is a third-party library with no circular dependency risk. It should be at the module top level.

**Severity:** 🔵 Low  
**Dimension:** D8 — Convention Adherence  
**Evidence:** `sdk.py` `Pipeline.to_yaml()`: `import yaml` inside method body.  
**Proposed Fix:** Move `import yaml` to the top of `sdk.py` alongside other standard/third-party imports.

---

**[G5-17] SDK completeness gap — no `validate()` method on `Pipeline`**

The REST API exposes `POST /pipelines/validate` and the CLI exposes `validate --graph PATH`. Neither is available on the `Pipeline` SDK object. A user who wants to validate a pipeline programmatically before running it must either call `run()` and catch exceptions, or reach into `app.core.validation` directly. This is a missing SDK method that breaks the principle that the SDK should expose all major pipeline operations.

**Severity:** 🟠 High  
**Dimension:** D8 — Convention Adherence (SDK completeness)  
**Evidence:** REST API: `POST /api/v1/pipelines/validate`. CLI: `graphyn validate --graph PATH`. SDK: no `Pipeline.validate()` method.  
**Proposed Fix:** Add a `validate() -> list[str]` method to `Pipeline` that returns a list of validation error strings (empty list = valid). Internally delegate to the same validation logic used by the REST API router.

---

**[G5-18] SDK completeness gap — no `get_schema()` / `get_port_schema()` method on `Pipeline` or `PipelineNode`**

The REST API exposes `GET /nodes/{node_type}/config-schema` and `GET /nodes/{node_type}/port-schema`. The SDK has no equivalent. A user building a dynamic UI or validation layer on top of the SDK cannot retrieve node schemas without importing `app.core.registry_runtime` directly.

**Severity:** 🟡 Medium  
**Dimension:** D8 — Convention Adherence (SDK completeness)  
**Evidence:** REST API: `GET /api/v1/nodes/{node_type}/config-schema`, `GET /api/v1/nodes/{node_type}/port-schema`. SDK: no equivalent on `PipelineNode` or a top-level SDK function.  
**Proposed Fix:** Add module-level SDK functions: `get_node_config_schema(node_type: str) -> dict` and `get_node_port_schema(node_type: str) -> dict` that delegate to `registry.get_config_schema()` and `registry.get_port_schema()`.

---

**[G5-19] SDK completeness gap — no `list_nodes()` top-level function**

The REST API exposes `GET /nodes` and the CLI exposes `graphyn nodes`. The SDK has no equivalent top-level function. Users must import `app.core.registry_runtime.get_registry` and call `registry.list_nodes()` directly.

**Severity:** 🟡 Medium  
**Dimension:** D8 — Convention Adherence (SDK completeness)  
**Evidence:** REST API: `GET /api/v1/nodes`. CLI: `graphyn nodes`. SDK: no `list_nodes()` function.  
**Proposed Fix:** Add `list_nodes(category: str | None = None) -> list` to `sdk.py` as a module-level function.

---

**[G5-20] SDK completeness gap — no run control methods (`pause`, `resume`, `cancel`) on `Pipeline`**

The REST API exposes `POST /runs/{run_id}/pause`, `/resume`, `/cancel`. The CLI exposes `graphyn runs pause/resume/cancel`. The SDK has no equivalent. A user running a pipeline via `pipeline.run()` in a background thread cannot pause or cancel it through the SDK — they must reach into `app.core.run_manager.get_active_run()` directly.

**Severity:** 🟠 High  
**Dimension:** D8 — Convention Adherence (SDK completeness)  
**Evidence:** REST API: `POST /api/v1/runs/{run_id}/pause|resume|cancel`. CLI: `graphyn runs pause|resume|cancel`. SDK: no equivalent methods.  
**Proposed Fix:** Add `pipeline.pause()`, `pipeline.resume()`, `pipeline.cancel()` methods that delegate to `get_active_run(self._last_run_id)` and call the corresponding `RunManager` methods. Guard with a check that `_last_run_id` is set.


---

### File 2 — `utils/hash.py`

#### D1 — Code Quality & Correctness

No logic errors found. The JSON encoding approach is correct and unambiguous. `json.dumps(list(args), sort_keys=True, default=str)` correctly serialises all standard Python types. The `default=str` fallback ensures non-JSON-serialisable objects (e.g. custom classes) are converted to their string representation rather than raising `TypeError`.

One subtle correctness note: `sort_keys=True` sorts **dict keys** within nested dicts, but does not sort the top-level `list(args)`. This is correct — argument order is significant for `stable_hash`. Two calls with the same arguments in different order should produce different hashes, and they do.

---

#### D2 — Architecture & Design

No issues found. The module is a single-responsibility utility with no dependencies beyond `hashlib` and `json`. The choice of MD5 with `usedforsecurity=False` is appropriate for a non-cryptographic hash and is correctly documented.

---

#### D3 — Error Handling

No issues found. `json.dumps` with `default=str` never raises for standard Python types. `hashlib.md5(...).hexdigest()` never raises. `int(..., 16)` on a valid MD5 hex string never raises.

---

#### D4 — Performance

No issues found. MD5 is fast for the small inputs typical of cache key derivation. JSON serialisation is O(N) in the total size of the arguments. No unbounded growth or blocking I/O.

---

#### D5 — Test Coverage Gaps

**[G5-21] No property test for `stable_hash` separator-collision resistance**

The docstring explains the separator-collision fix but there is no automated test verifying the property `stable_hash("a", "b") != stable_hash("a|b")` or the more general property that `stable_hash(*args)` is injective over the argument list structure. See the Hypothesis skeleton in Part 3.

**Severity:** 🟡 Medium  
**Dimension:** D5 — Test Coverage Gaps  
**Evidence:** No property test exists for `stable_hash` in the test suite.  
**Proposed Fix:** Add the Hypothesis property test from Part 3 of this report.

---

**[G5-22] No test for `stable_hash` with `None` vs `"None"` distinction**

The docstring explicitly states that `None` and `"None"` are correctly distinguished (JSON encodes them as `null` and `"None"` respectively). This is not tested.

**Severity:** 🔵 Low  
**Dimension:** D5 — Test Coverage Gaps  
**Evidence:** No test for `stable_hash(None) != stable_hash("None")`.  
**Proposed Fix:** Add: `assert stable_hash(None) != stable_hash("None")`

---

#### D6 — Security

No issues found. `usedforsecurity=False` is correctly set for FIPS compliance. MD5 is used only for cache key derivation, not for any security-sensitive purpose. The function is documented as "Not suitable for security-sensitive purposes."

---

#### D7 — Documentation

No issues found. The module docstring is clear and accurate. The function docstring explains the separator-collision fix, the `None`/`"None"` distinction, and the FIPS flag. The "Not suitable for security-sensitive purposes" warning is present.

---

#### D8 — Convention Adherence

No issues found. Imports are at module level. The function follows the project naming convention. `from __future__ import annotations` is not needed (no forward references) and is correctly absent.


---

### File 3 — `utils/__init__.py`

#### D1 — Code Quality & Correctness

No issues found. The single import `from app.core.utils.hash import stable_hash` is correct and the `__all__` declaration is consistent.

#### D2 — Architecture & Design

No issues found. The package is a clean re-export surface with no logic.

#### D3 — Error Handling

No issues found. No error handling needed in a pure re-export module.

#### D4 — Performance

No issues found. The import is O(1) and has no side effects.

#### D5 — Test Coverage Gaps

No issues found. The re-export is trivially correct and does not require dedicated tests beyond those for `hash.py`.

#### D6 — Security

No issues found.

#### D7 — Documentation

**[G5-23] `utils/__init__.py` module docstring is generic — does not list exported symbols**

The docstring says `"Utility helpers for the Graphyn platform."` but does not list the exported symbols or link to the individual modules. For a package that may grow over time, a brief symbol inventory helps contributors understand what is available without reading `__all__`.

**Severity:** 🔵 Low  
**Dimension:** D7 — Documentation  
**Evidence:** `utils/__init__.py` line 2: `"""Utility helpers for the Graphyn platform."""`  
**Proposed Fix:** Update to: `"""Utility helpers for the Graphyn platform.\n\nExports:\n    stable_hash: Non-cryptographic stable integer hash (see utils/hash.py).\n"""`

#### D8 — Convention Adherence

No issues found. `__all__` is present and consistent with the import.

---

### File 4 — `__init__.py`

#### D1 — Code Quality & Correctness

No issues found. The `__getattr__` lazy-loading pattern is correct Python 3.7+ module-level `__getattr__`. The `AttributeError` fallback with `f"module {__name__!r} has no attribute {name!r}"` is the correct message format matching Python's own `AttributeError` for missing attributes.

#### D2 — Architecture & Design

No issues found. The lazy-loading pattern correctly avoids pulling in the full pipeline module (and its transitive imports) at package import time. This is the S-09 fix and it is correctly implemented.

#### D3 — Error Handling

No issues found. The `AttributeError` is raised correctly for unknown attribute names. The `from app.core.pipeline import ResumeError` inside `__getattr__` will propagate `ImportError` if `pipeline.py` fails to import — this is the correct behaviour (fail loudly on broken imports).

#### D4 — Performance

No issues found. The lazy import is O(1) after the first access (Python caches module imports).

#### D5 — Test Coverage Gaps

**[G5-24] No test for `app.core.ResumeError` lazy import — verifies S-09 fix**

The S-09 fix (lazy `ResumeError` import) has no dedicated test. A test should verify that `import app.core` does not import `app.core.pipeline` as a side effect, and that `app.core.ResumeError` is accessible after the lazy import.

**Severity:** 🟡 Medium  
**Dimension:** D5 — Test Coverage Gaps  
**Evidence:** No test in the test suite checks `"app.core.pipeline" not in sys.modules` after `import app.core`.  
**Proposed Fix:** Add a test: `import sys; import app.core; assert "app.core.pipeline" not in sys.modules; from app.core import ResumeError; assert ResumeError is not None`

#### D6 — Security

No issues found.

#### D7 — Documentation

No issues found. The module docstring clearly explains the lazy-loading rationale and the S-09 fix.

#### D8 — Convention Adherence

No issues found. `from __future__ import annotations` is present. The `__all__` declaration is consistent with `__getattr__`.


---

## PART 3 — Special Items

### S-07 — Separator Collision Fix Verification (`utils/hash.py`)

**Verdict: CONFIRMED PRESENT AND CORRECT ✅**

The separator-collision fix is present. The previous implementation used `"|".join(str(a) for a in args)` which was ambiguous when arguments contained the `|` character. The current implementation uses **JSON encoding** as the separator strategy:

```python
s = json.dumps(list(args), sort_keys=True, default=str)
```

**Exact separator character used:** None — JSON encoding is used instead of a separator character. The arguments are serialised as a JSON array, where each element is unambiguously delimited by JSON's structural characters (`,`, `[`, `]`, `"`, etc.).

**Collision analysis for `stable_hash("a", "b")` vs `stable_hash("a|b")`:**

- `stable_hash("a", "b")` → `json.dumps(["a", "b"])` → `'["a", "b"]'`
- `stable_hash("a|b")` → `json.dumps(["a|b"])` → `'["a|b"]'`

These two strings are different (`'["a", "b"]'` ≠ `'["a|b"]'`), so the hashes will differ. ✅

**Additional collision cases verified:**

| Call | JSON encoding | Distinct? |
|------|--------------|-----------|
| `stable_hash("a", "b")` | `'["a", "b"]'` | ✅ |
| `stable_hash("a\|b")` | `'["a\|b"]'` | ✅ different from above |
| `stable_hash("a,b")` | `'["a,b"]'` | ✅ different from `stable_hash("a", "b")` |
| `stable_hash(None)` | `'[null]'` | ✅ |
| `stable_hash("None")` | `'["None"]'` | ✅ different from `stable_hash(None)` |
| `stable_hash(1, 2)` | `'[1, 2]'` | ✅ |
| `stable_hash("1, 2")` | `'["1, 2"]'` | ✅ different from `stable_hash(1, 2)` |

The JSON encoding approach is provably collision-free for all inputs that JSON can represent unambiguously (strings, numbers, booleans, None, lists, dicts). The `default=str` fallback for non-JSON-serialisable objects (e.g. custom class instances) reduces to string representation, which may have collisions for objects with identical `__str__` but different identity — this is acceptable for a non-cryptographic cache key.

---

### Correctness Property Skeleton — `stable_hash` (`utils/hash.py`)

The following Hypothesis property test verifies that `stable_hash` is injective over argument list structure — i.e. that different argument lists always produce different hashes (with overwhelming probability for MD5).

```python
# unit_test/core/utils/test_hash_property.py
"""
Property-based tests for app.core.utils.hash.stable_hash.

Tests the separator-collision resistance property:
    stable_hash(*args_a) != stable_hash(*args_b)
    whenever list(args_a) != list(args_b) as JSON arrays.
"""
from __future__ import annotations

import json
import pytest
from hypothesis import given, assume, settings
from hypothesis import strategies as st

from app.core.utils.hash import stable_hash


# ── Strategy: JSON-serialisable scalars ──────────────────────────────────────

json_scalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**31), max_value=2**31),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=64),
)


# ── Property 1: Separator-collision resistance ────────────────────────────────

@given(
    a=st.text(max_size=32),
    b=st.text(max_size=32),
)
@settings(max_examples=500)
def test_two_arg_vs_concat_never_collide(a: str, b: str) -> None:
    """stable_hash(a, b) != stable_hash(a_b_concat) for all strings a, b.

    This is the core S-07 property: the two-argument form must be
    distinguishable from any single-argument concatenation.
    """
    # The single-argument form that the old "|".join implementation
    # would have confused with stable_hash(a, b):
    concat_pipe = a + "|" + b
    concat_comma = a + ", " + b
    concat_bare = a + b

    h_two = stable_hash(a, b)

    # None of the single-argument concatenations should collide
    # (they produce different JSON arrays: ["a","b"] vs ["a|b"] etc.)
    assert h_two != stable_hash(concat_pipe), (
        f"Collision: stable_hash({a!r}, {b!r}) == stable_hash({concat_pipe!r})"
    )
    assert h_two != stable_hash(concat_comma), (
        f"Collision: stable_hash({a!r}, {b!r}) == stable_hash({concat_comma!r})"
    )
    # bare concat only collides when b == "" (a + "" == a), which is a
    # degenerate case — exclude it
    assume(b != "")
    assert h_two != stable_hash(concat_bare), (
        f"Collision: stable_hash({a!r}, {b!r}) == stable_hash({concat_bare!r})"
    )


# ── Property 2: Argument-count sensitivity ────────────────────────────────────

@given(args=st.lists(json_scalar, min_size=1, max_size=6))
@settings(max_examples=300)
def test_different_arg_counts_differ(args: list) -> None:
    """stable_hash(*args) != stable_hash(*args, extra) for any extra value."""
    h_original = stable_hash(*args)
    # Adding any element changes the JSON array
    h_extended = stable_hash(*args, "EXTRA_SENTINEL_VALUE_XYZ")
    assert h_original != h_extended


# ── Property 3: None vs "None" distinction ────────────────────────────────────

def test_none_vs_string_none() -> None:
    """stable_hash(None) != stable_hash("None") — JSON null vs string."""
    assert stable_hash(None) != stable_hash("None")
    assert stable_hash(None, None) != stable_hash("None", "None")
    assert stable_hash(None, "x") != stable_hash("None", "x")


# ── Property 4: Determinism (same args → same hash across calls) ──────────────

@given(args=st.lists(json_scalar, min_size=0, max_size=5))
@settings(max_examples=200)
def test_deterministic(args: list) -> None:
    """stable_hash is deterministic: same args always produce the same hash."""
    assert stable_hash(*args) == stable_hash(*args)


# ── Property 5: Argument-order sensitivity ────────────────────────────────────

@given(
    a=json_scalar,
    b=json_scalar,
)
@settings(max_examples=300)
def test_order_sensitive(a, b) -> None:
    """stable_hash(a, b) != stable_hash(b, a) when a != b."""
    assume(a != b)
    # JSON arrays are order-sensitive: ["a","b"] != ["b","a"]
    assert stable_hash(a, b) != stable_hash(b, a)
```


---

## PART 4 — Consolidated Finding Index (G5)

### All Findings

| ID | Title | File | Severity | Dimension |
|----|-------|------|----------|-----------|
| G5-01 | `ArtifactCollection.get()` priority order masks artifact lookup | `sdk.py` | 🟡 Medium | D1 |
| G5-02 | `_from_ir()` bypasses `_validate()` — unregistered node types silently accepted | `sdk.py` | 🟡 Medium | D1 |
| G5-03 | `to_yaml()` missing `allow_unicode=True` — non-ASCII escaped | `sdk.py` | 🔵 Low | D1 |
| G5-04 | `ArtifactCollection.lineage()` creates new `ProvenanceStore` per call | `sdk.py` | 🟡 Medium | D2 |
| G5-05 | `_SubscriberLoggerClass` global lazy-init not thread-safe | `sdk.py` | 🟡 Medium | D2 |
| G5-06 | `PipelineNode._validate()` catches bare `Exception` — masks real errors | `sdk.py` | 🟡 Medium | D3 |
| G5-07 | `_unsubscribe()` silent double-unsubscribe — undocumented | `sdk.py` | 🔵 Low | D3 |
| G5-08 | `_build_ir()` vs `_from_ir()` asymmetry undocumented in `__init__` | `sdk.py` | 🔵 Low | D4 |
| G5-09 | No test for `ArtifactCollection.get()` priority order | `sdk.py` | 🟡 Medium | D5 |
| G5-10 | No test for concurrent subscribe + self-unsubscribe during callback | `sdk.py` | 🟡 Medium | D5 |
| G5-11 | No test for `get_last_run_id()` == `run_manager.run_id` | `sdk.py` | 🔵 Low | D5 |
| G5-12 | `to_yaml()` output safe but downstream `yaml.load()` risk undocumented | `sdk.py` | 🔵 Low | D6 |
| G5-13 | `ArtifactCollection` dict-protocol methods not listed in docstring | `sdk.py` | 🟡 Medium | D7 |
| G5-14 | `Pipeline.run()` missing `Raises` for `resume_run_id` not found | `sdk.py` | 🟡 Medium | D7 |
| G5-15 | `install_plugin()` return type `PluginRecord` not in `TYPE_CHECKING` | `sdk.py` | 🟡 Medium | D7 |
| G5-16 | `import yaml` inside `to_yaml()` method body — non-idiomatic | `sdk.py` | 🔵 Low | D8 |
| G5-17 | SDK missing `Pipeline.validate()` method (REST + CLI have it) | `sdk.py` | 🟠 High | D8 |
| G5-18 | SDK missing `get_node_config_schema()` / `get_node_port_schema()` | `sdk.py` | 🟡 Medium | D8 |
| G5-19 | SDK missing `list_nodes()` top-level function | `sdk.py` | 🟡 Medium | D8 |
| G5-20 | SDK missing `pause()` / `resume()` / `cancel()` on `Pipeline` | `sdk.py` | 🟠 High | D8 |
| G5-21 | No property test for `stable_hash` separator-collision resistance | `utils/hash.py` | 🟡 Medium | D5 |
| G5-22 | No test for `stable_hash(None) != stable_hash("None")` | `utils/hash.py` | 🔵 Low | D5 |
| G5-23 | `utils/__init__.py` docstring does not list exported symbols | `utils/__init__.py` | 🔵 Low | D7 |
| G5-24 | No test for `app.core.ResumeError` lazy import (S-09 fix) | `__init__.py` | 🟡 Medium | D5 |

### G5 Severity Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟠 High | 2 |
| 🟡 Medium | 13 |
| 🔵 Low | 9 |
| **Total** | **24** |

