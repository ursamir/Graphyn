# Graphyn Platform — Independent Architectural Review

**Date:** 2026-05-26 | **Reviewer:** Principal Software Architect | **Codebase root:** `/home/meritech/Desktop/newAudio3`

---

## Pre-Review Verification Results

| Check | Result |
|---|---|
| File-header contract compliance | ✅ **All files compliant** |
| RULE 1 — module-level `app.domain` / `app.models` imports in `app/core/` | ✅ **Zero violations** |
| `app/core/` → `app/api/` imports | ✅ **Zero violations** |
| `app/models/` imports beyond `PortDataType` | ✅ **Zero violations** |
| Plugin nodes importing beyond allowed BC2 surface | ✅ **Zero violations** |
| MCP handlers importing execution internals | ⚠️ **1 violation** (`optimization.py` → `app.core.planner`) |
| `_resolve_capability` canonical location | ✅ `registry_runtime.py` (BC3) |
| `_infer_artifact_type` location | ✅ `artifact_store.py` (BC6) |
| `_WORKSPACE` sentinel removal | ⚠️ **Stale dead variable** in `run_journal.py` |

---

## FILE IDENTITY SUMMARIES

### BC1 — Graph Language (`app/core/ir/`)

**`models.py`**
```
Purpose:          Canonical, versioned, immutable data model for pipeline graphs
Bounded Context:  BC1 — Graph Language
Owns:             GraphIR, IRNode, IREdge, IRMetadata, IRParameter, IRCapabilityMetadata
Must NOT Know:    Nodes, execution, storage, domain
Reason To Change: Graph schema evolves
Primary Deps:     pydantic, stdlib only
Coupling Level:   LOW
Extraction Ready: YES — pure pydantic, zero app imports
Architectural Risk: LOW
```

**`loader.py`**
```
Purpose:          Serialize/deserialize/version-validate GraphIR documents
Bounded Context:  BC1 — Graph Language
Owns:             load_ir(), dump_ir(), IRVersionError, CURRENT_IR_VERSION
Must NOT Know:    Nodes, execution, domain
Reason To Change: IR version bumps, new serialization format
Primary Deps:     pydantic, json, app.core.ir.models
Coupling Level:   LOW
Extraction Ready: YES
Architectural Risk: LOW
```

**`yaml_shim.py`** / **`migrate.py`**
```
Purpose:          YAML → GraphIR conversion (shim) and file migration (CLI tool)
Bounded Context:  BC1 — Graph Language
Coupling Level:   LOW
Extraction Ready: YES
Architectural Risk: LOW
```

---

### BC2 — Node Contract (`app/core/nodes/base.py` et al.)

**`base.py`**
```
Purpose:          Base class and lifecycle protocol for all pipeline nodes
Bounded Context:  BC2 — Node Contract
Owns:             Node[InputT,OutputT], SISO wrapper, _maybe_wrap_siso()
Must NOT Know:    Registry, execution, storage, domain
Reason To Change: Node lifecycle protocol changes
Primary Deps:     BC2 (config, ports, retry, compat, observers)
Coupling Level:   LOW
Extraction Ready: YES
Architectural Risk: LOW — one known quality issue (SA-NE2, documented)
```

**`ports.py`, `config.py`, `retry.py`, `metadata.py`, `observers.py`, `compat.py`, `errors.py`**
```
All: LOW coupling, HIGH extraction readiness, pure BC2 with no upward dependencies
```

---

### BC3 — Node Catalog

**`registry.py`**
```
Purpose:          Thread-safe singleton registry mapping node_type → class + metadata
Bounded Context:  BC3 — Node Catalog
Owns:             NodeRegistry (register, unregister, get_class, get_metadata, list_nodes, ...)
Must NOT Know:    Execution, storage, domain
Coupling Level:   LOW
Extraction Ready: YES
Architectural Risk: LOW — one encapsulation issue (see Finding 3)
```

