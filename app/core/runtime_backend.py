# app/core/runtime_backend.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Pluggable execution backend abstraction. Defines the interface
                  all backends must implement and provides the default local backend.
                  This is the CANONICAL execution entry point — all interfaces
                  (SDK, API, MCP, CLI) must call get_backend().execute() rather
                  than importing run_pipeline_ir directly.
Owns:             RuntimeBackend (ABC), LocalPythonBackend, backend registry
                  (_BACKEND_REGISTRY, _BACKEND_INSTANCES), register_backend(),
                  get_backend(), list_backends().
Public Surface:   RuntimeBackend, LocalPythonBackend, get_backend(),
                  register_backend(), list_backends()
Must NOT:         Import from app.domain or app.api at module level.
                  LocalPythonBackend imports orchestrator lazily inside execute()
                  to avoid circular imports.
Dependencies:     BC1 (ir.models — TYPE_CHECKING only), BC6 (run_journal —
                  TYPE_CHECKING only), stdlib (abc, threading).
Reason To Change: New execution backends are added (Docker, K8s, edge),
                  or the backend lifecycle protocol changes.

Usage::

    from app.core.runtime_backend import LocalPythonBackend, RuntimeBackend

    backend: RuntimeBackend = LocalPythonBackend()
    result = backend.execute(graph, run_manager=run_manager)
"""
from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.ir.models import GraphIR
    from app.core.run_journal import RunManager


class RuntimeBackend(abc.ABC):
    """Abstract base class for pipeline execution backends.

    All backends receive a validated ``GraphIR`` and optional execution
    parameters, and return the raw node-outputs dict produced by the
    final node in topological order.

    Implementations MUST be stateless — a single ``RuntimeBackend``
    instance may be used to execute multiple pipelines concurrently.
    """

    @abc.abstractmethod
    def execute(
        self,
        graph: "GraphIR",
        *,
        logger: Any = None,
        use_cache: bool = True,
        checkpoint: bool = False,
        streaming: bool = False,
        parallel: bool = False,
        max_workers: int | None = None,
        resume_run_id: str | None = None,
        include_nodes: list[str] | None = None,
        exclude_nodes: list[str] | None = None,
        input_overrides: dict | None = None,
        event_driven: bool = False,
        observer: Any = None,
        run_manager: "RunManager | None" = None,
    ) -> dict[str, Any]:
        """Execute a pipeline graph and return the final node's outputs.

        Args:
            graph: A validated ``GraphIR`` object.
            logger: Optional ``PipelineLogger`` instance.
            use_cache: Whether to use ``PipelineCache`` for node outputs.
            checkpoint: Whether to write per-node checkpoints.
            streaming: Whether to use streaming execution for streaming nodes.
            parallel: Enable parallel wave execution.
            max_workers: Max thread-pool workers for parallel mode.
            resume_run_id: Prior run ID to resume from.
            include_nodes: Subset of node IDs to execute (partial execution).
            exclude_nodes: Node IDs to skip (partial execution).
            input_overrides: Per-node, per-port input value overrides.
            event_driven: Run in event-driven mode.
            observer: Optional ``NodeObserver`` passed to each node.
            run_manager: Optional ``RunManager`` instance.

        Returns:
            The outputs dict of the final node in topological order.
        """

    @property
    def backend_id(self) -> str:
        """Short identifier for this backend (e.g. ``"local_python"``)."""
        return type(self).__name__

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class LocalPythonBackend(RuntimeBackend):
    """Default backend — executes pipelines in the local Python process.

    Delegates directly to ``run_pipeline_ir()`` (the existing executor).
    This is the backend used by all current interfaces.

    Note: The backend instance itself is stateless. Each ``execute()`` call
    creates its own ``RunManager`` internally (if none is provided), which
    is stateful and manages run directories, logs, and artifacts.
    """

    def execute(
        self,
        graph: "GraphIR",
        *,
        logger: Any = None,
        use_cache: bool = True,
        checkpoint: bool = False,
        streaming: bool = False,
        parallel: bool = False,
        max_workers: int | None = None,
        resume_run_id: str | None = None,
        include_nodes: list[str] | None = None,
        exclude_nodes: list[str] | None = None,
        input_overrides: dict | None = None,
        event_driven: bool = False,
        observer: Any = None,
        run_manager: "RunManager | None" = None,
    ) -> dict[str, Any]:
        """Execute via the local ``run_pipeline_ir`` function."""
        from app.core.orchestrator import run_pipeline_ir  # lazy — avoids circular import

        return run_pipeline_ir(
            graph,
            logger=logger,
            use_cache=use_cache,
            checkpoint=checkpoint,
            streaming=streaming,
            parallel=parallel,
            max_workers=max_workers,
            resume_run_id=resume_run_id,
            include_nodes=include_nodes,
            exclude_nodes=exclude_nodes,
            input_overrides=input_overrides,
            event_driven=event_driven,
            observer=observer,
            run_manager=run_manager,
        )

    @property
    def backend_id(self) -> str:
        return "local_python"


# ── Backend registry ──────────────────────────────────────────────────────────

_BACKEND_REGISTRY: dict[str, type[RuntimeBackend]] = {
    "local_python": LocalPythonBackend,
}

# Singleton cache: backend_id → instance.
# Stateless backends (like LocalPythonBackend) are safe to share across calls.
# Future connection-holding backends (Docker, K8s) benefit from reuse.
_BACKEND_INSTANCES: dict[str, RuntimeBackend] = {}
_BACKEND_INSTANCES_LOCK = __import__("threading").Lock()


def register_backend(backend_id: str, backend_class: type[RuntimeBackend]) -> None:
    """Register a custom backend class under ``backend_id``.

    Allows plugins and third-party code to add new execution backends
    without modifying core platform code.

    Args:
        backend_id: Unique string identifier (e.g. ``"docker"``, ``"k8s"``).
        backend_class: A concrete subclass of ``RuntimeBackend``.

    Raises:
        TypeError: If ``backend_class`` is not a subclass of ``RuntimeBackend``.
    """
    if not (isinstance(backend_class, type) and issubclass(backend_class, RuntimeBackend)):
        raise TypeError(
            f"backend_class must be a subclass of RuntimeBackend, got {backend_class!r}"
        )
    _BACKEND_REGISTRY[backend_id] = backend_class
    # Invalidate any cached instance so the new class is used on next get_backend()
    with _BACKEND_INSTANCES_LOCK:
        _BACKEND_INSTANCES.pop(backend_id, None)


def get_backend(backend_id: str = "local_python") -> RuntimeBackend:
    """Return a cached backend instance by ID.

    Instances are created once and reused across calls. This avoids the
    overhead of re-instantiating connection-holding backends (e.g. Docker,
    Kubernetes) on every pipeline execution.

    Args:
        backend_id: The registered backend identifier (default: ``"local_python"``).

    Returns:
        A ``RuntimeBackend`` instance (shared singleton per backend_id).

    Raises:
        KeyError: If ``backend_id`` is not registered.
    """
    if backend_id not in _BACKEND_REGISTRY:
        available = sorted(_BACKEND_REGISTRY)
        raise KeyError(
            f"Unknown runtime backend '{backend_id}'. "
            f"Available backends: {available}"
        )
    with _BACKEND_INSTANCES_LOCK:
        if backend_id not in _BACKEND_INSTANCES:
            _BACKEND_INSTANCES[backend_id] = _BACKEND_REGISTRY[backend_id]()
        return _BACKEND_INSTANCES[backend_id]


def list_backends() -> list[str]:
    """Return a sorted list of all registered backend IDs."""
    return sorted(_BACKEND_REGISTRY)
