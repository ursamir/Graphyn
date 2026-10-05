# app/core/execution/node_executor.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Drive a single node through its full lifecycle with retry.
Owns:             NodeExecutor class — setup/teardown, on_start→process→on_end
                  sequencing, exponential back-off retry, streaming execution;
                  IR 1.3 per-node retry (``_graphyn_retry``) and on_error
                  route/continue (``_graphyn_on_error``, stamped by the
                  planner) with node_retry / node_error_routed /
                  node_failed_continued events via the progress sink.
Public Surface:   NodeExecutor(node, run_id), .setup(), .teardown(),
                  .execute(inputs) -> dict, .execute_stream(inputs) -> AsyncGen,
                  .request_cancel(), .set_cancel_check(), .is_cancel_requested,
                  .set_progress_sink(node_id, sink) (node_progress context
                  bound around process(); see app.core.nodes.progress)
Must NOT:         Understand pipeline topology, import from app.domain,
                  import from orchestrator or executor (no intra-BC5 cycles).
Dependencies:     BC2 (nodes.base, nodes.observers, nodes.retry, nodes.progress).
Reason To Change: Node lifecycle protocol changes, retry policy evolves,
                  or streaming execution semantics change.
"""
from __future__ import annotations

import logging
import time
from typing import Any, AsyncGenerator

from app.core.nodes.base import Node
from app.core.nodes.metadata import stable_node_type
from app.core.nodes.observers import NodeObserver
from app.core.nodes.retry import RetryPolicy

ERROR_PORT_DEFAULT = "error"  # mirrors app.core.ir.models.ERROR_PORT_DEFAULT

log = logging.getLogger(__name__)


def _count_port_items(port_data: Any) -> int:
    """Return the number of items on a port (1 for single value, N for list, 0 for None)."""
    if isinstance(port_data, list):
        return len(port_data)
    if port_data is None:
        return 0
    return 1



def _continue_error_output(node: Node, exc: Exception) -> dict[str, Any] | None:
    """If the node opts into error-port continuation, return an error payload.

    Used by error_catch / on_error=continue_error_output so failures can flow
    downstream instead of aborting the DAG.
    """
    cfg = getattr(node, "config", None)
    port = getattr(cfg, "on_error_port", None)
    mode = getattr(cfg, "on_error", None)
    if not port:
        return None
    if mode in ("fail", "raise"):
        return None
    if mode not in (None, "", "continue_error_output", "continue"):
        return None
    return {
        str(port): {
            "ok": False,
            "error_type": getattr(exc, "error_type", None) or type(exc).__name__,
            "message": str(exc),
        }
    }


def _error_type(exc: BaseException | None) -> str:
    if exc is None:
        return "Exception"
    return str(getattr(exc, "error_type", None) or type(exc).__name__)


def _short_message(exc: BaseException | None, limit: int = 2000) -> str:
    text = str(exc) if exc is not None else ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _ir_on_error(node: Any) -> dict[str, Any] | None:
    """IR 1.3 on_error policy stamped by PipelineGraph (plain dict) or None."""
    pol = getattr(node, "_graphyn_on_error", None)
    return pol if isinstance(pol, dict) else None


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return any("timeout" in cls.__name__.lower() for cls in type(exc).__mro__)


class _EffectiveRetry:
    """Retry decisions for one node: IR 1.3 ``retry`` overrides RetryPolicy."""

    def __init__(
        self,
        max_attempts: int,
        wait_fn: Any,
        retryable_fn: Any,
    ) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self._wait = wait_fn
        self._retryable = retryable_fn

    @classmethod
    def for_node(cls, node: Any) -> "_EffectiveRetry":
        ir = getattr(node, "_graphyn_retry", None)
        if isinstance(ir, dict):
            backoff = max(0.0, float(ir.get("backoff_s") or 0.0))
            cap = max(0.0, float(ir.get("max_backoff_s") if ir.get("max_backoff_s") is not None else 60.0))
            on = {str(x) for x in (ir.get("on") or ["exception"])}

            def _wait(i: int) -> float:
                return min(backoff * (2 ** max(0, int(i))), cap)

            def _retryable(exc: BaseException) -> bool:
                if "exception" in on:
                    return True
                return "timeout" in on and _is_timeout(exc)

            return cls(int(ir.get("max_attempts") or 1), _wait, _retryable)
        policy: RetryPolicy | None = getattr(node, "retry_policy", None)
        if policy is None:
            return cls(1, lambda i: 0.0, lambda exc: True)
        return cls(policy.max_attempts, policy.wait_before_attempt, policy.is_retryable)

    def wait_before_attempt(self, attempt_index: int) -> float:
        try:
            return float(self._wait(attempt_index) or 0.0)
        except Exception:
            return 0.0

    def is_retryable(self, exc: BaseException) -> bool:
        try:
            return bool(self._retryable(exc))
        except Exception:
            return True


class NodeExecutor:
    """Drives a single node through setup → (on_start → process → on_end)* → teardown.

    Handles:
      - Lifecycle hook sequencing
      - Retry with exponential back-off (via node.retry_policy)
      - Observer event emission
      - Streaming vs. batch execution

    Observer contract
    -----------------
    ``Node.on_start()``, ``Node.on_end()``, and ``Node.on_error()`` in
    ``base.py`` already call the observer internally.  This executor does NOT
    call the observer directly — doing so would fire every event twice (BUG-1
    fix).  The executor's only job is to call the lifecycle hooks in the right
    order; the hooks own the observer notification.

    Usage::

        executor = NodeExecutor(node, run_id="run-abc")
        executor.setup()
        outputs = executor.execute({"input": data})
        executor.teardown()
    """

    def __init__(self, node: Node, run_id: str = "") -> None:
        self._node = node
        self._run_id = run_id
        self._setup_done = False
        # True once teardown() ran after a setup — makes teardown idempotent
        # and lets execute() transparently re-setup a node that was torn down
        # by a failed attempt (event-driven mode reuses executors per event).
        self._torn_down = False
        self._cancel_requested = False
        self._cancel_check: Any = None  # optional Callable[[], bool]
        # node_progress side-channel (app.core.nodes.progress): set by the
        # orchestrator so emit_node_progress() inside process() reaches the
        # run journal / NDJSON stream. None → progress is a no-op.
        self._progress_node_id: str = ""
        self._progress_sink: Any = None  # optional Callable[[dict], None]
        # Set when execute() returns via IR/Config failure policy (route/continue).
        # Orchestrator must not cache those outputs — a later hit would replay the
        # error branch instead of re-running the node.
        self.failure_policy_applied: bool = False

    def setup(self) -> None:
        """Call node.setup() once before the first execution. Subsequent calls are no-ops.

        Isolated plugin nodes skip host ``setup()`` so ML stacks (TF/Torch/ONNX)
        are not imported in the platform process. Worker ``setup()`` runs inside
        the plugin venv instead.
        """
        if not self._setup_done:
            if self._isolated_spec() is None:
                self._node.setup()
            self._setup_done = True
            self._torn_down = False

    def teardown(self) -> None:
        """Call node.teardown() to release resources (idempotent)."""
        if self._torn_down:
            return
        self._torn_down = True
        self._setup_done = False
        self._node.teardown()

    def request_cancel(self) -> None:
        """Cooperative cancel: stop between retries / kill isolated subprocess."""
        self._cancel_requested = True

    def set_cancel_check(self, cancel_check: Any) -> None:
        """Optional callable polled during execute / isolated subprocess wait."""
        self._cancel_check = cancel_check

    def set_progress_sink(self, node_id: str, sink: Any) -> None:
        """Bind the node_progress sink (called with a full event dict)."""
        self._progress_node_id = str(node_id or "")
        self._progress_sink = sink

    def is_cancel_requested(self) -> bool:
        """True if request_cancel() was called or cancel_check() returned True."""
        if self._cancel_requested:
            return True
        check = self._cancel_check
        if check is not None:
            try:
                if check():
                    self._cancel_requested = True
                    return True
            except Exception:
                pass
        return False

    def _raise_if_cancelled(self) -> None:
        if self.is_cancel_requested():
            raise RuntimeError("cancelled by control plane")

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in short slices so cancel can abort retry back-off."""
        if seconds <= 0:
            return
        deadline = time.monotonic() + float(seconds)
        while True:
            self._raise_if_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.25, remaining))

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute the node synchronously with full lifecycle + retry.

        Args:
            inputs: Dict mapping input port names to their values.

        Returns:
            Dict mapping output port names to their produced values. With an
            IR ``on_error`` policy a final failure returns ``{}`` (continue)
            or ``{<error port>: {...}}`` (route) instead of raising.

        Raises:
            Exception: The last exception raised by process() after all retry
                       attempts are exhausted (no on_error policy).

        Warning:
            Must not be called directly from a coroutine — use
            ``loop.run_in_executor()`` to avoid blocking the event loop during
            retry back-off (``time.sleep()`` is used for back-off delays).
        """
        node = self._node
        self.failure_policy_applied = False
        if self._torn_down and not self._setup_done:
            # A previous failure tore the node down; re-acquire resources
            # instead of running process() against a torn-down node.
            self.setup()
        retry = _EffectiveRetry.for_node(node)
        max_attempts = retry.max_attempts
        node_type = stable_node_type(node)

        last_exc: Exception | None = None
        attempts_made = 0

        for attempt in range(max_attempts):
            self._raise_if_cancelled()
            if attempt > 0:
                wait = retry.wait_before_attempt(attempt - 1)
                self._emit_event(
                    "node_retry",
                    message=(
                        f"retrying (attempt {attempt + 1}/{max_attempts}) after "
                        f"{_error_type(last_exc)}"
                    ),
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    wait_s=round(float(wait), 3),
                    error_type=_error_type(last_exc),
                    error=_short_message(last_exc),
                )
                if wait > 0:
                    self._interruptible_sleep(wait)

            attempts_made = attempt + 1
            try:
                # on_start() calls observer.on_node_start() internally (base.py).
                # Do NOT call observer directly here — that would fire the event twice.
                node._run_id = self._run_id
                node._current_run_id = self._run_id  # type: ignore[attr-defined]
                node.on_start()
            except Exception as exc:
                # on_error() calls observer.on_node_error() internally.
                node.on_error(exc)
                last_exc = exc
                if not retry.is_retryable(exc):
                    return self._final_failure(exc, attempts_made)
                continue

            t0 = time.perf_counter()
            try:
                self._raise_if_cancelled()
                outputs = self._process(node, inputs)
                # Guard: a node that forgets to return its outputs dict would
                # cause an AttributeError on outputs.items() below, which would
                # bypass on_error() and the retry loop entirely.  Treat None as
                # an empty dict so the lifecycle completes cleanly.
                if outputs is None:
                    outputs = {}
                duration = time.perf_counter() - t0

                # on_end() calls observer.on_node_end() internally.
                # SA-NE2: pass duration and port counts via the node's _last_duration/
                # _last_counts attributes so base.py can forward them to the observer.
                # These are side-channel attributes on a foreign object — a known
                # quality issue (SA-NE2). The proper fix is to add explicit parameters
                # to on_end(duration, input_counts, output_counts) in a future refactor.
                node._last_duration = duration  # type: ignore[attr-defined]
                node._last_input_counts = {k: _count_port_items(v) for k, v in inputs.items()}  # type: ignore[attr-defined]
                node._last_output_counts = {k: _count_port_items(v) for k, v in outputs.items()}  # type: ignore[attr-defined]
                node.on_end()
            except Exception as exc:
                # on_error() calls observer.on_node_error() internally.
                node.on_error(exc)
                last_exc = exc
                # SA-NE4: if the policy marks this exception as non-retryable,
                # surface it immediately without consuming remaining attempts.
                if not retry.is_retryable(exc):
                    return self._final_failure(exc, attempts_made)
                continue

            if attempt > 0:
                log.info("Node '%s' succeeded after %d attempt(s).", node_type, attempt + 1)

            return outputs

        # All attempts exhausted.
        # on_error() was already called inside the loop on the last failed attempt.
        # Do NOT call it again here — that would fire the event twice (BUG-6 fix).
        assert last_exc is not None
        return self._final_failure(last_exc, attempts_made)

    def _final_failure(self, exc: Exception, attempts: int) -> dict[str, Any]:
        """Apply the failure policy after the last attempt: route / continue / raise.

        Precedence: IR ``on_error`` route/continue (any node) → legacy Config
        ``on_error_port`` continuation → re-raise. IR ``mode=fail`` (or unset)
        still allows Config continuation so graphs that only set Config keep
        working; do not set both IR route/continue and Config ``on_error_port``
        on the same node (validator warns). Cancellation is never routed or
        swallowed.
        """
        node = self._node
        if not self.is_cancel_requested():
            policy = _ir_on_error(node)
            mode = (policy or {}).get("mode")
            if mode == "route":
                port = str((policy or {}).get("port") or ERROR_PORT_DEFAULT)
                payload = {
                    "ok": False,
                    "error_type": _error_type(exc),
                    "message": _short_message(exc),
                    "node_id": self._node_id(),
                    "node_type": stable_node_type(node),
                    "attempt": int(attempts),
                }
                self._emit_event(
                    "node_error_routed",
                    message=f"failure routed to port '{port}': {_error_type(exc)}",
                    port=port,
                    attempt=int(attempts),
                    error_type=payload["error_type"],
                    error=payload["message"],
                )
                self.failure_policy_applied = True
                return {port: payload}
            if mode == "continue":
                self._emit_event(
                    "node_failed_continued",
                    message=f"failed ({_error_type(exc)}); on_error=continue — run continues",
                    attempt=int(attempts),
                    error_type=_error_type(exc),
                    error=_short_message(exc),
                )
                self.failure_policy_applied = True
                return {}
            # IR fail / unset: legacy Config on_error_port may still soft-continue.
            continued = _continue_error_output(node, exc)
            if continued is not None:
                self.failure_policy_applied = True
                return continued
        # SA-NE1 fix: only call teardown() if setup() was previously called.
        if self._setup_done:
            self.teardown()
        raise exc

    def _node_id(self) -> str:
        return str(
            self._progress_node_id or getattr(self._node, "_graphyn_node_id", "") or ""
        )

    def _emit_event(self, event_type: str, **fields: Any) -> None:
        """Journal a retry / routed-error event through the progress sink.

        The orchestrator's sink records it in logs.json + the NDJSON stream
        (``type`` is preserved) and mirrors the latest event per node into
        ``meta.json["node_progress"]``. Never raises.
        """
        event = {
            "type": event_type,
            "node_id": self._node_id(),
            "node_type": stable_node_type(self._node),
            "run_id": self._run_id,
            **fields,
        }
        log.info("%s node=%s %s", event_type, event["node_id"], fields.get("message", ""))
        sink = self._progress_sink
        if sink is None:
            return
        try:
            sink(event)
        except Exception:
            log.debug("node event sink failed", exc_info=True)

    def _node_type_name(self, node: Node) -> str | None:
        name = stable_node_type(node)
        return name or None

    def _isolated_spec(self):
        """Return IsolatedPluginSpec or None. Isolated types fail closed (H1)."""
        node = self._node
        node_type = self._node_type_name(node)
        marked = bool(getattr(type(node), "_graphyn_isolated", False))
        spec = None
        lookup_error: Exception | None = None
        try:
            from app.core.plugins.runtime_registry import get_runtime_registry

            if node_type:
                spec = get_runtime_registry().get_for_node(str(node_type))
        except Exception as exc:  # import / registry failures
            lookup_error = exc
            spec = None

        if spec is not None:
            return spec
        if marked:
            raise RuntimeError(
                f"Isolated node type {node_type!r} is not registered in "
                "PluginRuntimeRegistry; refusing in-process fallback."
            ) from lookup_error
        return None

    def _process(self, node: Node, inputs: dict[str, Any]) -> dict[str, Any]:
        """Run ``node.process`` in-process or via an isolated plugin worker."""
        from app.core.nodes.progress import progress_context

        with progress_context(
            self._progress_node_id, stable_node_type(node), self._progress_sink
        ):
            return self._process_inner(node, inputs)

    def _process_inner(self, node: Node, inputs: dict[str, Any]) -> dict[str, Any]:
        from app.core.plugins.hydrate import coerce_node_inputs
        from app.core.paths.write_paths import ensure_node_write_dirs

        inputs = coerce_node_inputs(inputs, type(node))
        ensure_node_write_dirs(node)
        spec = self._isolated_spec()
        if spec is not None:
            from app.core.plugins.isolated_executor import run_isolated_node

            node_type = self._node_type_name(node) or spec.node_types[0]
            config = {}
            raw_cfg = getattr(node, "config", None)
            if raw_cfg is not None:
                if hasattr(raw_cfg, "model_dump"):
                    # exclude_none: isolated workers re-validate with pydantic;
                    # explicit nulls from stub/schema padding must not override Field defaults.
                    config = raw_cfg.model_dump(exclude_none=True)
                elif isinstance(raw_cfg, dict):
                    config = dict(raw_cfg)
            seed = int(getattr(node, "seed", 42) or 42)
            result = run_isolated_node(
                spec,
                node_type=str(node_type),
                config=config,
                seed=seed,
                inputs=inputs,
                cancel_check=self.is_cancel_requested,
            )
            # Worker drained publish_files into the envelope — restore onto the
            # host Node so executor/orchestrator can register file_tree artifacts.
            node.accept_published_file_trees(result.published_file_trees)
            return result.outputs
        return node.process(inputs)

    async def execute_stream(
        self, inputs: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute the node in streaming mode.

        on_start() and on_end() (which call the observer internally) are called
        once per stream invocation. on_end() fires in a finally block so it
        fires even when the caller breaks out of the async for early.

        SA-NE3: Streaming nodes do not use RetryPolicy. This is an intentional
        asymmetry — wrapping an async generator in a retry loop requires
        re-entering the generator from the start, which is not always safe for
        stateful streaming nodes. If retry is needed, override execute_stream
        in the node subclass and implement the retry loop there.
        """
        node = self._node
        if self._isolated_spec() is not None:
            raise RuntimeError(
                f"Isolated node type {self._node_type_name(node)!r} cannot "
                "stream in-process; use NodeExecutor.execute() (worker)."
            )
        from app.core.paths.write_paths import ensure_node_write_dirs

        node._run_id = self._run_id
        node._current_run_id = self._run_id  # type: ignore[attr-defined]
        # Cooperative cancel (DIST-CANCEL-2): honour request_cancel / cancel_check
        # before start and between stream items. Does not interrupt mid-yield
        # inside process_stream (same cooperative model as sync process()).
        self._raise_if_cancelled()
        started = False
        try:
            ensure_node_write_dirs(node)
            node.on_start()
            started = True
            async for item in node.process_stream(inputs):
                self._raise_if_cancelled()
                yield item
        except Exception as exc:
            node.on_error(exc)
            raise
        finally:
            if started:
                node.on_end()