**`discovery.py`**
```
Purpose:          Scan directories and register Node/PortDataType subclasses
Bounded Context:  BC3 — Node Catalog
Coupling Level:   MEDIUM (imports PluginLoader lazily)
Extraction Ready: MEDIUM
Architectural Risk: LOW
```

**`registry_runtime.py`**
```
Purpose:          NodeRegistry singleton accessor + resolve_capability() pure function
Bounded Context:  BC3 — Node Catalog
Coupling Level:   LOW
Extraction Ready: YES — but has a lazy import of IRCapabilityMetadata to avoid circular dep
Architectural Risk: LOW
```

**`plugins/` package**
```
All components: BC3 — Node Catalog (Plugin Ecosystem)
Coupling Level: MEDIUM (manager.py accesses _classes directly — see Finding 3)
Extraction Ready: MEDIUM
```

---

### BC4 — Execution Planner (`app/core/planner.py`)

```
Purpose:          Transform GraphIR into executable DAG: instantiate nodes, validate edges,
                  compute topo order and parallel waves
Bounded Context:  BC4 — Execution Planner
Owns:             NodeSpec, EdgeSpec, PipelineConfig, PipelineGraph, _ir_to_pipeline_config()
Must NOT Know:    Execution runtime, storage, domain
Reason To Change: DAG construction algorithm changes
Primary Deps:     BC2 (nodes.base, observers, compat, errors), BC3 (registry_runtime — lazy),
                  app.core.utils.hash
Coupling Level:   LOW
Extraction Ready: YES
Architectural Risk: LOW
```

---

### BC5 — Execution Runtime

**`orchestrator.py`**
```
Purpose:          Coordinate execution of validated DAGs across all execution modes
Bounded Context:  BC5 — Execution Runtime
Owns:             run_pipeline_ir_async(), run_pipeline_ir()
Coupling Level:   HIGH (imports BC4, BC6 at module level; see Finding 1)
Extraction Ready: LOW — tightly coupled to BC6 at module level
Architectural Risk: MEDIUM
```

**`node_executor.py`**
```
Purpose:          Drive a single node through its lifecycle with retry
Bounded Context:  BC5 — Execution Runtime
Coupling Level:   LOW
Extraction Ready: YES
Architectural Risk: LOW — SA-NE2 (dynamic attribute injection) is documented
```

**`executor.py`**
```
Purpose:          Execute all nodes in a parallel wave concurrently
Bounded Context:  BC5 — Execution Runtime
Coupling Level:   MEDIUM (imports BC6 lazily inside _run_node)
Extraction Ready: MEDIUM
Architectural Risk: LOW
```

**`runtime_backend.py`**
```
Purpose:          Pluggable execution backend abstraction — canonical entry point
Bounded Context:  BC5 — Execution Runtime
Coupling Level:   LOW (LocalPythonBackend imports orchestrator lazily)
Extraction Ready: YES
Architectural Risk: LOW
```

**`conditions.py`, `events.py`**
```
Both: LOW coupling, HIGH extraction readiness, pure BC5 with no upward dependencies
```

**`pipeline.py` (shim)**
```
Purpose:          Backward-compatibility re-export shim
Bounded Context:  BC5 — Execution Runtime (shim)
Coupling Level:   HIGH (imports from all BCs)
Extraction Ready: NO — by design; will be removed
Architectural Risk: LOW (shim only, no logic)
```

---

### BC6 — Observability & Storage

**`run_journal.py`**
```
Purpose:          Filesystem persistence for a single pipeline run
Bounded Context:  BC6 — Observability & Storage
Coupling Level:   MEDIUM (lazy imports of artifact_store, provenance, checkpoint)
Extraction Ready: MEDIUM
Architectural Risk: LOW — one stale dead variable (_WORKSPACE, see Finding 5)
```

**`artifact_store.py`**
```
Purpose:          Content-addressed, typed artifact registry
Bounded Context:  BC6 — Observability & Storage
Coupling Level:   LOW (delegates to ArtifactSerializerRegistry)
Extraction Ready: YES
Architectural Risk: LOW
```

