#!/usr/bin/env python3
"""
Example 09 — Parallel Wave Execution (Priority 3 — A1)
=======================================================
Demonstrates the platform's parallel DAG executor.

Builds a fan-out pipeline where multiple independent branches process
different audio label classes concurrently in the same pipeline execution.
Compares wall-clock time against sequential execution to show the speedup.

Pipeline shape (fan-out DAG):
                    ┌─ clean → trim → augment → split → file_export (yes)
  file_input(yes)  ─┤
                    └─ (sequential: same nodes, different seed)

  file_input(no)   ─┬─ clean → trim → augment → audio_exporter (no)
  file_input(up)   ─┬─ clean → trim → augment → audio_exporter (up)
  file_input(down) ─┘─ clean → trim → augment → audio_exporter (down)

In parallel mode, all four branches execute concurrently in Wave 1.
In sequential mode, they execute one after another.

What this shows:
  - pipeline.run(parallel=True)       — parallel wave execution
  - pipeline.run(parallel=False)      — sequential baseline
  - execution_waves                   — nodes grouped into parallel waves
  - wave_start / wave_end log events  — wave lifecycle
  - ParallelExecutor + ThreadPoolExecutor
  - Wall-clock speedup measurement

Usage:
  venv/bin/python examples/09_parallel_execution/parallel_pipeline.py

  # CLI equivalent
  venv/bin/python -m app.cli.main run \\
      --graph examples/09_parallel_execution/pipeline.graph.json \\
      --parallel
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import ClassVar

# ── Path setup ────────────────────────────────────────────────────────────────
WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from app.core.sdk import Pipeline, PipelineNode  # noqa: E402
from app.core.ir.models import (  # noqa: E402
    GraphIR, IREdge, IRMetadata, IRNode,
)
from app.core.ir.loader import CURRENT_IR_VERSION, dump_ir_to_file  # noqa: E402
from app.core.logger import PipelineLogger  # noqa: E402
from app.core.plugins.manager import PluginManager  # noqa: E402

# ── Install required plugins ──────────────────────────────────────────────────
_manager = PluginManager()
_manager.install("PluginPackage/Audio/dataset_ingest/")
_manager.install("PluginPackage/Audio/audio_conditioner/")
_manager.install("PluginPackage/Audio/segmenter/")
_manager.install("PluginPackage/Audio/augmentation_pipeline/")
_manager.install("PluginPackage/Audio/audio_exporter/")
_manager.load_enabled_plugins()

# ── Colours ───────────────────────────────────────────────────────────────────
_RESET   = "\033[0m"
_BOLD    = "\033[1m"
_CYAN    = "\033[36m"
_GREEN   = "\033[32m"
_YELLOW  = "\033[33m"
_MAGENTA = "\033[35m"
_DIM     = "\033[2m"

def _h(t: str) -> str: return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t: str) -> str: return f"{_GREEN}{t}{_RESET}"
def _dim(t: str) -> str: return f"{_DIM}{t}{_RESET}"
def _wave(t: str) -> str: return f"{_MAGENTA}{t}{_RESET}"


# ── Constants ─────────────────────────────────────────────────────────────────
EXAMPLE_DIR  = Path(__file__).parent
OUTPUT_DIR   = EXAMPLE_DIR / "output"
DATA_BASE    = Path(WORKSPACE_ROOT) / "examples" / "02_speech_commands" / "data"
LABELS       = ["yes", "no", "up", "down"]


# ── Build the fan-out DAG ─────────────────────────────────────────────────────

def build_parallel_graph() -> GraphIR:
    """Build a fan-out DAG: N independent branches, one per label class.

    Wave 0: N dataset_ingest nodes (source nodes — no predecessors)
    Wave 1: N audio_conditioner nodes
    Wave 2: N segmenter nodes
    Wave 3: N augmentation_pipeline nodes
    Wave 4: N audio_exporter nodes (sink nodes)

    All nodes in the same wave are independent and can run concurrently.
    """
    nodes: list[IRNode] = []
    edges: list[IREdge] = []

    for label in LABELS:
        data_path = str(DATA_BASE / label)
        out_path  = str(OUTPUT_DIR / label)

        # Node IDs are unique per label
        n_ingest  = f"dataset_ingest_{label}"
        n_cond    = f"audio_conditioner_{label}"
        n_seg     = f"segmenter_{label}"
        n_aug     = f"augmentation_pipeline_{label}"
        n_builder = f"dataset_builder_{label}"
        n_version = f"dataset_versioner_{label}"

        n_export  = f"audio_exporter_{label}"

        nodes += [
            IRNode(id=n_ingest,  node_type="dataset_ingest",
                   config={"path": data_path, "recursive": False, "source_type": "filesystem"}),
            IRNode(id=n_cond,    node_type="audio_conditioner",
                   config={"target_sample_rate": 16000}),
            IRNode(id=n_seg,     node_type="segmenter",
                   config={"silence_threshold_db": 40.0, "mode": "silence"}),
            IRNode(id=n_aug,     node_type="augmentation_pipeline",
                   config={"copies_per_sample": 1,
                           "augmentations": [{"type": "gain", "apply_prob": 1.0, "gain_db": [-3.0, 3.0]}]}),
            IRNode(id=n_export,  node_type="audio_exporter",
                   config={"output_dir": out_path,
                           "split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15},
                           "version_tag": "v1", "random_seed": 42, "append": False}),
        ]
        edges += [
            IREdge(src_id=n_ingest,  src_port="output", dst_id=n_cond,   dst_port="input"),
            IREdge(src_id=n_cond,    src_port="output", dst_id=n_seg,    dst_port="input"),
            IREdge(src_id=n_seg,     src_port="output", dst_id=n_aug,    dst_port="input"),
            IREdge(src_id=n_aug,     src_port="output", dst_id=n_export, dst_port="input"),
        ]

    return GraphIR(
        schema_version=CURRENT_IR_VERSION,
        metadata=IRMetadata(
            name="parallel-fan-out",
            seed=42,
            description=f"Fan-out DAG: {len(LABELS)} independent branches",
        ),
        nodes=nodes,
        edges=edges,
    )


# ── Wave inspector logger ─────────────────────────────────────────────────────

class WaveLogger(PipelineLogger):
    """Extends PipelineLogger to print wave events to the terminal."""

    def __init__(self) -> None:
        super().__init__()
        self.wave_events: list[dict] = []

    def wave_start(self, wave_index: int, node_ids: list[str]) -> None:
        super().wave_start(wave_index, node_ids)
        self.wave_events.append({"type": "wave_start", "index": wave_index, "nodes": node_ids})
        print(f"  {_wave(f'Wave {wave_index} starting')} — "
              f"{len(node_ids)} node(s): {_dim(', '.join(node_ids))}")

    def wave_end(self, wave_index: int, node_ids: list[str], duration_s: float) -> None:
        super().wave_end(wave_index, node_ids, duration_s)
        self.wave_events.append({"type": "wave_end", "index": wave_index,
                                  "nodes": node_ids, "duration_s": duration_s})
        print(f"  {_wave(f'Wave {wave_index} done')}    — "
              f"{duration_s:.3f}s  ({len(node_ids)} node(s) completed)")


# ── Run and time ──────────────────────────────────────────────────────────────

def run_pipeline(graph: GraphIR, parallel: bool, label: str) -> float:
    """Run the pipeline in the given mode and return wall-clock seconds."""
    from app.core.pipeline import run_pipeline_ir

    logger = WaveLogger() if parallel else PipelineLogger()
    t0 = time.perf_counter()
    run_pipeline_ir(graph, logger=logger, parallel=parallel, use_cache=False)
    return time.perf_counter() - t0


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Check data exists
    missing = [l for l in LABELS if not (DATA_BASE / l).exists()]
    if missing:
        print(f"Missing data directories: {missing}")
        print("Run first: venv/bin/python examples/prepare_real_data.py")
        sys.exit(1)

    # Ensure output directories exist
    for label in LABELS:
        (OUTPUT_DIR / label).mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"{_h('Example 09 — Parallel Wave Execution')}")
    print(f"{'='*60}")
    print(f"  Labels:  {', '.join(LABELS)}")
    print(f"  Data:    {DATA_BASE}")
    print(f"  Output:  {OUTPUT_DIR}")

    # Build the fan-out DAG
    graph = build_parallel_graph()
    total_nodes = len(graph.nodes)
    total_edges = len(graph.edges)
    print(f"\n  Graph: {total_nodes} nodes, {total_edges} edges")
    print(f"  Shape: {len(LABELS)} independent branches (fan-out DAG)")

    # Show the execution waves
    from app.core.pipeline import PipelineGraph, _ir_to_pipeline_config
    cfg = _ir_to_pipeline_config(graph)
    pg  = PipelineGraph(cfg)
    waves = pg.execution_waves
    print(f"\n  {_h('Execution Waves')} ({len(waves)} waves):")
    for i, wave in enumerate(waves):
        print(f"    Wave {i}: {len(wave)} node(s) — {_dim(', '.join(wave))}")

    # Save the graph.json for CLI use
    graph_path = EXAMPLE_DIR / "pipeline.graph.json"
    dump_ir_to_file(graph, str(graph_path))
    print(f"\n  Graph saved: {graph_path}")
    print(f"  CLI usage:   graphyn run --graph {graph_path} --parallel")

    # ── Sequential run ────────────────────────────────────────────────────────
    print(f"\n{_h('Sequential Run')} (parallel=False)")
    print(f"  {_dim('Nodes execute one at a time in topological order')}")
    t_seq = run_pipeline(graph, parallel=False, label="sequential")
    print(f"  {_ok('✓')} Sequential completed in {_BOLD}{t_seq:.2f}s{_RESET}")

    # ── Parallel run ──────────────────────────────────────────────────────────
    print(f"\n{_h('Parallel Run')} (parallel=True)")
    print(f"  {_dim('Nodes in the same wave execute concurrently via ThreadPoolExecutor')}")
    t_par = run_pipeline(graph, parallel=True, label="parallel")
    print(f"  {_ok('✓')} Parallel completed in {_BOLD}{t_par:.2f}s{_RESET}")

    # ── Speedup ───────────────────────────────────────────────────────────────
    speedup = t_seq / max(t_par, 0.001)
    print(f"\n{'='*60}")
    print(f"{_h('Results')}")
    print(f"{'='*60}")
    print(f"  Sequential:  {t_seq:.2f}s")
    print(f"  Parallel:    {t_par:.2f}s")
    print(f"  Speedup:     {_BOLD}{speedup:.1f}×{_RESET}")
    print(f"  Branches:    {len(LABELS)} (yes, no, up, down)")
    print(f"  Waves:       {len(waves)}")
    print(f"\n  Wave structure:")
    for i, wave in enumerate(waves):
        node_types = list({n.split('_')[0] for n in wave})
        print(f"    Wave {i}: {len(wave)} × {_dim(', '.join(sorted(node_types)))}")
    print(f"\n  Key insight: nodes in the same wave have no data dependency")
    print(f"  on each other — the executor runs them concurrently.")
    print(f"  The speedup scales with the number of independent branches.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
