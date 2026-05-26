# Functional Review — app/core/sdk.py

**Group:** 9 — SDK & CLI
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/sdk.py
FUNCTION:    Pipeline._execute
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Core execution logic shared by run() and run_with_manager(); returns (raw_outputs, run_manager).

WHAT IT ACTUALLY DOES:
Calls get_backend().execute(...) and assigns self._last_run_id = run_manager.run_id on line ~413.
If get_backend().execute() raises an exception, the assignment on line 413 is never reached, so
self._last_run_id remains None (or its previous value from a prior run). The exception propagates
raw to the caller with no wrapping or context.

THE BUG / RISK:
After a failed run, self._last_run_id is stale (points to the previous successful run, or None).
A caller that catches the exception and then calls pipeline.pause() / pipeline.cancel() will
silently operate on the wrong run (or no-op), giving the false impression that the failed run
was controlled. Additionally, the raw exception from the backend (which may contain internal
stack frames) is surfaced directly to SDK callers with no SDK-level context message.

EVIDENCE:
Lines 393–413 (sdk.py):
    raw_outputs = get_backend().execute(
        graph,
        ...
        run_manager=run_manager,
    )
    self._last_run_id = run_manager.run_id   # ← only reached on success

REPRODUCTION SCENARIO:
    p = Pipeline([PipelineNode("some_node")])
    p.run()  # succeeds, _last_run_id = "run-001"
    p.run()  # raises mid-execution
    p.cancel()  # silently cancels run-001, not the failed run

IMPACT:
Stale run ID causes pause/resume/cancel to silently target the wrong run. No data loss, but
control operations are silently misdirected.

FIX DIRECTION:
Reset _last_run_id before the execute call, then set it in a finally block if run_manager.run_id
is available:
    self._last_run_id = None
    try:
        raw_outputs = get_backend().execute(...)
    finally:
        self._last_run_id = getattr(run_manager, "run_id", None)

--------------------------------------------------------------------
FILE:        app/core/sdk.py
FUNCTION:    Pipeline._build_ir
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Construct the backing GraphIR from the node list, using explicit edges if provided, otherwise
auto-chaining linearly.

WHAT IT ACTUALLY DOES:
When self._explicit_edges is not None, it unpacks each edge tuple as
(src_idx, src_port, dst_idx, dst_port) and indexes into ir_nodes[src_idx] and ir_nodes[dst_idx]
(lines ~276–285).

THE BUG / RISK:
There is no bounds check on src_idx or dst_idx. If a caller passes an edge tuple with an index
that is out of range for the nodes list (e.g. (0, "output", 5, "input") when there are only 3
nodes), Python raises an IndexError with a confusing traceback inside _build_ir, not a clear
validation error. This is called from __init__, so the error surfaces at Pipeline construction
time with no indication of which edge is invalid.

EVIDENCE:
Lines 276–285 (sdk.py):
    ir_edges = [
        IREdge(
            src_id=ir_nodes[src_idx].id,   # ← no bounds check
            ...
            dst_id=ir_nodes[dst_idx].id,   # ← no bounds check
            ...
        )
        for src_idx, src_port, dst_idx, dst_port in self._explicit_edges
    ]

REPRODUCTION SCENARIO:
    nodes = [PipelineNode("a"), PipelineNode("b")]
    Pipeline(nodes, edges=[(0, "output", 99, "input")])
    # → IndexError: list index out of range (no indication of which edge)

IMPACT:
Confusing IndexError instead of a clear ValueError. Callers cannot distinguish a bad edge index
from an internal bug.

FIX DIRECTION:
    for src_idx, src_port, dst_idx, dst_port in self._explicit_edges:
        if src_idx >= len(ir_nodes) or dst_idx >= len(ir_nodes):
            raise ValueError(
                f"Edge ({src_idx}, {src_port!r}, {dst_idx}, {dst_port!r}): "
                f"node index out of range (pipeline has {len(ir_nodes)} nodes)"
            )

--------------------------------------------------------------------
FILE:        app/core/sdk.py
FUNCTION:    Pipeline._build_ir
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Construct the backing GraphIR from the node list.

WHAT IT ACTUALLY DOES:
When self._explicit_edges is not None but is an empty list [], it produces a GraphIR with nodes
but no edges. This is valid for a single-node pipeline but silently produces a disconnected graph
for multi-node pipelines when the caller passes edges=[] by mistake.

THE BUG / RISK:
edges=[] is treated as "explicit empty edge list" (no auto-chaining), not as "use default
auto-chaining". A caller who passes edges=[] expecting the default linear chain gets a
disconnected graph that will fail at execution time with a confusing error, not at construction
time.

EVIDENCE:
Line 275 (sdk.py):
    if self._explicit_edges is not None:   # [] is not None → takes explicit path

REPRODUCTION SCENARIO:
    Pipeline([PipelineNode("a"), PipelineNode("b")], edges=[])
    # → GraphIR with 2 nodes, 0 edges — disconnected, no error at construction