**`artifact_serializer.py`**
```
Purpose:          Pluggable serializer registry interface
Bounded Context:  BC6 — Observability & Storage
Coupling Level:   LOW — pure interface, zero domain imports
Extraction Ready: YES
Architectural Risk: LOW
```

**`checkpoint.py`, `pipeline_cache.py`, `provenance.py`, `run_control.py`, `logger.py`**
```
All: LOW-MEDIUM coupling, MEDIUM-HIGH extraction readiness
```

---

## FINDINGS

---

```
--------------------------------------------------------------------
FILE:      app/core/orchestrator.py
BOUNDARY:  BC5 — Execution Runtime
CATEGORY:  Module-Level BC6 Coupling
SEVERITY:  MEDIUM
--------------------------------------------------------------------
CURRENT RESPONSIBILITY:
Coordinates all execution modes. Also imports two BC6 symbols at module
level: _infer_artifact_type from artifact_store and _write_checkpoint /
_load_checkpoint_outputs from checkpoint.

EXPECTED RESPONSIBILITY:
BC5 should depend on BC6 only at call time (lazy imports), not at module
load time. The dependency direction BC5→BC6 is architecturally correct,
but module-level binding creates a hard coupling that prevents independent
testing of the orchestrator without the full storage layer being importable.

ARCHITECTURAL ISSUE:
Lines 30 and 37:
  from app.core.artifact_store import _infer_artifact_type
  from app.core.checkpoint import _write_checkpoint, _load_checkpoint_outputs

These are module-level imports of BC6 into BC5. All other BC6 imports in
orchestrator.py (logger, run_journal, run_control, pipeline_cache) are
correctly lazy (inside the async function body). These two are inconsistent
with that pattern.

Additionally, _infer_artifact_type is a private name (underscore prefix)
being imported across a bounded context boundary. It appears in the
artifact_store.py Public Surface docstring, but the underscore convention
signals it is not truly public. The correct pattern would be a named public
function or a method on ArtifactStore.

EVIDENCE:
  orchestrator.py:30: from app.core.artifact_store import _infer_artifact_type
  orchestrator.py:37: from app.core.checkpoint import _write_checkpoint, _load_checkpoint_outputs
  All other BC6 imports in orchestrator.py are lazy (inside function body).

WHY THIS IS DANGEROUS:
Importing at module level means any test that imports orchestrator.py
transitively loads artifact_store.py and checkpoint.py. This increases
import time, makes test isolation harder, and tightens the coupling between
BC5 and BC6 in a way that will resist future extraction of the execution
runtime into a separate package.

RECOMMENDED DIRECTION:
Move both imports inside run_pipeline_ir_async() alongside the other lazy
BC6 imports. Rename _infer_artifact_type to infer_artifact_type (public)
or expose it as ArtifactStore.infer_type() to make the cross-BC contract
explicit.

EXTRACTION IMPACT:
Prevents clean extraction of BC5 into a standalone execution package
without dragging in BC6 storage infrastructure.

DISTRIBUTED SYSTEM IMPACT:
A remote execution worker that imports orchestrator.py would also import
the local filesystem storage layer, which is incorrect for a distributed
backend.
--------------------------------------------------------------------
```

---

