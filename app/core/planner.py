# app/core/planner.py
"""Graph planning — DAG builder, topological sort, and execution wave computation.

Extracted from pipeline.py. Responsible for:
  - NodeSpec, EdgeSpec, PipelineConfig  — internal data structures
  - _parse_pipeline_config              — legacy YAML dict → PipelineConfig
  - _ir_to_pipeline_config              — GraphIR → PipelineConfig
  - PipelineGraph                       — DAG builder + validator + wave planner
"""
from __future__ import annotations

import copy
import itertools
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from app.core.nodes.base import Node
from app.core.nodes.observers import NodeObserver
from app.core.utils.hash import stable_hash

log = logging.getLogger(__name__)


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class NodeSpec:
    """Specification for one node in a pipeline config."""
    node_id: str
    node_type: str
    config: dict[str, Any]


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
        node_id = n.get("id") or f"{n['type']}_{i}"
        nodes.append(NodeSpec(
            node_id=node_id,
            node_type=n["type"],
            config=n.get("config", {}),
        ))

    raw_edges = pipeline.get("edges")
    if raw_edges:
        edges = [
            EdgeSpec(
                src_id=e["from"][0],
                src_port=e["from"][1],
                dst_id=e["to"][0],
                dst_port=e["to"][1],
            )
            for e in raw_edges
        ]
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

def _ir_to_pipeline_config(graph: Any) -> PipelineConfig:
    """Convert a GraphIR to a PipelineConfig. Pure — no side effects, no I/O."""
    nodes = [
        NodeSpec(
            node_id=ir_node.id,
            node_type=ir_node.node_type,
            config=dict(ir_node.config),
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
    ) -> None:
        self._config = config
        self._observer = observer
        self._nodes: dict[str, Node] = {}
        self._edges: list[EdgeSpec] = list(config.edges)
        self._topo_order: list[str] = []
        self._build()

    def _build(self) -> None:
        from app.core.registry_runtime import get_registry
        from app.core.nodes.compat import CompatibilityChecker
        from app.core.nodes.errors import PipelineGraphError

        node_registry = get_registry()
        seed = self._config.seed

        for i, spec in enumerate(self._config.nodes):
            node_class = node_registry.get_class(spec.node_type)
            node_seed = stable_hash(seed, spec.node_type, i) % (2 ** 32)
            node_config = copy.deepcopy(spec.config)
            node = node_class(config=node_config, seed=node_seed, observer=self._observer)
            self._nodes[spec.node_id] = node

        for edge in self._edges:
            src_node = self._nodes.get(edge.src_id)
            dst_node = self._nodes.get(edge.dst_id)
            if src_node is None:
                raise PipelineGraphError(f"Edge references unknown source node '{edge.src_id}'")
            if dst_node is None:
                raise PipelineGraphError(f"Edge references unknown destination node '{edge.dst_id}'")
            CompatibilityChecker.check_connection(src_node, edge.src_port, dst_node, edge.dst_port)

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

        max_level = max(level.values(), default=0)
        return [
            [nid for nid, lv in level.items() if lv == i]
            for i in range(max_level + 1)
        ]

    def get_node(self, node_id: str) -> Node:
        return self._nodes[node_id]

    @property
    def execution_waves(self) -> list[list[str]]:
        return list(self._waves)

    @property
    def execution_order(self) -> list[str]:
        return list(itertools.chain(*self._waves))