IMPACT:
Silent wrong result: pipeline appears valid but produces no data flow between nodes.

FIX DIRECTION:
Document the behavior explicitly, or treat empty list the same as None:
    if self._explicit_edges:   # falsy empty list → auto-chain

--------------------------------------------------------------------
FILE:        app/core/sdk.py
FUNCTION:    Pipeline.validate
CATEGORY:    Contract Mismatch
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Validate the pipeline and return a list of error strings. Returns an empty list if the pipeline
is valid."

WHAT IT ACTUALLY DOES:
Step 2 calls _ir_to_pipeline_config() and PipelineGraph() inside a single try/except. If
PipelineGraph raises, only the first exception message is captured. Multiple independent errors
(e.g. two unknown node types AND a cycle) are collapsed into a single string.

THE BUG / RISK:
The docstring promises a list of error strings (implying all errors are returned), but the
implementation can return a list with a single concatenated string that contains multiple errors
merged by the exception chain. Callers who iterate the list expecting one-error-per-item will
misparse the output.

EVIDENCE:
Lines 624–633 (sdk.py):
    try:
        pipeline_cfg = _ir_to_pipeline_config(self._graph_ir)
        PipelineGraph(pipeline_cfg)
    except Exception as exc:
        errors.append(str(exc))   # ← single append regardless of how many errors

REPRODUCTION SCENARIO:
    p = Pipeline([PipelineNode("unknown_a"), PipelineNode("unknown_b")])
    errs = p.validate()
    # errs may be ["Unknown node type 'unknown_a'. ..."] — unknown_b not reported

IMPACT:
Incomplete validation output. Callers may fix one error and re-validate, not realizing there are
more.

FIX DIRECTION:
Either document that only the first error per phase is returned, or restructure to collect all
errors before returning (matching the behavior of cmd_validate in the CLI which collects all
errors).

--------------------------------------------------------------------
FILE:        app/core/sdk.py
FUNCTION:    Pipeline.to_yaml
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Serialize the pipeline to a YAML file.

WHAT IT ACTUALLY DOES:
Opens the file with `open(path, "w", encoding="utf-8")` inside a `with` block (line 562), then
calls yaml.dump(). This is correct for the happy path. However, if yaml.dump() raises (e.g. an
object in the config is not YAML-serializable), the file is left on disk as a zero-byte or
partially-written file with no cleanup.

THE BUG / RISK:
A partially-written YAML file is silently left on disk. A subsequent call to from_yaml() on that
path will fail with a confusing parse error, not a clear "serialization failed" message.

EVIDENCE:
Lines 558–563 (sdk.py):
    def to_yaml(self, path: str) -> None:
        import yaml
        config = self._to_config_dict()
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, sort_keys=False)

REPRODUCTION SCENARIO:
    class BadObj:
        pass
    p = Pipeline([PipelineNode("node_a", config={"x": BadObj()})])
    p.to_yaml("/tmp/out.yaml")
    # → RepresenterError raised, /tmp/out.yaml is 0 bytes or partial

IMPACT:
Corrupted output file left on disk. Subsequent loads fail with confusing errors.

FIX DIRECTION:
Write to a temp file and rename atomically, or delete the output file on exception:
    import tempfile, os
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.dump(config, f, sort_keys=False)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

--------------------------------------------------------------------
FILE:        app/core/sdk.py
FUNCTION:    Pipeline._from_ir
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Construct a Pipeline directly from a GraphIR without calling _build_ir(). Populates lightweight
PipelineNode shells with no validation.

WHAT IT ACTUALLY DOES:
Creates PipelineNode instances via object.__new__(PipelineNode) (bypassing __init__), then sets
pn.node_type, pn.config, and pn._ir_node directly. However, it does NOT set pn._validate (which
is a method, not state) — that is fine. But it also does NOT set any attribute that __init__
would set beyond node_type, config, and _ir_node. If PipelineNode.__init__ is ever extended to
set additional instance attributes, _from_ir will silently produce incomplete PipelineNode
objects that are missing those attributes.

THE BUG / RISK:
More concretely: the current code sets pn._ir_node on the shell nodes (line 326), but the
comment in __init__ (line 186) explicitly says "_ir_node is now set lazily by _from_ir()". This
is consistent. However, if any code path calls pn._validate() on a shell node (e.g. after
modifying pn.config), it will work correctly because _validate() is a method. The real risk is
that _from_ir() is a fragile pattern: any new attribute added to PipelineNode.__init__ must also
be added to _from_ir() or the shell nodes will be broken. There is no enforcement of this
invariant.

EVIDENCE:
Lines 318–327 (sdk.py):
    for pn, ir_node in zip(pipeline.nodes, graph.nodes):
        pn.node_type = ir_node.node_type
        pn.config = dict(ir_node.config)
        pn._ir_node = ir_node
    # No other PipelineNode attributes set

REPRODUCTION SCENARIO:
    # Add a new attribute in PipelineNode.__init__:
    #   self.metadata = {}
    # Then load via Pipeline.from_json() → pn.metadata raises AttributeError

