# app/core/execution/planner.py
"""
Bounded Context:  BC4 — Execution Planner
Responsibility:   Transform a GraphIR into an executable DAG: instantiate nodes,
                  validate edges, compute topological order and parallel waves.
Owns:             NodeSpec, EdgeSpec, PipelineConfig (internal data structures);
                  PipelineGraph (DAG builder + validator + wave planner);
                  _ir_to_pipeline_config(), _parse_pipeline_config() (parsers).
Public Surface:   PipelineGraph, PipelineConfig, NodeSpec, EdgeSpec,
                  derive_node_seed() (shared with the distributed backend),
                  routed_error_port_of() (IR 1.3 on_error=route port),
                  _ir_to_pipeline_config(), _parse_pipeline_config()
Must NOT:         Execute nodes, persist state, import from app.domain,
                  import from BC5 (orchestrator/executor), or import from app.api.
Dependencies:     BC1 (ir.models via _ir_to_pipeline_config), BC2 (nodes.base,
                  nodes.observers, nodes.compat, nodes.errors),
                  BC3 (registry_runtime for node class lookup),
                  app.core.utils.hash (stable_hash for node seeding).
Reason To Change: DAG construction algorithm changes, wave computation strategy
                  evolves, or new node instantiation requirements emerge.
"""
from __future__ import annotations

import copy
import itertools
import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.core.nodes.base import Node
from app.core.nodes.observers import NodeObserver
from app.core.utils.hash import stable_hash

log = logging.getLogger(__name__)


def _plain_jsonable(value: Any) -> Any:
    """Normalize mappingproxy/containers to plain JSON-compatible containers."""
    if isinstance(value, MappingProxyType):
        return {k: _plain_jsonable(v) for k, v in value.items()}
    if isinstance(value, dict):
        return {k: _plain_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_plain_jsonable(v) for v in value]
    return value


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class NodeSpec:
    """Specification for one node in a pipeline config."""
    node_id: str
    node_type: str
    config: dict[str, Any]
    # IR 1.3 per-node policies (plain dicts; None = unset). Stamped onto the
    # Node instance as ``_graphyn_on_error`` / ``_graphyn_retry`` for
    # NodeExecutor (which never sees the IR).
    on_error: dict[str, Any] | None = None
    retry: dict[str, Any] | None = None


@dataclass
class EdgeSpec:
    """A directed edge connecting one node's output port to another's input port."""
    src_id: str
    src_port: str
    dst_id: str
    dst_port: str
    condition: str | None = None


@dataclass
class PipelineConfig:
    """Parsed, validated pipeline configuration."""
    seed: int
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]


# ── Legacy YAML parser ─────────────────────────────────────────────────────────

def _parse_pipeline_config(raw: dict) -> PipelineConfig:
    """Parse a raw YAML dict into a PipelineConfig.

    Supports both the explicit-edge format and the legacy linear format.
    """
    pipeline = raw.get("pipeline", {})
    seed = pipeline.get("seed", 0)
    raw_nodes = pipeline.get("nodes", [])

    nodes: list[NodeSpec] = []
    for i, n in enumerate(raw_nodes):
        node_id = n.get("id") or f"{n.get('type', 'node')}_{i}"
        # Finding 4 (HIGH): explicit error when "type" is missing
        node_type = n.get("type")
        if not node_type:
            raise ValueError(f"Node at index {i} is missing required field 'type'")
        nodes.append(NodeSpec(
            node_id=node_id,
            node_type=node_type,
            config=n.get("config", {}),
        ))

    raw_edges = pipeline.get("edges")
    if raw_edges:
        edges = []
        for ei, e in enumerate(raw_edges):
            # Finding 4+5 (HIGH): validate "from" and "to" are 2-element lists
            from_val = e.get("from")
            if not isinstance(from_val, (list, tuple)) or len(from_val) < 2:
                raise ValueError(
                    f"Edge at index {ei}: 'from' must be a 2-element list [node_id, port], "
                    f"got: {from_val!r}"
                )
            to_val = e.get("to")
            if not isinstance(to_val, (list, tuple)) or len(to_val) < 2:
                raise ValueError(
                    f"Edge at index {ei}: 'to' must be a 2-element list [node_id, port], "
                    f"got: {to_val!r}"
                )
            edges.append(EdgeSpec(
                src_id=from_val[0],
                src_port=from_val[1],
                dst_id=to_val[0],
                dst_port=to_val[1],
                # SA-P1 fix: copy condition from YAML edge so it is not silently
                # dropped (the IR path already copies it correctly).
                condition=e.get("condition"),
            ))
    else:
        edges = [
            EdgeSpec(
                src_id=nodes[i].node_id,
                src_port="output",
                dst_id=nodes[i + 1].node_id,
                dst_port="input",
            )
            for i in range(len(nodes) - 1)
        ]

    return PipelineConfig(seed=seed, nodes=nodes, edges=edges)


