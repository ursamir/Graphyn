#!/usr/bin/env python3
"""
Example 12 — Conditional Branching Pipeline (Priority 6 — A4)
==============================================================
Demonstrates IREdge.condition — edges that are only traversed when a
boolean expression evaluates to True against the source node's output.

Pipeline: file_input → trim → [branch A: silence_detector → export_short]
                                [branch B: augment → export_long]

The trim node's output is routed to branch A (silence_detector) when
clips are short, and to branch B (augment) when clips are long.
Both branches always receive the full list; the condition gates which
branch actually processes data.

What this shows:
  - IREdge.condition field in the graph JSON
  - evaluate_condition() — restricted AST evaluator
  - node_skip(reason="condition_false") log events
  - Branching DAG topology (one source, two sinks)
  - How to write conditional edges programmatically

Usage:
  venv/bin/python examples/12_conditional_branching/conditional_pipeline.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from app.core.ir.loader import CURRENT_IR_VERSION, dump_ir_to_file  # noqa: E402
from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode  # noqa: E402
from app.core.pipeline import run_pipeline_ir  # noqa: E402
from app.core.plugins.manager import PluginManager  # noqa: E402

# ── Install required plugins ──────────────────────────────────────────────────
_manager = PluginManager()
_manager.install("PluginPackage/Audio/dataset_ingest/")
_manager.install("PluginPackage/Audio/segmenter/")
_manager.install("PluginPackage/Audio/audio_quality_gate/")
_manager.install("PluginPackage/Audio/augmentation_pipeline/")
_manager.install("PluginPackage/Audio/feature_frontend/")
_manager.install("PluginPackage/Common/dataset_builder/")
_manager.install("PluginPackage/Common/dataset_versioner/")
_manager.load_enabled_plugins()

_RESET = "\033[0m"; _BOLD = "\033[1m"; _CYAN = "\033[36m"
_GREEN = "\033[32m"; _DIM = "\033[2m"; _YELLOW = "\033[33m"
def _h(t): return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t): return f"{_GREEN}{t}{_RESET}"
def _dim(t): return f"{_DIM}{t}{_RESET}"
def _warn(t): return f"{_YELLOW}{t}{_RESET}"

EXAMPLE_DIR = Path(__file__).parent
DATA_PATH   = Path(WORKSPACE_ROOT) / "examples" / "02_speech_commands" / "data" / "yes"
OUTPUT_DIR  = EXAMPLE_DIR / "output"


def build_conditional_graph(condition_true: bool) -> GraphIR:
    """Build a branching graph with a conditional edge.

    When condition_true=True:  the condition 'len(output) > 0' passes → branch A runs
    When condition_true=False: the condition 'len(output) > 9999' fails → branch A skipped

    Branch A: segmenter → audio_quality_gate → dataset_versioner(branch_a)
    Branch B: segmenter → augmentation_pipeline → dataset_versioner(branch_b)

    The condition is on the edge from segmenter to audio_quality_gate.
    """
    condition_expr = "len(output) > 0" if condition_true else "len(output) > 9999"

    nodes = [
        IRNode(id="dataset_ingest_0",    node_type="dataset_ingest",
               config={"path": str(DATA_PATH), "recursive": False, "source_type": "filesystem"}),
        IRNode(id="segmenter_1",         node_type="segmenter",
               config={"silence_threshold_db": 40.0, "mode": "silence"}),
        # Branch A — conditional
        IRNode(id="audio_quality_gate_2",node_type="audio_quality_gate",
               config={"min_snr_db": 5.0}),
        IRNode(id="feature_frontend_a_2b", node_type="feature_frontend",
               config={"feature_type": "mfcc", "n_mfcc": 40, "n_fft": 512,
                       "hop_length": 160, "fmax": 8000.0}),
        IRNode(id="dataset_builder_a_3", node_type="dataset_builder",
               config={"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}, "fixed_length": 101}),
        IRNode(id="dataset_versioner_a_4",node_type="dataset_versioner",
               config={"output_dir": str(OUTPUT_DIR / "branch_a"),
                       "version_tag": "v1"}),
        # Branch B — unconditional
        IRNode(id="augmentation_pipeline_5",node_type="augmentation_pipeline",
               config={"augmentations": [{"type": "gain", "gain_db": [-3.0, 3.0], "copies_per_sample": 1}]}),
        IRNode(id="feature_frontend_b_5b", node_type="feature_frontend",
               config={"feature_type": "mfcc", "n_mfcc": 40, "n_fft": 512,
                       "hop_length": 160, "fmax": 8000.0}),
        IRNode(id="dataset_builder_b_6", node_type="dataset_builder",
               config={"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}, "fixed_length": 101}),
        IRNode(id="dataset_versioner_b_7",node_type="dataset_versioner",
               config={"output_dir": str(OUTPUT_DIR / "branch_b"),
                       "version_tag": "v1"}),
    ]
    edges = [
        IREdge(src_id="dataset_ingest_0",    src_port="output",
               dst_id="segmenter_1",         dst_port="input"),
        # Branch A — conditional edge
        IREdge(src_id="segmenter_1",         src_port="output",
               dst_id="audio_quality_gate_2",dst_port="input",
               condition=condition_expr),
        IREdge(src_id="audio_quality_gate_2",src_port="output",
               dst_id="feature_frontend_a_2b",dst_port="input"),
        IREdge(src_id="feature_frontend_a_2b",src_port="output",
               dst_id="dataset_builder_a_3", dst_port="input"),
        IREdge(src_id="dataset_builder_a_3", src_port="output",
               dst_id="dataset_versioner_a_4",dst_port="input"),
        # Branch B — unconditional edge
        IREdge(src_id="segmenter_1",         src_port="output",
               dst_id="augmentation_pipeline_5",dst_port="input"),
        IREdge(src_id="augmentation_pipeline_5",src_port="output",
               dst_id="feature_frontend_b_5b",dst_port="input"),
        IREdge(src_id="feature_frontend_b_5b",src_port="output",
               dst_id="dataset_builder_b_6", dst_port="input"),
        IREdge(src_id="dataset_builder_b_6", src_port="output",
               dst_id="dataset_versioner_b_7",dst_port="input"),
    ]
    return GraphIR(
        schema_version=CURRENT_IR_VERSION,
        metadata=IRMetadata(name="conditional-branching", seed=42,
                            description=f"Conditional edge: {condition_expr!r}"),
        nodes=nodes,
        edges=edges,
    )


def run_and_report(label: str, condition_true: bool) -> None:
    """Run the conditional pipeline and report which branches executed."""
    from app.core.logger import PipelineLogger

    print(f"\n{_h('Run: ' + label)}")
    condition_expr = "len(output) > 0" if condition_true else "len(output) > 9999"
    print(f"  Condition on trim→silence_detector edge: {_BOLD}{condition_expr!r}{_RESET}")
    print(f"  Expected: Branch A {'RUNS' if condition_true else 'SKIPPED'}, "
          f"Branch B always RUNS")

    graph = build_conditional_graph(condition_true)
    logger = PipelineLogger()
    try:
        run_pipeline_ir(graph, logger=logger, use_cache=False)
    except Exception as exc:
        # When condition is False, downstream nodes of the skipped branch
        # receive None input. Nodes that don't handle None will raise.
        # This is expected behavior — in production, use optional input ports
        # or guard nodes that handle None gracefully.
        if not condition_true:
            print(f"  {_warn('⚠')} Expected: downstream node received None "
                  f"(condition was False): {type(exc).__name__}")
        else:
            raise

    # Analyse log events
    skipped = [e for e in logger.logs if e.get("type") == "node_skip"]
    completed = [e for e in logger.logs if e.get("type") == "node_end"]

    print(f"\n  Results:")
    for e in completed:
        print(f"    {_ok('✓')} {e.get('node_type', '?'):<25} executed")
    for e in skipped:
        reason = e.get("reason", "?")
        print(f"    {_warn('⏭')} {e.get('node_type', '?'):<25} "
              f"skipped ({_dim(reason)})")

    if condition_true:
        branch_a_ran = any(e.get("node_type") == "audio_quality_gate" for e in completed)
        print(f"\n  Branch A (audio_quality_gate): {'✓ ran' if branch_a_ran else '✗ did not run'}")
    else:
        branch_a_skipped = any(e.get("node_type") == "audio_quality_gate" for e in skipped)
        print(f"\n  Branch A (audio_quality_gate): "
              f"{'⏭ correctly skipped' if branch_a_skipped else '? unexpected'}")

    branch_b_ran = any(e.get("node_type") == "augmentation_pipeline" for e in completed)
    print(f"  Branch B (augmentation_pipeline): {'✓ ran' if branch_b_ran else '✗ did not run'}")


def main() -> None:
    if not DATA_PATH.exists():
        print(f"Missing data: {DATA_PATH}")
        sys.exit(1)

    for d in [OUTPUT_DIR / "branch_a", OUTPUT_DIR / "branch_b"]:
        d.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(_h("Example 12 — Conditional Branching Pipeline"))
    print(f"{'='*60}")
    print(f"\n  Graph topology:")
    print(f"    dataset_ingest → segmenter ─[condition]─► audio_quality_gate → dataset_versioner_a")
    print(f"                               └────────────► augmentation_pipeline → dataset_versioner_b")
    print(f"\n  The condition is evaluated against trim's output dict.")
    print(f"  If True: silence_detector runs. If False: it is skipped.")

    # Save graph.json for inspection
    graph = build_conditional_graph(condition_true=True)
    graph_path = EXAMPLE_DIR / "pipeline.graph.json"
    dump_ir_to_file(graph, str(graph_path))
    print(f"\n  Graph saved: {graph_path}")
    print(f"  Inspect edges: graphyn inspect --graph {graph_path}")

    # Show the conditional edge in the JSON
    with open(graph_path) as f:
        gdata = json.load(f)
    cond_edges = [e for e in gdata["edges"] if e.get("condition")]
    print(f"\n  Conditional edges in graph JSON:")
    for e in cond_edges:
        print(f"    {_dim(e['src_id'] + '.' + e['src_port'])} → "
              f"{_dim(e['dst_id'] + '.' + e['dst_port'])}  "
              f"condition: {_BOLD}{e['condition']!r}{_RESET}")

    # Run 1: condition passes → both branches run
    run_and_report("Condition TRUE  (len(output) > 0)", condition_true=True)

    # Run 2: condition fails → branch A skipped
    run_and_report("Condition FALSE (len(output) > 9999)", condition_true=False)

    print(f"\n{'='*60}")
    print(_h("Summary"))
    print(f"{'='*60}")
    print(f"  IREdge.condition is a Python expression evaluated against")
    print(f"  the source node's output dict at runtime.")
    print(f"  Allowed: comparisons, boolean ops, len(), subscript on 'output'")
    print(f"  When False: destination node receives None → node_skip event")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