```
--------------------------------------------------------------------
FILE:      app/cli/main.py (cmd_validate function)
BOUNDARY:  CLI Interface
CATEGORY:  Duplicated Planner Logic / Responsibility Drift
SEVERITY:  MEDIUM
--------------------------------------------------------------------
CURRENT RESPONSIBILITY:
cmd_validate performs deep IR graph validation including: node type
resolution, per-node config validation, port existence checks, port type
compatibility checks, and a full Kahn's algorithm cycle detection — all
implemented inline within the CLI command function.

EXPECTED RESPONSIBILITY:
The CLI should delegate validation to the SDK's Pipeline.validate() or
directly to PipelineGraph, which already owns all of this logic. The CLI's
responsibility is argument parsing and output formatting, not graph
topology analysis.

ARCHITECTURAL ISSUE:
cmd_validate contains ~100 lines of validation logic that duplicates what
PipelineGraph._build() already does:
  - Node instantiation (PipelineGraph does this)
  - CompatibilityChecker.check_connection() (PipelineGraph does this)
  - Kahn's topological sort cycle detection (PipelineGraph._topological_sort() does this)

The SDK's Pipeline.validate() already calls PipelineGraph for topology
checks. The CLI bypasses this entirely and re-implements the same logic.

EVIDENCE:
  cli/main.py: Steps 5 & 6 — manual port existence + CompatibilityChecker calls
  cli/main.py: Step 7 — manual Kahn's algorithm (defaultdict + deque)
  planner.py: PipelineGraph._build() — identical port validation
  planner.py: PipelineGraph._topological_sort() — identical cycle detection
  sdk.py: Pipeline.validate() — calls PipelineGraph, already correct

WHY THIS IS DANGEROUS:
Any change to PipelineGraph's validation logic (new port rules, new error
types, new edge semantics) must be replicated in cmd_validate manually.
This has already diverged: cmd_validate uses a fixed seed of 0 for node
instantiation (stable_hash(seed, node_type, 0)) while PipelineGraph uses
the actual pipeline seed with config included (SA-P3 fix). The CLI
validator can produce different results than the runtime for the same graph.

RECOMMENDED DIRECTION:
Replace cmd_validate's Steps 3–7 with a single call to Pipeline.validate()
(which already uses PipelineGraph internally). The CLI should only handle
file I/O, argument parsing, and output formatting. The detailed error
messages can be preserved by catching PipelineGraphError and NodeTypeError
from PipelineGraph.

EXTRACTION IMPACT:
The CLI currently cannot be extracted without also extracting planner.py
and compat.py, which it imports directly. Delegating to Pipeline.validate()
would reduce the CLI's direct dependency surface to SDK only.

DISTRIBUTED SYSTEM IMPACT:
Low — CLI is a local tool. But the divergence means a graph that passes
CLI validation may fail at runtime (or vice versa), which is a correctness
issue regardless of deployment topology.
--------------------------------------------------------------------
```

---

```
--------------------------------------------------------------------
FILE:      app/cli/main.py (cmd_artifacts_replay function)
BOUNDARY:  CLI Interface
CATEGORY:  Interface Layer Bypassing Canonical Entry Point
SEVERITY:  MEDIUM
--------------------------------------------------------------------
CURRENT RESPONSIBILITY:
cmd_artifacts_replay imports run_pipeline_ir directly from orchestrator.py
and calls it, bypassing the canonical RuntimeBackend abstraction.

EXPECTED RESPONSIBILITY:
All interfaces (SDK, API, MCP, CLI) must call get_backend().execute() as
the canonical execution entry point. This was the explicit goal of
ARCH-REVIEW-6 and is enforced everywhere else.

ARCHITECTURAL ISSUE:
  cli/main.py:844: from app.core.orchestrator import run_pipeline_ir
  cli/main.py:863: run_pipeline_ir(graph, run_manager=run_manager)

Every other execution path in the CLI uses get_backend().execute() or
Pipeline.run(). This one function is the sole remaining direct orchestrator
import in the CLI, making it an inconsistency that will silently bypass any
custom backend registered via register_backend().

EVIDENCE:
  cli/main.py:844: from app.core.orchestrator import run_pipeline_ir
  runtime_backend.py: get_backend() is the canonical entry point
  All other CLI execution paths: get_backend().execute() or Pipeline.run()

WHY THIS IS DANGEROUS:
If a custom backend is registered (e.g. a distributed K8s backend), the
replay command will silently use the local Python backend instead. This is
an invisible behavioral inconsistency that will be very hard to debug in
production.

RECOMMENDED DIRECTION:
Replace with:
  from app.core.runtime_backend import get_backend
  get_backend().execute(graph, run_manager=run_manager)

This is a one-line fix that restores architectural consistency.

EXTRACTION IMPACT:
The CLI currently has a direct dependency on orchestrator.py that should
not exist. Removing it reduces the CLI's dependency surface to
runtime_backend.py only.

DISTRIBUTED SYSTEM IMPACT:
HIGH — this is the exact scenario where a distributed backend would be
bypassed silently.
--------------------------------------------------------------------
```