# ── IR → PipelineConfig ────────────────────────────────────────────────────────

def _policy_dict(value: Any) -> dict[str, Any] | None:
    """IR 1.3 on_error / retry model → plain dict (None when unset)."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return _plain_jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return _plain_jsonable(value)
    return None


def routed_error_port_of(spec_or_node: Any) -> str | None:
    """Error port name when on_error.mode == "route" (NodeSpec or Node)."""
    # Node instances have an ``on_error()`` hook method — read the stamped
    # policy there; NodeSpec carries a plain dict.
    pol = getattr(spec_or_node, "_graphyn_on_error", None)
    if pol is None and isinstance(spec_or_node, NodeSpec):
        pol = spec_or_node.on_error
    if isinstance(pol, dict) and pol.get("mode") == "route":
        return str(pol.get("port") or "error")
    return None


def _ir_to_pipeline_config(graph: Any) -> PipelineConfig:
    """Convert a GraphIR to a PipelineConfig. Pure — no side effects, no I/O."""
    # Finding 9 (LOW): guard against missing metadata
    if graph.metadata is None:
        raise ValueError("GraphIR is missing metadata — cannot extract seed")
    nodes = [
        NodeSpec(
            node_id=ir_node.id,
            node_type=ir_node.node_type,
            config=_plain_jsonable(ir_node.config),
            on_error=_policy_dict(getattr(ir_node, "on_error", None)),
            retry=_policy_dict(getattr(ir_node, "retry", None)),
        )
        for ir_node in graph.nodes
    ]
    edges = [
        EdgeSpec(
            src_id=ir_edge.src_id,
            src_port=ir_edge.src_port,
            dst_id=ir_edge.dst_id,
            dst_port=ir_edge.dst_port,
            condition=ir_edge.condition,
        )
        for ir_edge in graph.edges
    ]
    return PipelineConfig(seed=graph.metadata.seed, nodes=nodes, edges=edges)


# ── PipelineGraph ──────────────────────────────────────────────────────────────

def derive_node_seed(graph_seed: int, node_type: str, index: int, logical_config: Any) -> int:
    """Per-node seed shared by PipelineGraph (Mode A) and DistributedBackend (Mode B).

    ``index`` is the node's position in ``graph.nodes``; ``logical_config`` is the
    pre-run-scoping config (already JSON-plain). Raises TypeError when the config
    is not JSON-serializable.
    """
    config_str = json.dumps(logical_config, sort_keys=True)
    return stable_hash(graph_seed, node_type, index, config_str) % (2 ** 32)


class PipelineGraph:
    """Builds a validated DAG from a PipelineConfig.

    Responsibilities:
      - Instantiate Node objects from NodeSpecs
      - Validate all edges via CompatibilityChecker
      - Compute topological execution order (Kahn's algorithm)
      - Compute parallel execution waves (level-based BFS)
    """

    def __init__(
        self,
        config: PipelineConfig,
        observer: NodeObserver | None = None,
        registry: Any | None = None,
        seed_configs: dict[str, Any] | None = None,
    ) -> None:
        """Build the DAG.

        ``seed_configs`` (node_id → config) optionally supplies the *logical*
        config used to derive each node's seed. The orchestrator passes the
        pre-scoping configs so run-scoped artifact paths (which embed the
        run_id) do not change node seeds on every run. Nodes are still
        instantiated with ``config`` (the materialized one).
        """
        self._config = config
        self._seed_configs = dict(seed_configs or {})
        self._observer = observer
        # Finding 7 (MEDIUM): accept optional registry for DI / unit-test injection;
        # if None, _build() fetches the real singleton via get_registry().
        self._registry = registry
        self._nodes: dict[str, Node] = {}
        self._edges: list[EdgeSpec] = list(config.edges)
        self._topo_order: list[str] = []
        self._build()

    def _build(self) -> None:
        from app.core.host.registry_runtime import get_registry
        from app.core.nodes.compat import CompatibilityChecker
        from app.core.nodes.errors import PipelineGraphError

        node_registry = self._registry if self._registry is not None else get_registry()
        seed = self._config.seed

        for i, spec in enumerate(self._config.nodes):
            # Finding 1 (CRITICAL): duplicate node ID check — silent overwrite
            if spec.node_id in self._nodes:
                raise PipelineGraphError(
                    f"Duplicate node ID '{spec.node_id}' in pipeline config"
                )
            # Finding 2 (HIGH): guard against unknown node type
            node_class = node_registry.get_class(spec.node_type)
            if node_class is None:
                raise PipelineGraphError(
                    f"Unknown node type '{spec.node_type}' for node '{spec.node_id}'"
                )
            # SA-P3 fix: include node config in the seed so two pipelines with
            # the same seed and node types but different configs produce distinct
            # node seeds (important for augmentation nodes with random behaviour).
            # Finding 3 (HIGH): wrap json.dumps so non-serializable configs give a clear error
            config_plain = _plain_jsonable(spec.config)
            seed_source = (
                _plain_jsonable(self._seed_configs[spec.node_id])
                if spec.node_id in self._seed_configs
                else config_plain
            )
            try:
                node_seed = derive_node_seed(seed, spec.node_type, i, seed_source)
            except TypeError as exc:
                raise PipelineGraphError(
                    f"Node '{spec.node_id}' config is not JSON-serializable: {exc}"
                ) from exc
            node_config = copy.deepcopy(config_plain)
            node = node_class(config=node_config, seed=node_seed, observer=self._observer)
            # IR 1.3 policies for NodeExecutor (instance attrs; class untouched).
            node._graphyn_node_id = spec.node_id  # type: ignore[attr-defined]
            node._graphyn_on_error = spec.on_error  # type: ignore[attr-defined]
            node._graphyn_retry = spec.retry  # type: ignore[attr-defined]
            self._nodes[spec.node_id] = node

        for edge in self._edges:
            src_node = self._nodes.get(edge.src_id)
            dst_node = self._nodes.get(edge.dst_id)
            if src_node is None:
                raise PipelineGraphError(f"Edge references unknown source node '{edge.src_id}'")
            if dst_node is None:
                raise PipelineGraphError(f"Edge references unknown destination node '{edge.dst_id}'")
            # IR 1.3: the synthetic error port of an on_error=route node carries
            # a plain dict ({ok, error_type, message, node_id, attempt}); only
            # the destination port must exist.
            err_port = routed_error_port_of(src_node)
            if err_port is not None and edge.src_port == err_port:
                if edge.dst_port not in getattr(dst_node, "input_ports", {}):
                    raise PipelineGraphError(
                        f"Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                        f"'{edge.dst_id}' has no input port '{edge.dst_port}'"
                    )
                continue
            # Finding 8 (MEDIUM): wrap compat errors so callers only need to catch PipelineGraphError
            try:
                CompatibilityChecker.check_connection(src_node, edge.src_port, dst_node, edge.dst_port)
            except PipelineGraphError:
                raise
            except Exception as exc:
                raise PipelineGraphError(
                    f"Incompatible edge {edge.src_id}.{edge.src_port} → "
                    f"{edge.dst_id}.{edge.dst_port}: {exc}"
                ) from exc

        self._topo_order = self._topological_sort()
        self._waves: list[list[str]] = self._compute_waves()

    def _topological_sort(self) -> list[str]:
        from app.core.nodes.errors import PipelineGraphError

        in_degree: dict[str, int] = {nid: 0 for nid in self._nodes}
        adjacency: dict[str, list[str]] = defaultdict(list)

        for edge in self._edges:
            adjacency[edge.src_id].append(edge.dst_id)
            in_degree[edge.dst_id] += 1

        queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
        order: list[str] = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            for successor in adjacency[nid]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)

        if len(order) != len(self._nodes):
            raise PipelineGraphError(
                "Pipeline contains a cycle — topological sort failed. "
                f"Nodes not reached: {set(self._nodes) - set(order)}"
            )
        return order

    def _compute_waves(self) -> list[list[str]]:
        predecessors: dict[str, list[str]] = {nid: [] for nid in self._topo_order}
        for e in self._edges:
            predecessors[e.dst_id].append(e.src_id)

        level: dict[str, int] = {}
        for node_id in self._topo_order:
            preds = predecessors[node_id]
            level[node_id] = max((level[p] + 1 for p in preds), default=0)

        # SA-P2 fix: build waves dict in a single pass instead of iterating
        # all nodes for each level — reduces O(N²) to O(N) for deep linear pipelines.
        # Finding 6 (MEDIUM): empty pipeline must return [] not [[]]
        if not level:
            return []
        waves_dict: dict[int, list[str]] = defaultdict(list)
        for nid in self._topo_order:
            waves_dict[level[nid]].append(nid)
        max_level = max(level.values())
        return [waves_dict[i] for i in range(max_level + 1)]

    def get_node(self, node_id: str) -> Node:
        return self._nodes[node_id]

    @property
    def execution_waves(self) -> list[list[str]]:
        return list(self._waves)

    @property
    def execution_order(self) -> list[str]:
        return list(itertools.chain(*self._waves))

# Public names. A leading underscore stays private to this module.
ir_to_pipeline_config = _ir_to_pipeline_config
plain_jsonable = _plain_jsonable
