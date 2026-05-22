#!/usr/bin/env python3
"""
Example 18 — Pipeline Composition and Reuse (Priority 12 — G1)
===============================================================
Demonstrates the IR as a composable, programmable graph format.

Builds two sub-pipelines, serializes each to IR JSON, then composes
them into a single pipeline by merging their nodes and edges.

What this shows:
  - pipeline.to_ir()          — get the backing GraphIR object
  - pipeline.to_json(path)    — serialize to .graph.json
  - Pipeline.from_json(path)  — load and preserve explicit edges
  - Programmatic IR manipulation: merge nodes + edges from two graphs
  - load_ir(dict) / dump_ir(graph) — IR serialization primitives
  - IRNode, IREdge, IRMetadata — IR model construction

Usage:
  venv/bin/python examples/18_pipeline_composition/composition_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from app.core.plugins.manager import PluginManager  # noqa: E402

# ── Install required plugins ──────────────────────────────────────────────────
_manager = PluginManager()
_manager.install("PluginPackage/Audio/dataset_ingest/")
_manager.install("PluginPackage/Audio/audio_conditioner/")
_manager.install("PluginPackage/Audio/segmenter/")
_manager.install("PluginPackage/Audio/audio_quality_gate/")
_manager.install("PluginPackage/Audio/augmentation_pipeline/")
_manager.install("PluginPackage/Audio/feature_frontend/")
_manager.install("PluginPackage/Common/dataset_builder/")
_manager.install("PluginPackage/Common/dataset_versioner/")
_manager.load_enabled_plugins()

_RESET = "\033[0m"; _BOLD = "\033[1m"; _CYAN = "\033[36m"
_GREEN = "\033[32m"; _DIM = "\033[2m"
def _h(t): return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t): return f"{_GREEN}{t}{_RESET}"
def _dim(t): return f"{_DIM}{t}{_RESET}"

EXAMPLE_DIR = Path(__file__).parent
DATA_PATH   = Path(WORKSPACE_ROOT) / "examples" / "02_speech_commands" / "data" / "yes"
OUTPUT_DIR  = EXAMPLE_DIR / "output"


def build_preprocessing_pipeline():
    """Sub-pipeline A: dataset_ingest → audio_conditioner → segmenter → audio_quality_gate"""
    from app.core.sdk import Pipeline, PipelineNode
    return Pipeline(
        nodes=[
            PipelineNode("dataset_ingest",    {"path": str(DATA_PATH), "recursive": False, "source_type": "filesystem"}),
            PipelineNode("audio_conditioner", {"target_sample_rate": 16000}),
            PipelineNode("segmenter",         {"silence_threshold_db": 40.0, "mode": "silence"}),
            PipelineNode("audio_quality_gate",{"min_snr_db": 5.0}),
        ],
        seed=42, name="preprocessing",
    )


def build_augmentation_pipeline():
    """Sub-pipeline B: augmentation_pipeline → dataset_builder → dataset_versioner"""
    from app.core.sdk import Pipeline, PipelineNode
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return Pipeline(
        nodes=[
            PipelineNode("augmentation_pipeline", {"augmentations": [
                {"type": "gain",        "gain_db": [-3.0, 3.0],   "copies_per_sample": 1},
                {"type": "pitch_shift", "semitones": [-2.0, 2.0], "copies_per_sample": 1},
            ]}),
            PipelineNode("feature_frontend", {
                "feature_type": "mfcc",
                "n_mfcc": 40,
                "n_fft": 512,
                "hop_length": 160,
                "fmax": 8000.0,
            }),
            PipelineNode("dataset_builder",   {"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}, "fixed_length": 101}),
            PipelineNode("dataset_versioner", {"output_dir": str(OUTPUT_DIR),
                                               "version_tag": "v1"}),
        ],
        seed=42, name="augmentation",
    )


def compose_pipelines(ir_a, ir_b):
    """Merge two GraphIR objects into one by connecting A's last node to B's first."""
    from app.core.ir.loader import CURRENT_IR_VERSION
    from app.core.ir.models import GraphIR, IREdge, IRMetadata

    # Combine nodes (both already have unique IDs from their respective pipelines)
    all_nodes = list(ir_a.nodes) + list(ir_b.nodes)

    # Keep all edges from both sub-pipelines
    all_edges = list(ir_a.edges) + list(ir_b.edges)

    # Add a connecting edge: last node of A → first node of B
    last_a  = ir_a.nodes[-1].id
    first_b = ir_b.nodes[0].id
    connecting_edge = IREdge(
        src_id=last_a, src_port="output",
        dst_id=first_b, dst_port="input",
    )
    all_edges.append(connecting_edge)

    return GraphIR(
        schema_version=CURRENT_IR_VERSION,
        metadata=IRMetadata(
            name="composed-pipeline",
            seed=42,
            description=f"Composed from '{ir_a.metadata.name}' + '{ir_b.metadata.name}'",
        ),
        nodes=all_nodes,
        edges=all_edges,
    )


def main() -> None:
    if not DATA_PATH.exists():
        print(f"Missing data: {DATA_PATH}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(_h("Example 18 — Pipeline Composition and Reuse"))
    print(f"{'='*60}")

    # ── Build sub-pipelines ───────────────────────────────────────────
    print(f"\n{_h('Step 1 — Build two sub-pipelines')}")
    pipe_a = build_preprocessing_pipeline()
    pipe_b = build_augmentation_pipeline()

    ir_a = pipe_a.to_ir()
    ir_b = pipe_b.to_ir()

    print(f"  Sub-pipeline A ({ir_a.metadata.name}): {len(ir_a.nodes)} nodes")
    for n in ir_a.nodes:
        print(f"    {_dim(n.id)} ({n.node_type})")

    print(f"  Sub-pipeline B ({ir_b.metadata.name}): {len(ir_b.nodes)} nodes")
    for n in ir_b.nodes:
        print(f"    {_dim(n.id)} ({n.node_type})")

    # ── Serialize sub-pipelines ───────────────────────────────────────
    print(f"\n{_h('Step 2 — Serialize sub-pipelines to IR JSON')}")
    path_a = EXAMPLE_DIR / "preprocessing.graph.json"
    path_b = EXAMPLE_DIR / "augmentation.graph.json"
    pipe_a.to_json(str(path_a))
    pipe_b.to_json(str(path_b))
    print(f"  {_ok('✓')} {path_a.name}")
    print(f"  {_ok('✓')} {path_b.name}")

    # ── Load and verify round-trip ────────────────────────────────────
    print(f"\n{_h('Step 3 — Load from JSON (verify round-trip)')}")
    from app.core.sdk import Pipeline
    loaded_a = Pipeline.from_json(str(path_a))
    loaded_b = Pipeline.from_json(str(path_b))
    print(f"  {_ok('✓')} Loaded A: {len(loaded_a.nodes)} nodes, "
          f"edges preserved: {len(loaded_a.to_ir().edges)}")
    print(f"  {_ok('✓')} Loaded B: {len(loaded_b.nodes)} nodes, "
          f"edges preserved: {len(loaded_b.to_ir().edges)}")

    # ── Compose ───────────────────────────────────────────────────────
    print(f"\n{_h('Step 4 — Compose into single pipeline')}")
    composed_ir = compose_pipelines(ir_a, ir_b)
    print(f"  {_ok('✓')} Composed: {len(composed_ir.nodes)} nodes, "
          f"{len(composed_ir.edges)} edges")
    print(f"  Connecting edge: {ir_a.nodes[-1].id}.output → {ir_b.nodes[0].id}.input")

    # Save composed graph
    from app.core.ir.loader import dump_ir_to_file
    composed_path = EXAMPLE_DIR / "composed.graph.json"
    dump_ir_to_file(composed_ir, str(composed_path))
    print(f"  Saved: {composed_path}")

    # ── Run composed pipeline ─────────────────────────────────────────
    print(f"\n{_h('Step 5 — Run composed pipeline')}")
    from app.core.pipeline import run_pipeline_ir
    from app.core.run_manager import RunManager
    run_mgr = RunManager()
    run_pipeline_ir(composed_ir, run_manager=run_mgr, use_cache=False)
    print(f"  {_ok('✓')} Composed pipeline completed")
    print(f"    run_id: {run_mgr.run_id}")

    print(f"\n{_h('Summary')}")
    print(f"  pipeline.to_ir()     → GraphIR object (backing IR)")
    print(f"  pipeline.to_json()   → .graph.json file")
    print(f"  Pipeline.from_json() → Pipeline with edges preserved")
    print(f"  Programmatic merge:  combine nodes + edges + add connecting edge")
    print(f"  The IR is a first-class data structure — not just serialization")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