---

```
--------------------------------------------------------------------
FILE:      app/core/plugins/manager.py, app/core/plugins/loader.py
BOUNDARY:  BC3 — Node Catalog (Plugin Ecosystem)
CATEGORY:  Encapsulation Violation — Private Attribute Access
SEVERITY:  MEDIUM
--------------------------------------------------------------------
CURRENT RESPONSIBILITY:
PluginManager and PluginLoader access NodeRegistry._classes directly
(a private dict) to snapshot registered node types before and after
plugin loading, and to iterate classes for unloading.

EXPECTED RESPONSIBILITY:
All access to registry state should go through NodeRegistry's public API.
The registry owns its internal state; callers should not reach into _classes.

ARCHITECTURAL ISSUE:
Five direct accesses to self._registry._classes:
  loader.py:260: before: set[str] = set(self._registry._classes.keys())
  loader.py:289: after:  set[str] = set(self._registry._classes.keys())
  manager.py:294: before = set(self._registry._classes.keys())
  manager.py:296: after  = set(self._registry._classes.keys())
  manager.py:417: for node_type, cls in list(self._registry._classes.items()):

The public API already provides list_nodes() which returns NodeMetadata
objects. The node_type strings are available via m.node_type. The class
objects needed for _unload_node_types() (to call inspect.getfile()) are
not exposed publicly.

The _unload_node_types() heuristic (using inspect.getfile() to find which
classes belong to a plugin) is also fragile: it relies on filesystem path
prefix matching, which can fail for compiled extensions, namespace packages,
or symlinked directories.

EVIDENCE:
  manager.py:417: for node_type, cls in list(self._registry._classes.items())
  registry.py: no public method returns (node_type, class) pairs
  registry.py: list_nodes() returns list[NodeMetadata] — no class objects

WHY THIS IS DANGEROUS:
Any refactoring of NodeRegistry's internal storage (e.g. changing _classes
from a plain dict to a more sophisticated structure) will silently break
PluginManager and PluginLoader. The encapsulation boundary between BC3
components is already weak; this makes it weaker.

A cleaner design would have NodeRegistry track which plugin_name registered
each node_type at registration time, and expose an unregister_plugin(name)
method. This would eliminate the inspect.getfile() heuristic entirely.

RECOMMENDED DIRECTION:
1. Add NodeRegistry.list_node_types() → list[str] as a public method
   (replaces _classes.keys() accesses).
2. Add NodeRegistry.get_class(node_type) (already exists) for the
   _unload_node_types() iteration.
3. Long-term: add NodeRegistry.register(node_type, cls, metadata,
   plugin_name=None) and NodeRegistry.unregister_plugin(plugin_name) to
   make plugin ownership explicit in the registry.

EXTRACTION IMPACT:
The current design couples PluginManager to NodeRegistry internals,
preventing independent extraction of either component.

DISTRIBUTED SYSTEM IMPACT:
Low — plugin management is a local operation. But the fragile heuristic
will fail in any environment where source files are not on the local
filesystem (e.g. compiled wheels, remote plugin loading).
--------------------------------------------------------------------
```

---

