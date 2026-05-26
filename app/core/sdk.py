"""
Bounded Context:  Application Layer — SDK
Responsibility:   Provide the Python SDK for programmatic pipeline definition
                  and execution. The primary interface for Python callers.
Owns:             Pipeline, PipelineNode, ArtifactCollection.
Public Surface:   Pipeline (run, run_with_manager, from_json, from_yaml, to_ir,
                  to_json, subscribe, validate, pause, resume, cancel);
                  PipelineNode; ArtifactCollection.
Must NOT:         Contain execution logic — delegates entirely to
                  get_backend().execute() and RunManager. Must not import from
                  app.domain or app.api at module level.
Dependencies:     BC1 (ir.models, ir.loader), BC5 (runtime_backend — lazy),
                  BC6 (run_journal — lazy, provenance — lazy),
                  BC3 (registry_runtime — lazy via PipelineNode._validate),
                  app.core.logger (lazy), app.core.plugins.manager (lazy).
Reason To Change: SDK public API evolves (new Pipeline methods, new
                  ArtifactCollection accessors), or execution delegation
                  strategy changes.
"""
from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from app.core.artifact_store import ArtifactRecord
    from app.core.ir.models import GraphIR

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ArtifactCollection  (req-04 §1)
# ---------------------------------------------------------------------------


