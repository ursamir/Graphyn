# R5 · R6 · R7 · R8 — Runtime: Lifecycle, Retry, Streaming, Observability

← [Back to master requirements](requirements.md)

---

## Requirement 5: Node Lifecycle Hooks

**User Story:** As a pipeline operator, I want nodes to support lifecycle hooks so that I can perform setup, teardown, and error recovery without polluting the `process` method.

### Acceptance Criteria

1. THE `Node` SHALL define the following lifecycle methods with no-op default implementations:
   - `setup(self) -> None`
   - `on_start(self) -> None`
   - `on_end(self) -> None`
   - `on_error(self, exc: Exception) -> None`
   - `teardown(self) -> None`
2. `setup(self)` is called by the pipeline runtime once per node instance, after instantiation and before the first call to `on_start()`. It is NOT called by `Node.__init__` itself. Use it for expensive one-time initialisation (e.g. loading model weights, opening file handles).
3. For each node execution, the pipeline runtime SHALL call `on_start()` immediately before `process()`, and `on_end()` immediately after `process()` returns without raising.
4. WHEN `process()` raises an exception, the runtime SHALL call `on_error(exc)` before propagating the exception.
5. WHEN `on_start()` raises an exception, the runtime SHALL call `on_error(exc)` and SHALL NOT call `process()`.
6. `teardown(self)` is called by the pipeline runtime once per node instance: after the node's final `on_end()` call, or after `on_error()` if the node failed and will not be retried. Use it for releasing resources (e.g. closing file handles, freeing GPU memory).

---

## Requirement 6: Retry Policy

**User Story:** As a pipeline operator, I want nodes to automatically retry on transient failures, so that intermittent I/O or network errors do not abort the entire pipeline.

### Acceptance Criteria

1. THE `Node` SHALL expose a `retry_policy: RetryPolicy | None` class-level attribute, defaulting to `None` (no retries).
2. `RetryPolicy` SHALL be a Pydantic model with fields:
   - `max_attempts: int` — minimum 1. Total number of attempts including the first.
   - `backoff_seconds: float` — minimum 0. Base wait time in seconds.
   - `backoff_multiplier: float` — minimum 1.0. Multiplier applied per retry.
3. WHEN `retry_policy` is set and `process()` raises an exception, the runtime SHALL retry `process()` up to `max_attempts - 1` additional times. The wait before retry `i` (0-indexed) is `backoff_seconds * (backoff_multiplier ** i)` seconds. Examples: wait before 2nd attempt = `backoff_seconds * 1.0`; wait before 3rd attempt = `backoff_seconds * backoff_multiplier`. `on_start()` SHALL be called again immediately before each retry; `on_end()` SHALL NOT be called between retries.
4. WHEN all retry attempts are exhausted, the runtime SHALL call `on_error(exc)` with the final exception, call `teardown()`, and re-raise the exception.
5. WHEN `process()` succeeds on a retry attempt, the runtime SHALL call `on_end()` normally and SHALL log the number of attempts taken at `INFO` level.

---

## Requirement 7: Streaming / Async Node Support

**User Story:** As a pipeline author, I want to define nodes that yield output items incrementally, so that large datasets can be processed without loading everything into memory at once.

### Acceptance Criteria

1. THE `Node` SHALL support an optional `process_stream(self, inputs: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]` method for streaming output. The `inputs` dict follows the same multi-port convention as `process`.
2. WHEN a node overrides `process_stream`, the runtime SHALL call `process_stream` instead of `process` when the pipeline is run in streaming mode. Streaming mode is activated by calling `run_pipeline(..., streaming=True)`.
3. WHEN a node defines only `process` (not `process_stream`), the runtime SHALL wrap `process` in a single-item async generator: call `process(inputs)` synchronously and yield the result once.
4. THE `Node` SHALL expose `is_streaming: bool` as a class-level property that is `True` when `process_stream` is overridden (i.e. `type(node).process_stream is not Node.process_stream`) and `False` otherwise.
5. WHEN two streaming nodes are connected, the runtime SHALL pipe the async generator output of node N directly into the `process_stream` input of node N+1 using `async for item in node_n.process_stream(inputs): ...`, rather than collecting all items into a list first.
6. For multi-port streaming nodes with `"multi"` cardinality input ports, the runtime SHALL collect one item from each upstream async generator per iteration step and pass them together as the `inputs` dict for that step.

---

## Requirement 8: Node Observability

**User Story:** As a platform engineer, I want nodes to emit structured events during execution, so that I can collect metrics, traces, and logs without modifying node business logic.

### Acceptance Criteria

1. THE `Node` SHALL accept an optional `observer: NodeObserver | None` parameter at construction time, defaulting to `None`.
2. `NodeObserver` SHALL define the following abstract interface:
   - `on_node_start(node_type: str, run_id: str) -> None`
   - `on_node_end(node_type: str, run_id: str, duration_s: float, input_counts: dict[str, int], output_counts: dict[str, int]) -> None`
   - `on_node_error(node_type: str, run_id: str, exc: Exception) -> None`
   
   `input_counts` maps each input port name to the number of items received (1 for `"single"` cardinality, N for `"multi"` cardinality). `output_counts` maps each output port name to the number of items produced.
3. WHEN an observer is attached, the `Node` SHALL call the corresponding observer method at each lifecycle event.
4. THE `System` SHALL provide a `LoggingObserver` concrete implementation that writes one structured JSON line per event to a Python `logging.Logger`. Each line SHALL be a JSON object: `{"event": "<event_name>", "node_type": "...", "run_id": "...", <event-specific fields>}` where `<event_name>` is `"node_start"`, `"node_end"`, or `"node_error"`.
5. THE `System` SHALL provide a `CompositeObserver` that fans out all events to a list of child `NodeObserver` instances, so that multiple observers can be attached simultaneously.