```
--------------------------------------------------------------------
FILE:      app/core/run_journal.py
BOUNDARY:  BC6 — Observability & Storage
CATEGORY:  Dead Code / Stale Module-Level State
SEVERITY:  LOW
--------------------------------------------------------------------
CURRENT RESPONSIBILITY:
run_journal.py defines _WORKSPACE = str(_project_dir()) at module level
(line 41) with a comment "Patchable for test isolation". This variable is
defined once and never referenced anywhere in the file.

EXPECTED RESPONSIBILITY:
RunManager.__init__() correctly calls _project_dir() at construction time
(not at import time), which is the right pattern. The _WORKSPACE sentinel
was part of the original broken implementation (NEW-2 fix) and should have
been fully removed.

ARCHITECTURAL ISSUE:
  run_journal.py:41: _WORKSPACE = str(_project_dir())

This is a module-level call to _project_dir() that freezes the project
directory path at import time. If GRAPHYN_PROJECT_DIR is set after this
module is imported (a documented pattern for tests), _WORKSPACE will hold
the wrong value. The variable is never used, so it causes no runtime bug —
but it is misleading dead code that contradicts the correct pattern used
in __init__().

EVIDENCE:
  run_journal.py:41: _WORKSPACE = str(_project_dir())  # defined
  run_journal.py: _WORKSPACE referenced 1 time total (the definition itself)
  run_journal.py:__init__: base_dir = str(_project_dir() / "runs")  # correct pattern

WHY THIS IS DANGEROUS:
A future developer may see _WORKSPACE and use it, reintroducing the
frozen-path bug that NEW-2 fixed. The comment "Patchable for test
isolation" is actively misleading — it suggests this is an intentional
test hook when it is actually dead code.

RECOMMENDED DIRECTION:
Delete line 41. The correct pattern (_project_dir() called at construction
time) is already in place.

EXTRACTION IMPACT:
Negligible — dead code.

DISTRIBUTED SYSTEM IMPACT:
None.
--------------------------------------------------------------------
```

---

```
--------------------------------------------------------------------
FILE:      app/mcp/handlers/optimization.py
BOUNDARY:  Application Layer — MCP Interface
CATEGORY:  Interface Layer Importing BC4 Directly
SEVERITY:  LOW
--------------------------------------------------------------------
CURRENT RESPONSIBILITY:
optimize_execution_handler imports PipelineGraph and _ir_to_pipeline_config
from app.core.planner (BC4) to build execution waves for analysis.

EXPECTED RESPONSIBILITY:
MCP handlers are application-layer thin shells. They should delegate to
the SDK or to public BC3/BC5 interfaces. Importing BC4 directly couples
the MCP layer to the planner's internal data structures.

ARCHITECTURAL ISSUE:
  optimization.py: from app.core.planner import PipelineGraph, _ir_to_pipeline_config

The handler uses PipelineGraph to compute execution_waves for the
optimization recommendations. This is the only MCP handler that reaches
into a bounded context below the SDK/runtime_backend level.

The import is lazy (inside the handler function), which mitigates the
module-level coupling concern. However, the handler now depends on
PipelineGraph's internal wave computation, which is a BC4 implementation
detail.

EVIDENCE:
  optimization.py: from app.core.planner import PipelineGraph, _ir_to_pipeline_config
  All other MCP handlers: import from BC1 (ir.loader), BC3 (registry_runtime),
    BC5 (runtime_backend), BC6 (artifact_store, provenance, run_journal)
  No other MCP handler imports from BC4

WHY THIS IS DANGEROUS:
If PipelineGraph's wave computation is refactored (e.g. moved to a
dedicated WavePlanner class), this handler will break. The handler also
instantiates nodes via PipelineGraph, which triggers node setup — this is
a side effect that should not happen in an analysis-only handler.

RECOMMENDED DIRECTION:
Expose a pure analysis function in BC4 or BC5:
  def analyze_graph(graph: GraphIR) -> GraphAnalysis
that returns wave structure, capability summary, and optimization hints
without instantiating nodes. The MCP handler then calls this function.
Alternatively, expose execution_waves via the SDK's Pipeline object.

EXTRACTION IMPACT:
The MCP server currently cannot be extracted without also extracting
planner.py. Removing this dependency would make the MCP server a true
application-layer component.

DISTRIBUTED SYSTEM IMPACT:
Low — optimization is a local analysis operation. But instantiating nodes
in an analysis handler is wasteful and could trigger unexpected side effects
(e.g. model loading in setup()).
--------------------------------------------------------------------
```

---

