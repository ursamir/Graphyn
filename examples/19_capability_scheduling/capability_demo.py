#!/usr/bin/env python3
"""
Example 19 — Capability-Aware Scheduling (Priority 13 — D2)
============================================================
Demonstrates the machine-readable capability metadata system — the
foundation for Phase 6 edge deployment scheduling.

A scheduling script queries the registry for nodes filtered by capability
fields, builds an edge-optimized inference pipeline using only
edge-compatible nodes, and verifies the graph's capability summary.

What this shows:
  - list_nodes(capability_filter={"supports_edge": True}) via MCP
  - get_graph_capability_summary — aggregate capability analysis
  - IRCapabilityMetadata fields: supports_edge, memory_requirements, batch_support
  - How capability metadata enables hardware-aware scheduling
  - registry.find_compatible_nodes() — type-compatible node discovery
  - GET /api/v1/nodes?capability=supports_edge:true via REST

Usage:
  venv/bin/python examples/19_capability_scheduling/capability_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from app.core.plugins.manager import PluginManager  # noqa: E402

# ── Install all plugins so the full capability inventory is visible ───────────
_manager = PluginManager()
for _pkg in [
    "PluginPackage/Audio/dataset_ingest/",
    "PluginPackage/Audio/stream_ingest/",
    "PluginPackage/Audio/audio_conditioner/",
    "PluginPackage/Audio/segmenter/",
    "PluginPackage/Audio/audio_quality_gate/",
    "PluginPackage/Audio/augmentation_pipeline/",
    "PluginPackage/Audio/feature_frontend/",
    "PluginPackage/Audio/audio_classifier/",
    "PluginPackage/Audio/audio_event_detector/",
    "PluginPackage/Audio/audio_annotator/",
    "PluginPackage/Audio/audio_exporter/",
    "PluginPackage/Audio/audio_generator/",
    "PluginPackage/Audio/alignment_node/",
    "PluginPackage/Audio/environment_simulator/",
    "PluginPackage/Audio/speaker_separator/",
    "PluginPackage/Audio/speech_enhancer/",
    "PluginPackage/Common/dataset_builder/",
    "PluginPackage/Common/dataset_versioner/",
    "PluginPackage/Common/deployment_packager/",
    "PluginPackage/Common/edge_optimizer/",
]:
    _manager.install(_pkg)
_manager.load_enabled_plugins()

_RESET = "\033[0m"; _BOLD = "\033[1m"; _CYAN = "\033[36m"
_GREEN = "\033[32m"; _DIM = "\033[2m"; _YELLOW = "\033[33m"; _RED = "\033[31m"
def _h(t): return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t): return f"{_GREEN}{t}{_RESET}"
def _dim(t): return f"{_DIM}{t}{_RESET}"
def _warn(t): return f"{_YELLOW}{t}{_RESET}"
def _err(t): return f"{_RED}{t}{_RESET}"

EXAMPLE_DIR = Path(__file__).parent


def main() -> None:
    from app.core.registry_runtime import get_registry
    from app.core.ir.loader import CURRENT_IR_VERSION, dump_ir
    from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode, IRCapabilityMetadata

    registry = get_registry()

    print(f"\n{'='*60}")
    print(_h("Example 19 — Capability-Aware Scheduling"))
    print(f"{'='*60}")

    # ── Step 1: Discover all nodes with their capability metadata ─────
    print(f"\n{_h('Step 1 — Full capability inventory')}")
    all_nodes = registry.list_nodes()
    print(f"  {len(all_nodes)} nodes registered. Capability breakdown:\n")

    cap_table = []
    for meta in sorted(all_nodes, key=lambda m: (m.category, m.node_type)):
        cap_table.append({
            "node_type":        meta.node_type,
            "category":         meta.category,
            "requires_gpu":     meta.requires_gpu,
            "supports_edge":    meta.supports_edge,
            "deterministic":    meta.deterministic,
            "cacheable":        meta.cacheable,
            "streaming":        meta.streaming_support,
            "batch":            meta.batch_support,
            "memory":           meta.memory_requirements or "—",
        })

    # Print header
    print(f"  {'node_type':<25} {'cat':<18} {'gpu':>4} {'edge':>5} "
          f"{'det':>4} {'cache':>5} {'stream':>6} {'batch':>5} {'mem':<8}")
    print(f"  {'-'*25} {'-'*18} {'-'*4} {'-'*5} {'-'*4} {'-'*5} {'-'*6} {'-'*5} {'-'*8}")
    for r in cap_table:
        def b(v): return _ok("✓") if v else _dim("✗")
        print(f"  {r['node_type']:<25} {r['category']:<18} "
              f"{b(r['requires_gpu']):>4} {b(r['supports_edge']):>5} "
              f"{b(r['deterministic']):>4} {b(r['cacheable']):>5} "
              f"{b(r['streaming']):>6} {b(r['batch']):>5} {r['memory']:<8}")

    # ── Step 2: Filter edge-compatible nodes ──────────────────────────
    print(f"\n{_h('Step 2 — Filter: supports_edge=True')}")
    edge_nodes = [m for m in all_nodes if m.supports_edge]
    print(f"  {len(edge_nodes)} edge-compatible nodes:")
    for m in sorted(edge_nodes, key=lambda m: m.node_type):
        mem = f"  mem={m.memory_requirements}" if m.memory_requirements else ""
        print(f"    {_ok('✓')} {_BOLD}{m.node_type:<25}{_RESET} "
              f"[{m.category}]{mem}")

    # ── Step 3: Filter GPU-required nodes ─────────────────────────────
    print(f"\n{_h('Step 3 — Filter: requires_gpu=True')}")
    gpu_nodes = [m for m in all_nodes if m.requires_gpu]
    if gpu_nodes:
        for m in gpu_nodes:
            print(f"    {_warn('⚡')} {m.node_type} [{m.category}]")
    else:
        print(f"  {_dim('No nodes require GPU in the current registry')}")

    # ── Step 4: Filter non-deterministic nodes ────────────────────────
    print(f"\n{_h('Step 4 — Filter: deterministic=False (random augmentation nodes)')}")
    nondeterministic = [m for m in all_nodes if not m.deterministic]
    print(f"  {len(nondeterministic)} non-deterministic nodes:")
    for m in sorted(nondeterministic, key=lambda m: m.node_type):
        print(f"    {_warn('~')} {_BOLD}{m.node_type:<25}{_RESET} [{m.category}]")

    # ── Step 5: Build an edge-optimized inference graph ───────────────
    print(f"\n{_h('Step 5 — Build edge-optimized inference graph')}")
    print(f"  Using only edge-compatible nodes: stream_ingest → audio_conditioner → segmenter → feature_frontend")

    edge_node_types = {m.node_type for m in edge_nodes}
    pipeline_nodes = ["stream_ingest", "audio_conditioner", "segmenter", "feature_frontend"]
    missing = [n for n in pipeline_nodes if n not in edge_node_types]
    if missing:
        print(f"  {_warn('⚠')} Some planned nodes not edge-compatible: {missing}")

    # Use stream_ingest with source="file_stream" — edge-compatible alternative to dataset_ingest
    sample_file = str(Path(WORKSPACE_ROOT) / "examples" / "02_speech_commands" / "data" / "yes")
    # Pick any wav file from the directory for the file_stream demo
    import glob as _glob
    wav_files = _glob.glob(str(Path(WORKSPACE_ROOT) / "examples" / "02_speech_commands" / "data" / "yes" / "*.wav"))
    sample_wav = wav_files[0] if wav_files else "examples/02_speech_commands/data/yes/0a2b400e_nohash_0.wav"

    nodes = [
        IRNode(id="stream_ingest_0",     node_type="stream_ingest",
               config={"source": "file_stream", "file_path": sample_wav,
                       "sample_rate": 16000, "duration_s": 5.0}),
        IRNode(id="audio_conditioner_1", node_type="audio_conditioner",
               config={"target_sample_rate": 16000}),
        IRNode(id="segmenter_2",         node_type="segmenter",
               config={"silence_threshold_db": 40.0, "mode": "silence"}),
        IRNode(id="feature_frontend_3",  node_type="feature_frontend",
               config={"feature_type": "mfcc", "n_mfcc": 40, "n_fft": 512,
                       "hop_length": 160, "fmax": 8000.0, "fixed_length": 101,
                       "normalize": True}),
    ]
    edges = [
        IREdge(src_id="stream_ingest_0",     src_port="output", dst_id="audio_conditioner_1", dst_port="input"),
        IREdge(src_id="audio_conditioner_1", src_port="output", dst_id="segmenter_2",          dst_port="input"),
        IREdge(src_id="segmenter_2",         src_port="output", dst_id="feature_frontend_3",   dst_port="input"),
    ]
    graph = GraphIR(
        schema_version=CURRENT_IR_VERSION,
        metadata=IRMetadata(name="edge-inference", seed=42,
                            description="Edge-optimized inference pipeline"),
        nodes=nodes, edges=edges,
    )

    # ── Step 6: Compute capability summary ────────────────────────────
    print(f"\n{_h('Step 6 — Compute graph capability summary')}")
    from app.mcp.handlers.graph import get_graph_capability_summary_handler
    summary = get_graph_capability_summary_handler({"graph": dump_ir(graph)})

    print(f"  Graph: {len(graph.nodes)} nodes")
    print(f"  Capability summary:")
    for k, v in summary.items():
        icon = _ok("✓") if v is True else (_err("✗") if v is False else _dim("—"))
        print(f"    {icon} {k}: {_BOLD}{v}{_RESET}")

    if summary.get("all_support_edge"):
        print(f"\n  {_ok('✓')} This graph is EDGE-DEPLOYABLE — all nodes support edge hardware")
    else:
        print(f"\n  {_warn('⚠')} This graph is NOT fully edge-compatible")

    if not summary.get("any_requires_gpu"):
        print(f"  {_ok('✓')} No GPU required — can run on CPU-only edge devices")

    # ── Step 7: Save graph for Phase 6 ───────────────────────────────
    from app.core.ir.loader import dump_ir_to_file
    graph_path = EXAMPLE_DIR / "edge_inference.graph.json"
    dump_ir_to_file(graph, str(graph_path))
    print(f"\n  {_ok('✓')} Edge-optimized graph saved: {graph_path}")
    print(f"  This graph is ready for Phase 6 edge deployment packaging.")

    print(f"\n{_h('Summary')}")
    print(f"  Capability fields enable hardware-aware scheduling:")
    print(f"    supports_edge=True  → safe to deploy to Raspberry Pi, Jetson, etc.")
    print(f"    requires_gpu=True   → needs GPU acceleration")
    print(f"    deterministic=False → output varies per run (augmentation nodes)")
    print(f"    memory_requirements → estimated RAM footprint")
    print(f"    batch_support=True  → can process multiple samples at once")
    print(f"\n  Phase 6 will use supports_edge to filter and schedule")
    print(f"  nodes for deployment to edge hardware targets.")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