IMPACT:
AttributeError on any code that accesses a PipelineNode attribute not set by _from_ir().
Currently latent; becomes a real bug on any PipelineNode.__init__ extension.

FIX DIRECTION:
Add a class-level _SHELL_ATTRS set or a dedicated _make_shell() classmethod on PipelineNode
that is the single source of truth for shell construction, so _from_ir() calls it instead of
duplicating the attribute list.

--------------------------------------------------------------------
FILE:        app/core/sdk.py
FUNCTION:    ArtifactCollection.lineage
CATEGORY:    Testability
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the full upstream lineage tree for artifact_id. "Never raises for unknown artifact IDs —
returns an error node dict instead."

WHAT IT ACTUALLY DOES:
Instantiates a new ProvenanceStore() on every call (line 94). ProvenanceStore is a stateful
object that reads from disk/DB. This means every lineage() call creates a new store instance,
which may re-read state from disk. If ProvenanceStore.__init__ raises (e.g. missing directory),
the exception propagates despite the docstring claiming "never raises".

EVIDENCE:
Lines 93–95 (sdk.py):
    from app.core.provenance import ProvenanceStore
    store = ProvenanceStore()
    return store.get_lineage(artifact_id)

REPRODUCTION SCENARIO:
    # GRAPHYN_PROJECT_DIR points to a non-existent path
    collection.lineage("some-id")
    # → ProvenanceStore.__init__ raises FileNotFoundError or similar

IMPACT:
Unexpected exception from a method documented as "never raises". Callers who rely on the
no-raise contract will have unhandled exceptions.

FIX DIRECTION:
Wrap in try/except and return an error dict on failure, consistent with the documented contract:
    try:
        store = ProvenanceStore()
        return store.get_lineage(artifact_id)
    except Exception as exc:
        return {"error": str(exc), "artifact_id": artifact_id}

--------------------------------------------------------------------
FILE:        app/core/sdk.py
FUNCTION:    Pipeline.subscribe
CATEGORY:    State Bug
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Register a callback to receive pipeline execution events. Returns an unsubscribe function.

WHAT IT ACTUALLY DOES:
Appends the callback to self._subscribers (line 598). The _unsubscribe closure calls
self._subscribers.remove(callback) (line 600). If the same callback is subscribed twice and
unsubscribe is called once, only the first occurrence is removed (list.remove removes the first
match). The second subscription remains active silently.

EVIDENCE:
Lines 598–601 (sdk.py):
    self._subscribers.append(callback)
    def _unsubscribe() -> None:
        try:
            self._subscribers.remove(callback)  # removes first occurrence only
        except ValueError:
            pass

REPRODUCTION SCENARIO:
    cb = lambda e: print(e)
    unsub1 = pipeline.subscribe(cb)
    unsub2 = pipeline.subscribe(cb)
    unsub1()   # removes first occurrence
    pipeline.run()  # cb still called once (second subscription remains)
    unsub2()   # removes second occurrence

IMPACT:
Duplicate callbacks fire after one unsubscribe. Low severity because it requires the same
callback object to be subscribed twice, which is unusual.

FIX DIRECTION:
Document that subscribing the same callback twice is not supported, or use a list of (id, cb)
tuples so each subscription is independently removable.

--------------------------------------------------------------------
FILE:        app/core/sdk.py
FUNCTION:    Pipeline.pause / Pipeline.resume / Pipeline.cancel
CATEGORY:    Silent Failure Risk
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
pause(): "Pause the currently running pipeline after the current node completes."
resume(): "Resume a paused pipeline run."
cancel(): "Cancel the currently running pipeline after the current node completes."

WHAT IT ACTUALLY DOES:
All three methods check self._last_run_id is None and return silently (no-op). They also silently
no-op if get_active_run() returns None (run already completed or not found). There is no
indication to the caller that the operation was a no-op.

THE BUG / RISK:
A caller who calls pipeline.pause() after a run has completed (but _last_run_id is set) will
silently get a no-op because get_active_run() returns None for completed runs. The caller has no
way to distinguish "paused successfully" from "run was already done, nothing happened".

EVIDENCE:
Lines 636–671 (sdk.py):
    def pause(self) -> None:
        if self._last_run_id is None:
            return
        run = get_active_run(self._last_run_id)
        if run is not None:
            run.pause()
        # ← no else: no signal to caller that run was not active

REPRODUCTION SCENARIO:
    collection = pipeline.run()
    pipeline.pause()  # run already completed — silent no-op, no exception, no return value

IMPACT:
Silent no-op. Callers cannot detect whether the control operation succeeded. Low severity because
the methods are documented as no-ops when inactive.

FIX DIRECTION:
Return a bool indicating whether the operation was applied, or raise if the run is not active
(breaking change). At minimum, document the silent no-op behavior explicitly.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 3 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | UNSAFE |
| Test Hostile | PARTIAL |
| Top Risk | _execute() leaves _last_run_id stale after a failed run, causing pause/resume/cancel to silently target the wrong run. |