```
--------------------------------------------------------------------
FILE:      app/core/ir/models.py (IRNode)
BOUNDARY:  BC1 — Graph Language
CATEGORY:  Documentation/Implementation Contract Mismatch
SEVERITY:  LOW
--------------------------------------------------------------------
CURRENT RESPONSIBILITY:
IRNode stores config as MappingProxyType (immutable proxy) via the
_deep_copy_config validator. The class docstring states: "config: dict[str,
Any] is a plain Python dict and can be mutated in place."

EXPECTED RESPONSIBILITY:
The docstring should accurately describe the actual runtime type. The
contract note about mutability is the opposite of what the implementation
enforces.

ARCHITECTURAL ISSUE:
The docstring was written before the P-23 fix (deep-copy + MappingProxyType
wrapping) was applied. The fix correctly makes config immutable, but the
docstring was not updated. Callers reading the docstring may attempt
in-place mutation and get a TypeError at runtime.

EVIDENCE:
  models.py IRNode docstring: "config: dict[str, Any] is a plain Python dict
    and can be mutated in place"
  models.py _deep_copy_config: return MappingProxyType(copy.deepcopy(v))
  planner.py: dict(ir_node.config) — correctly converts to mutable dict

WHY THIS IS DANGEROUS:
Any plugin or external code that reads the IRNode docstring and attempts
in-place config mutation will get a silent TypeError. The docstring is
the primary contract document for BC1 consumers.

RECOMMENDED DIRECTION:
Update the IRNode docstring to:
  "config is stored as a MappingProxyType (immutable). Use dict(node.config)
  to obtain a mutable copy."

EXTRACTION IMPACT:
None — documentation only.

DISTRIBUTED SYSTEM IMPACT:
None.
--------------------------------------------------------------------
```

---

```
--------------------------------------------------------------------
FILE:      PluginPackage/Audio/audio_classifier/nodes.py
           PluginPackage/Common/trainer/nodes.py
BOUNDARY:  Plugin Layer
CATEGORY:  Type System Bypass — Untyped Port Declarations
SEVERITY:  LOW
--------------------------------------------------------------------
CURRENT RESPONSIBILITY:
AudioClassifierNode declares its input port with data_type=list (bare,
unparameterized). TrainerNode and ModelBuilderNode declare input ports
with data_type=object. These bypass the CompatibilityChecker entirely.

EXPECTED RESPONSIBILITY:
Port data_type should be as specific as possible to enable static
compatibility checking at pipeline build time. Using bare list or object
defeats the purpose of the typed port system.

ARCHITECTURAL ISSUE:
  audio_classifier: InputPort(data_type=list) — accepts any list
  trainer: InputPort(name="model", data_type=object) — accepts anything
  trainer: InputPort(name="dataset", data_type=object) — accepts anything
  model_builder: InputPort(name="input", data_type=object) — accepts anything

CompatibilityChecker.are_compatible(list, list) returns True (Rule 3b),
so any list-producing node can connect to AudioClassifierNode regardless
of element type. For TrainerNode, data_type=object is the universal sink
(Rule 3c), meaning any output can connect to it.

The reason for object is documented: Keras models and DatasetArtifact are
not PortDataType subclasses, so they cannot be typed in the port system.
This is a legitimate constraint, but it means the type system provides no
safety for these connections.

EVIDENCE:
  audio_classifier/nodes.py: data_type=list (description says list[AudioSample] or list[FeatureArray])
  trainer/nodes.py: data_type=object for model and dataset ports
  compat.py Rule 3c: input_type is object → accepts anything

WHY THIS IS DANGEROUS:
A pipeline that connects a list[PredictionResult] to AudioClassifierNode's
input will pass PipelineGraph validation but fail at runtime with a
confusing AttributeError inside process(). The type system's safety net
is absent for these nodes.

RECOMMENDED DIRECTION:
For AudioClassifierNode: use Union[list[AudioSample], list[FeatureArray]]
as the data_type. CompatibilityChecker handles Union types (Rules 4a-4c).
For TrainerNode: the model port cannot be typed without making Keras/PyTorch
models PortDataType subclasses. Document this explicitly in the port
description and add a runtime isinstance check at the top of process().

EXTRACTION IMPACT:
None — plugin-level concern.

DISTRIBUTED SYSTEM IMPACT:
None — but untyped ports make agent-driven graph construction (a stated
platform goal) unreliable for these nodes.
--------------------------------------------------------------------
```

