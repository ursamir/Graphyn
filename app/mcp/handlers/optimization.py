# app/mcp/handlers/optimization.py
"""optimize_execution MCP tool handler (V1.md §11).

Analyses a GraphIR and returns execution recommendations:
- parallel vs sequential
- cacheable subgraph identification
- hardware placement hints based on capability metadata
- partial execution suggestions
"""
from __future__ import annotations

from typing import Any

# ── Tool schema constants ─────────────────────────────────────────────────────

OPTIMIZE_EXECUTION_DESCRIPTION = (
    "Analyse a GraphIR and return execution optimization recommendations. "
    "Suggests parallel execution waves, identifies cacheable nodes, provides "
    "hardware placement hints based on capability metadata, and flags nodes "
    "that can be skipped via partial execution."
)

OPTIMIZE_EXECUTION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "graph": {
            "type": "object",
            "description": "A validated GraphIR JSON document to analyse.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["graph"],
    "additionalProperties": False,
}


# ── Handler ───────────────────────────────────────────────────────────────────


def optimize_execution_handler(arguments: dict[str, Any]) -> Any:
    """Analyse a GraphIR and return execution optimization recommendations."""
    from app.core.ir.loader import load_ir
    from app.core.planner import PipelineGraph, _ir_to_pipeline_config
    from app.core.orchestrator import _resolve_capability
    from app.core.registry_runtime import get_registry

    graph_dict = arguments.get("graph")
    if not graph_dict:
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "'graph' is required.",
        }

    # Validate graph
    try:
        graph = load_ir(graph_dict)
    except Exception as exc:
        return {
            "error": True,
            "error_type": "ir_validation_error",
            "message": str(exc),
        }

    registry = get_registry()

    # ── Build execution waves ─────────────────────────────────────────────────
    try:
        pipeline_cfg = _ir_to_pipeline_config(graph)
        graph_obj = PipelineGraph(pipeline_cfg)
        waves = graph_obj.execution_waves
    except Exception as exc:
        return {
            "error": True,
            "error_type": "graph_build_error",
            "message": str(exc),
        }

    # ── Analyse each node's capability metadata ───────────────────────────────
    node_analysis: list[dict] = []
    requires_gpu_nodes: list[str] = []
    edge_compatible_nodes: list[str] = []
    non_cacheable_nodes: list[str] = []
    non_deterministic_nodes: list[str] = []

    for ir_node in graph.nodes:
        try:
            cap = _resolve_capability(ir_node, registry)
        except Exception:
            cap = None

        analysis: dict[str, Any] = {
            "node_id": ir_node.id,
            "node_type": ir_node.node_type,
        }

        if cap is not None:
            analysis["capability"] = {
                "requires_gpu": cap.requires_gpu,
                "supports_cpu": cap.supports_cpu,
                "supports_edge": cap.supports_edge,
                "deterministic": cap.deterministic,
                "cacheable": cap.cacheable,
                "streaming_support": cap.streaming_support,
                "realtime_support": cap.realtime_support,
                "batch_support": cap.batch_support,
                "memory_requirements": cap.memory_requirements,
            }
            if cap.requires_gpu:
                requires_gpu_nodes.append(ir_node.id)
            if cap.supports_edge:
                edge_compatible_nodes.append(ir_node.id)
            if not cap.cacheable:
                non_cacheable_nodes.append(ir_node.id)
            if not cap.deterministic:
                non_deterministic_nodes.append(ir_node.id)
        else:
            analysis["capability"] = None

        node_analysis.append(analysis)

    # ── Parallel execution recommendation ─────────────────────────────────────
    max_wave_size = max((len(w) for w in waves), default=0)
    can_parallelize = max_wave_size > 1

    wave_summary = [
        {"wave_index": i, "node_ids": wave, "parallelizable": len(wave) > 1}
        for i, wave in enumerate(waves)
    ]

    # ── Partial execution hints ───────────────────────────────────────────────
    # Identify source nodes (no incoming edges) and sink nodes (no outgoing edges)
    all_dst_ids = {e.dst_id for e in graph.edges}
    all_src_ids = {e.src_id for e in graph.edges}
    source_nodes = [n.id for n in graph.nodes if n.id not in all_dst_ids]
    sink_nodes = [n.id for n in graph.nodes if n.id not in all_src_ids]

    # ── Conditional edges ─────────────────────────────────────────────────────
    conditional_edges = [
        {
            "src_id": e.src_id,
            "src_port": e.src_port,
            "dst_id": e.dst_id,
            "dst_port": e.dst_port,
            "condition": e.condition,
        }
        for e in graph.edges
        if e.condition is not None
    ]

    # ── Recommendations ───────────────────────────────────────────────────────
    recommendations: list[str] = []

    if can_parallelize:
        parallel_waves = [w for w in waves if len(w) > 1]
        recommendations.append(
            f"Enable parallel=True: {len(parallel_waves)} wave(s) contain multiple "
            f"independent nodes (max {max_wave_size} nodes in one wave)."
        )

    if non_cacheable_nodes:
        recommendations.append(
            f"Nodes {non_cacheable_nodes} have cacheable=False — they will always "
            "re-execute even with use_cache=True."
        )

    if non_deterministic_nodes:
        recommendations.append(
            f"Nodes {non_deterministic_nodes} are non-deterministic — avoid caching "
            "or resuming from checkpoints for these nodes."
        )

    if requires_gpu_nodes:
        recommendations.append(
            f"Nodes {requires_gpu_nodes} require a GPU. Ensure GPU is available "
            "before executing, or use a GPU-capable runtime backend."
        )

    if edge_compatible_nodes and len(edge_compatible_nodes) == len(graph.nodes):
        recommendations.append(
            "All nodes have supports_edge=True — this graph is suitable for edge deployment."
        )
    elif edge_compatible_nodes:
        incompatible = [n.id for n in graph.nodes if n.id not in edge_compatible_nodes]
        recommendations.append(
            f"Nodes {incompatible} have supports_edge=False — graph is NOT suitable "
            "for edge deployment as-is."
        )

    if conditional_edges:
        recommendations.append(
            f"{len(conditional_edges)} conditional edge(s) found — some nodes may be "
            "skipped at runtime depending on upstream outputs."
        )

    if not recommendations:
        recommendations.append(
            "No specific optimizations identified. Graph is ready to execute with defaults."
        )

    return {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "execution_waves": wave_summary,
        "can_parallelize": can_parallelize,
        "max_wave_parallelism": max_wave_size,
        "source_nodes": source_nodes,
        "sink_nodes": sink_nodes,
        "requires_gpu_nodes": requires_gpu_nodes,
        "edge_compatible_nodes": edge_compatible_nodes,
        "non_cacheable_nodes": non_cacheable_nodes,
        "non_deterministic_nodes": non_deterministic_nodes,
        "conditional_edges": conditional_edges,
        "node_analysis": node_analysis,
        "recommendations": recommendations,
    }