class ArtifactCollection:
    """Wraps the raw pipeline output dict with typed artifact access.

    Returned by ``Pipeline.run()`` instead of a plain dict. Fully
    backward-compatible: all dict-like access patterns continue to work.

    NOT a dict subclass — ``isinstance(collection, dict)`` is ``False``.

    Requirements: req-04 §1
    """

    def __init__(
        self,
        artifacts: list[ArtifactRecord],
        run_id: str,
        _raw: dict,
    ) -> None:
        self.artifacts = artifacts
        self.run_id = run_id
        self._raw = _raw

    # ------------------------------------------------------------------
    # Artifact access methods
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return ArtifactRecord for ``key`` if found by node_id, else ``default``.

        Also serves as the dict-compatible ``get(key, default)`` — checks
        ``_raw`` first, then falls back to artifact lookup by ``node_id``.

        Requirements: req-04 §1.3, §1.4
        """
        if key in self._raw:
            return self._raw[key]
        for record in self.artifacts:
            if record.node_id == key:
                return record
        return default

    def get_by_type(self, artifact_type: str) -> list[ArtifactRecord]:
        """Return all artifacts whose ``artifact_type`` matches.

        Requirements: req-04 §1.3
        """
        return [r for r in self.artifacts if r.artifact_type == artifact_type]

    def lineage(self, artifact_id: str) -> dict:
        """Return the full upstream lineage tree for ``artifact_id``.

        Delegates to ``ProvenanceStore.get_lineage()``. Never raises for
        unknown artifact IDs — returns an error node dict instead.

        Requirements: req-04 §4
        """
        from app.core.provenance import ProvenanceStore  # lazy — avoids circular dep
        store = ProvenanceStore()
        return store.get_lineage(artifact_id)

    # ------------------------------------------------------------------
    # Dict protocol (backward compatibility)  (req-04 §1.4)
    # ------------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self._raw[key]

    def __contains__(self, key: object) -> bool:
        return key in self._raw

    def keys(self):
        return self._raw.keys()

    def items(self):
        return self._raw.items()

    def values(self):
        return self._raw.values()

    # ------------------------------------------------------------------
    # Repr  (req-04 §1.5)
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"ArtifactCollection(run_id={self.run_id!r}, artifacts={len(self.artifacts)})"


# ---------------------------------------------------------------------------
# Module-level subscriber logger (S-05 fix — defined once, not per call)
# ---------------------------------------------------------------------------

class _SubscriberLogger:
    """PipelineLogger subclass that forwards every event to registered callbacks.

    Defined at module level so Python does not create a new class object on
    every ``_make_subscriber_logger`` call.

    Properly subclasses PipelineLogger so that internal calls to ``self._emit``
    within PipelineLogger methods (node_start, node_end, etc.) go through the
    overridden ``_emit`` and reach subscribers.
    """
    pass  # Filled in lazily below to avoid importing PipelineLogger at module load time


def _make_subscriber_logger_class():
    """Build the _SubscriberLogger class inheriting from PipelineLogger.

    Called once on first use to avoid a circular import at module load time.
    """
    from app.core.logger import PipelineLogger  # noqa: PLC0415

    class _SL(PipelineLogger):
        def __init__(self, subscribers: list, queue=None) -> None:
            super().__init__(queue=queue)
            self._subscribers = subscribers

        def _emit(self, event: dict) -> None:
            super()._emit(event)
            for cb in list(self._subscribers):
                try:
                    cb(event)
                except Exception:
                    log.warning(
                        "Pipeline subscriber %r raised an exception on event %r",
                        cb,
                        event.get("type"),
                        exc_info=True,
                    )

    return _SL


_SubscriberLoggerClass = None  # lazily initialized


class PipelineNode:
    """Represents a single pipeline node with a type and configuration.

    Validates config against the node's Pydantic Config model on instantiation.
    Internally holds an IRNode object (Req 2.2.1).
    """

    def __init__(self, node_type: str, config: dict[str, Any] | None = None) -> None:
        self.node_type = node_type
        self.config = config or {}
        self._validate()
        # ARCH-5 fix: do NOT set self._ir_node here with a hardcoded "_0" suffix.
        # The correct IRNode (with the actual positional index) is produced by
        # to_ir_node(node_index) and used by Pipeline._build_ir(). Any code that
        # accessed pn._ir_node.id directly was getting the wrong ID.
        # _ir_node is now set lazily by _from_ir() when loading from an existing IR.

    def _validate(self) -> None:
        """Validate config using registry.get_class() + Config.model_validate()."""
        from app.core.registry_runtime import get_registry
        import pydantic

        registry = get_registry()

        try:
            node_class = registry.get_class(self.node_type)
        except Exception:
            available = sorted(m.node_type for m in registry.list_nodes())
            raise ValueError(
                f"Unknown node type '{self.node_type}'. "
                f"Available types: {', '.join(available)}"
            )

        try:
            node_class.Config.model_validate(self.config)
        except pydantic.ValidationError as exc:
            raise ValueError(
                f"Invalid config for node '{self.node_type}': {exc}"
            ) from exc

    def to_ir_node(self, node_index: int) -> "IRNode":
        """Return an IRNode with the correct positional id (Req 2.2.2)."""
        from app.core.ir.models import IRNode
        return IRNode(
            id=f"{self.node_type}_{node_index}",
            node_type=self.node_type,
            config=self.config,
        )

    def to_dict(self) -> dict:
        """Return legacy dict representation."""
        return {"type": self.node_type, "config": dict(self.config)}


class Pipeline:
    """Represents a complete pipeline of nodes.

    Internally backed by a GraphIR object (Req 2.4.1).
    Public API is unchanged from the previous implementation.
    """

    def __init__(
        self,
        nodes: list[PipelineNode],
        seed: int = 42,
        name: str = "pipeline",
        description: str = "",
        edges: "list[tuple[str, str, str, str]] | None" = None,
    ) -> None:
        """Create a Pipeline.

        Args:
            nodes:       List of PipelineNode objects.
            seed:        Random seed for reproducibility.
            name:        Pipeline name.
            description: Pipeline description.
            edges:       Optional explicit edge list for non-linear pipelines.
                         Each edge is a 4-tuple:
                         ``(src_node_index, src_port, dst_node_index, dst_port)``
                         where the index is the 0-based position in ``nodes``.
                         When ``None`` (default), edges are auto-chained linearly.
        """
        self.nodes = nodes
        self.seed = seed
        self.name = name
        self.description = description
        self._explicit_edges = edges
        self._subscribers: list = []
        self._last_run_id: str | None = None
        self._graph_ir = self._build_ir()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_ir(self) -> "GraphIR":
        """Construct the backing GraphIR from the node list."""
        from app.core.ir.loader import CURRENT_IR_VERSION
        from app.core.ir.models import GraphIR, IREdge, IRMetadata

        ir_nodes = [node.to_ir_node(i) for i, node in enumerate(self.nodes)]

        if self._explicit_edges is not None:
            ir_edges = [
                IREdge(
                    src_id=ir_nodes[src_idx].id,
                    src_port=src_port,
                    dst_id=ir_nodes[dst_idx].id,
                    dst_port=dst_port,
                )
                for src_idx, src_port, dst_idx, dst_port in self._explicit_edges
            ]
        else:
            ir_edges = [
                IREdge(
                    src_id=ir_nodes[i].id,
                    src_port="output",
                    dst_id=ir_nodes[i + 1].id,
                    dst_port="input",
                )
                for i in range(len(ir_nodes) - 1)
            ]

        return GraphIR(
            schema_version=CURRENT_IR_VERSION,
            metadata=IRMetadata(
                name=self.name,
                seed=self.seed,
                description=self.description,
            ),
            nodes=ir_nodes,
            edges=ir_edges,
        )

    @classmethod
    def _from_ir(cls, graph: "GraphIR") -> "Pipeline":
        """Construct a Pipeline directly from a GraphIR without calling _build_ir().

        Used by ``from_json`` and ``from_yaml`` to avoid the double-build
        overhead (S-04 fix): previously those classmethods called ``cls(nodes,
        ...)`` which triggered ``_build_ir()``, then immediately overwrote
        ``_graph_ir`` with the loaded IR.

        This factory bypasses ``__init__`` entirely and sets all fields
        directly from the GraphIR.
        """
        pipeline = object.__new__(cls)
        pipeline.nodes = [
            PipelineNode.__new__(PipelineNode) for _ in graph.nodes
        ]
        # Populate lightweight PipelineNode shells (no validation — IR is already valid)
        for pn, ir_node in zip(pipeline.nodes, graph.nodes):
            pn.node_type = ir_node.node_type
            pn.config = dict(ir_node.config)
            pn._ir_node = ir_node
        pipeline.seed = graph.metadata.seed
        pipeline.name = graph.metadata.name
        pipeline.description = graph.metadata.description
        pipeline._explicit_edges = None
        pipeline._subscribers = []
        pipeline._last_run_id = None
        pipeline._graph_ir = graph
        return pipeline

    def _make_subscriber_logger(self, base_logger: Any) -> Any:
        """Return a logger that forwards events to all registered subscribers.

        Returns ``base_logger`` unchanged when there are no subscribers.
        Uses a lazily-initialized PipelineLogger subclass so that internal
        calls to ``self._emit`` within PipelineLogger methods (node_start,
        node_end, etc.) correctly reach the subscriber callbacks (S-05 fix).
        """
        if not self._subscribers:
            return base_logger

        global _SubscriberLoggerClass
        if _SubscriberLoggerClass is None:
            _SubscriberLoggerClass = _make_subscriber_logger_class()

        base_queue = getattr(base_logger, "queue", None) if base_logger else None
        sl = _SubscriberLoggerClass(subscribers=self._subscribers, queue=base_queue)

        # Preserve logs and start_time from an existing base logger
        if base_logger is not None:
            sl.logs = getattr(base_logger, "logs", sl.logs)
            sl.start_time = getattr(base_logger, "start_time", sl.start_time)

        return sl

    def _execute(
        self,
        logger: Any,
        use_cache: bool,
        checkpoint: bool,
        streaming: bool,
        parallel: bool,
        max_workers: "int | None",
        resume_run_id: "str | None",
        include_nodes: "list[str] | None",
        exclude_nodes: "list[str] | None",
        input_overrides: "dict | None",
        event_driven: bool,
        observer: Any,
        run_manager: Any,
    ) -> "tuple[dict, Any]":
        """Core execution logic shared by run() and run_with_manager() (S-01 fix).

        Returns ``(raw_outputs, run_manager)`` so both public methods can
        build their return values from the same execution.
        """
        from app.core.runtime_backend import get_backend  # noqa: PLC0415
        from app.core.run_journal import RunManager  # noqa: PLC0415

        if run_manager is None:
            run_manager = RunManager()

        # Deep-copy the IR instead of round-tripping through JSON (S-03 fix).
        # copy.deepcopy is faster and preserves all Python-level attributes.
        graph = copy.deepcopy(self._graph_ir)

        _logger = self._make_subscriber_logger(logger)

        raw_outputs = get_backend().execute(
            graph,
            logger=_logger,
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
        self._last_run_id = run_manager.run_id
        return raw_outputs, run_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def to_ir(self) -> "GraphIR":
        """Return the backing GraphIR object (Req 2.4.2)."""
        return self._graph_ir

    def _to_config_dict(self) -> dict:
        """Derive the legacy YAML config dict from the backing GraphIR."""
        graph = self._graph_ir
        return {
            "pipeline": {
                "seed": graph.metadata.seed,
                "nodes": [
                    {"type": node.node_type, "config": dict(node.config)}
                    for node in graph.nodes
                ],
            }
        }

    def run(
        self,
        logger: Any = None,
        use_cache: bool = True,
        checkpoint: bool = False,
        streaming: bool = False,
        parallel: bool = False,
        max_workers: "int | None" = None,
        resume_run_id: "str | None" = None,
        include_nodes: "list[str] | None" = None,
        exclude_nodes: "list[str] | None" = None,
        input_overrides: "dict | None" = None,
        event_driven: bool = False,
        observer: Any = None,
        run_manager: Any = None,
    ) -> "ArtifactCollection":
        """Execute the pipeline and return an ArtifactCollection (Req 2.4.3).

        Delegates to ``run_with_manager()`` and discards the manager (S-01 fix).
        All existing dict-access patterns (result["node_id"]) continue to work.

        Requirements: req-04 §2, §3
        """
        collection, _ = self.run_with_manager(
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
        return collection

    def get_last_run_id(self) -> "str | None":
        """Return the run_id of the most recent run, or None if never run."""
        return self._last_run_id

    def run_with_manager(
        self,
        logger: Any = None,
        use_cache: bool = True,
        checkpoint: bool = False,
        streaming: bool = False,
        parallel: bool = False,
        max_workers: "int | None" = None,
        resume_run_id: "str | None" = None,
        include_nodes: "list[str] | None" = None,
        exclude_nodes: "list[str] | None" = None,
        input_overrides: "dict | None" = None,
        event_driven: bool = False,
        observer: Any = None,
        run_manager: Any = None,
    ) -> "tuple[ArtifactCollection, Any]":
        """Execute the pipeline and return (ArtifactCollection, run_manager).

        Example::

            collection, run = pipeline.run_with_manager()
            print(f"Run ID: {run.run_id}")
            print(f"Artifacts: {collection.artifacts}")

        Requirements: req-04 §3.5
        """
        raw_outputs, run_manager = self._execute(
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
        collection = ArtifactCollection(
            # Use the public artifacts property (thread-safe snapshot, S-02 fix)
            artifacts=run_manager.artifacts,
            run_id=run_manager.run_id,
            _raw=raw_outputs,
        )
        return collection, run_manager

    def to_json(self, path: str) -> None:
        """Serialize the pipeline to an IR JSON file (Req 2.6.1)."""
        from app.core.ir.loader import dump_ir_to_file
        dump_ir_to_file(self._graph_ir, path)

    @classmethod
    def from_json(cls, path: str) -> "Pipeline":
        """Load a Pipeline from an IR JSON file (Req 2.5.1).

        Uses ``_from_ir()`` to avoid the double-build overhead (S-04 fix).
        Preserves explicit edge routing from the IR.

        Raises:
            IRVersionError: if the IR document has an incompatible major version.
        """
        from app.core.ir.loader import load_ir_from_file
        graph = load_ir_from_file(path)
        return cls._from_ir(graph)

    @classmethod
    def from_yaml(cls, path: str) -> "Pipeline":
        """Load a Pipeline from a YAML file (deprecated — emits DeprecationWarning).

        Uses ``_from_ir()`` to avoid the double-build overhead (S-04 fix).

        Req 2.3.5, 4.2.4
        """
        from app.core.ir.yaml_shim import load_yaml_with_deprecation
        graph = load_yaml_with_deprecation(path)
        return cls._from_ir(graph)

    def to_yaml(self, path: str) -> None:
        """Serialize the pipeline to a YAML file (Req 2.7.1)."""
        import yaml
        config = self._to_config_dict()
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, sort_keys=False)

    def install_plugin(self, source: str, upgrade: bool = False) -> "PluginRecord":
        """Install a plugin and make its node types available immediately.

        Requirements: req-08 §9.9
        """
        from app.core.plugins.manager import PluginManager
        return PluginManager().install(source, upgrade=upgrade)

    def subscribe(self, callback: "Callable[[dict], None]") -> "Callable[[], None]":
        """Register a callback to receive pipeline execution events (V1.md §8).

        Args:
            callback: Callable accepting a single event dict. Always has a
                      ``"type"`` key (e.g. ``"node_start"``, ``"node_end"``).

        Returns:
            An unsubscribe function. Call it to remove the callback.

        Example::

            def on_event(event):
                if event["type"] == "node_end":
                    print(f"Node {event['node_type']} done in {event['duration_s']:.2f}s")

            unsubscribe = pipeline.subscribe(on_event)
            pipeline.run()
            unsubscribe()
        """
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    def validate(self) -> list[str]:
        """Validate the pipeline and return a list of error strings.

        Returns an empty list if the pipeline is valid. Uses IR-native
        validation: structural checks via load_ir() then topology checks
        via PipelineGraph. No longer round-trips through the deprecated
        YAML-format dict (G5-17 / SDK-validate fix).

        Returns:
            List of validation error strings. Empty list means valid.
        """
        from app.core.ir.loader import load_ir, dump_ir  # noqa: PLC0415
        from app.core.planner import PipelineGraph, _ir_to_pipeline_config  # noqa: PLC0415

        errors: list[str] = []

        # Step 1: structural IR validation (schema, node IDs, edge refs)
        try:
            graph_dict = dump_ir(self._graph_ir)
            load_ir(graph_dict)
        except Exception as exc:
            errors.append(str(exc))
            return errors  # no point continuing if IR is structurally invalid

        # Step 2: node type resolution + config validation + topology (cycle check)
        try:
            pipeline_cfg = _ir_to_pipeline_config(self._graph_ir)
            PipelineGraph(pipeline_cfg)
        except Exception as exc:
            errors.append(str(exc))

        return errors

    def pause(self) -> None:
        """Pause the currently running pipeline after the current node completes.

        Requires a run to be in progress (started via run() or run_with_manager()).
        No-op if no run is active (G5-20 fix).
        """
        if self._last_run_id is None:
            return
        from app.core.run_control import get_active_run
        run = get_active_run(self._last_run_id)
        if run is not None:
            run.pause()

    def resume(self) -> None:
        """Resume a paused pipeline run (G5-20 fix).

        No-op if no run is active or the run is not paused.
        """
        if self._last_run_id is None:
            return
        from app.core.run_control import get_active_run
        run = get_active_run(self._last_run_id)
        if run is not None:
            run.resume()

    def cancel(self) -> None:
        """Cancel the currently running pipeline after the current node completes.

        No-op if no run is active (G5-20 fix).
        """
        if self._last_run_id is None:
            return
        from app.core.run_control import get_active_run
        run = get_active_run(self._last_run_id)
        if run is not None:
            run.cancel()