---

```
--------------------------------------------------------------------
FILE:      app/core/plugins/index.py (PluginIndexClient)
BOUNDARY:  BC3 — Node Catalog (Plugin Ecosystem)
CATEGORY:  Global Mutable State — Class-Level Cache
SEVERITY:  LOW
--------------------------------------------------------------------
CURRENT RESPONSIBILITY:
PluginIndexClient._cache is a class-level variable shared across all
instances and all test runs within a process. The docstring notes "Reset
_cache to None in tests to prevent cross-test contamination" but provides
no public reset method.

EXPECTED RESPONSIBILITY:
Shared mutable state should be either encapsulated behind a clear reset
mechanism or eliminated in favor of instance-level state.

ARCHITECTURAL ISSUE:
  index.py: _cache: list[PluginIndexEntry] | None = None  (class variable)
  index.py: _cache_lock: threading.Lock = threading.Lock()  (class variable)

The cache is never invalidated during normal operation. If the remote
index changes during a long-running process, the stale cache is served
indefinitely. There is no TTL, no explicit invalidation API, and no
public reset method — only a docstring note telling test authors to
mutate the class variable directly.

EVIDENCE:
  index.py: PluginIndexClient._cache = None  (0 assignments in production code)
  index.py docstring: "Reset _cache to None in tests to prevent cross-test contamination"
  No public invalidate() or clear_cache() method

WHY THIS IS DANGEROUS:
Tests that call PluginIndexClient.fetch() will share cache state across
test cases unless each test manually resets the class variable. This is
an implicit contract that is easy to miss. In production, a stale index
cache can cause install failures for newly published plugins.

RECOMMENDED DIRECTION:
Add a class method PluginIndexClient.clear_cache() that sets _cache = None.
This makes the reset contract explicit and testable. Optionally add a TTL
(e.g. 5 minutes) to the cache so it auto-invalidates in long-running
processes.

EXTRACTION IMPACT:
Low — but class-level state makes PluginIndexClient non-extractable as a
stateless service component.

DISTRIBUTED SYSTEM IMPACT:
In a multi-worker deployment, each worker has its own class-level cache.
This is acceptable but means index updates are not propagated across
workers until each worker's cache is invalidated independently.
--------------------------------------------------------------------
```

---

```
--------------------------------------------------------------------
FILE:      app/core/run_journal.py (orchestrator.py access pattern)
BOUNDARY:  BC5 → BC6 boundary
CATEGORY:  Private Attribute Access Across BC Boundary
SEVERITY:  LOW
--------------------------------------------------------------------
CURRENT RESPONSIBILITY:
orchestrator.py accesses run._artifacts directly (line 429) to build the
list of prior artifact IDs for provenance chaining. RunManager has a
public .artifacts property that returns a thread-safe snapshot.

EXPECTED RESPONSIBILITY:
All access to RunManager state should go through its public API.

ARCHITECTURAL ISSUE:
  orchestrator.py:429: r.artifact_id for r in run._artifacts if r.node_id == _src_id

RunManager.artifacts is a @property that returns list(self._artifacts)
under a lock. The direct _artifacts access bypasses the lock, creating a
potential race condition in parallel execution where the artifacts list
is being appended concurrently.

EVIDENCE:
  orchestrator.py:429: run._artifacts (private, no lock)
  run_journal.py: @property artifacts: with self._artifacts_lock: return list(self._artifacts)
  executor.py:    run_manager.artifacts (correct — uses public property)

WHY THIS IS DANGEROUS:
In parallel execution (parallel=True), multiple nodes execute concurrently
and each calls run.register_artifact() which appends to _artifacts under
_artifacts_lock. The sequential orchestrator's direct _artifacts access