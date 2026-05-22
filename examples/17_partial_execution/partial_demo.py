#!/usr/bin/env python3
"""
Example 17 — Partial Execution and Input Injection (Priority 11 — A3)
======================================================================
Demonstrates include_nodes, exclude_nodes, and input_overrides — the
Phase 3 partial execution features.

Use case: a developer wants to re-run only the augment and split nodes
of an existing pipeline, injecting pre-computed audio samples as input
rather than re-running the expensive file_input → clean → trim chain.

What this shows:
  - include_nodes — execute only a subset of the graph
  - exclude_nodes — skip specific nodes
  - input_overrides — inject data at a specific node's input port
  - How partial execution interacts with the cache
  - graphyn run --graph ... --include-nodes clean_0,split_0

Usage:
  venv/bin/python examples/17_partial_execution/partial_demo.py
"""
from __future__ import annotations

import sys
import time
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
_GREEN = "\033[32m"; _DIM = "\033[2m"; _YELLOW = "\033[33m"
def _h(t): return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t): return f"{_GREEN}{t}{_RESET}"
def _dim(t): return f"{_DIM}{t}{_RESET}"
def _warn(t): return f"{_YELLOW}{t}{_RESET}"

EXAMPLE_DIR = Path(__file__).parent
DATA_PATH   = Path(WORKSPACE_ROOT) / "examples" / "02_speech_commands" / "data" / "yes"
OUTPUT_DIR  = EXAMPLE_DIR / "output"


def build_pipeline():
    from app.core.sdk import Pipeline, PipelineNode
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return Pipeline(
        nodes=[
            PipelineNode("dataset_ingest",       {"path": str(DATA_PATH), "recursive": False, "source_type": "filesystem"}),
            PipelineNode("audio_conditioner",    {"target_sample_rate": 16000}),
            PipelineNode("segmenter",            {"silence_threshold_db": 40.0, "mode": "silence"}),
            PipelineNode("audio_quality_gate",   {"min_snr_db": 5.0}),
            PipelineNode("augmentation_pipeline",{"augmentations": [{"type": "gain", "gain_db": [-3.0, 3.0], "copies_per_sample": 1}]}),
            PipelineNode("feature_frontend", {
                "feature_type": "mfcc",
                "n_mfcc": 40,
                "n_fft": 512,
                "hop_length": 160,
                "fmax": 8000.0,
            }),
            PipelineNode("dataset_builder",      {"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}, "fixed_length": 101}),
            PipelineNode("dataset_versioner",    {"output_dir": str(OUTPUT_DIR),
                                                  "version_tag": "v1"}),
        ],
        seed=42,
    )


def _nodes_from_logs(run_mgr) -> tuple[list[str], list[str]]:
    """Return (executed_node_types, skipped_node_types) from a run's logs.json."""
    import json, os
    workspace = os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")
    logs_path = Path(workspace) / "runs" / run_mgr.run_id / "logs.json"
    executed, skipped = [], []
    if logs_path.exists():
        with open(logs_path) as f:
            logs = json.load(f)
        for entry in logs:
            if entry.get("type") == "node_end":
                executed.append(entry.get("node_type", "?"))
            elif entry.get("type") == "node_skip":
                skipped.append(entry.get("node_type", "?"))
    return executed, skipped


def main() -> None:
    if not DATA_PATH.exists():
        print(f"Missing data: {DATA_PATH}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(_h("Example 17 — Partial Execution and Input Injection"))
    print(f"{'='*60}")

    # ── Full run (baseline) ───────────────────────────────────────────
    print(f"\n{_h('Run 1 — Full pipeline (baseline)')}")
    pipeline = build_pipeline()
    t0 = time.perf_counter()
    result, run_mgr = pipeline.run_with_manager(use_cache=False)
    t_full = time.perf_counter() - t0
    executed, _ = _nodes_from_logs(run_mgr)
    print(f"  {_ok('✓')} Full run: {t_full:.2f}s  run_id={run_mgr.run_id[:8]}")
    print(f"    Nodes executed ({len(executed)}): {', '.join(executed)}")

    # ── exclude_nodes ─────────────────────────────────────────────────
    print(f"\n{_h('Run 2 — exclude_nodes=[\"augmentation_pipeline_4\"]')}")
    print(f"  {_dim('Skip the augmentation node — useful for quick validation runs')}")
    pipeline2 = build_pipeline()
    t0 = time.perf_counter()
    result2, run_mgr2 = pipeline2.run_with_manager(
        exclude_nodes=["augmentation_pipeline_4"],
        use_cache=False,
    )
    t_excl = time.perf_counter() - t0
    executed2, skipped2 = _nodes_from_logs(run_mgr2)
    print(f"  {_ok('✓')} Excluded augmentation_pipeline: {t_excl:.2f}s  run_id={run_mgr2.run_id[:8]}")
    print(f"    Nodes executed ({len(executed2)}): {', '.join(executed2)}")
    aug_skipped = "augmentation_pipeline" in skipped2
    print(f"    augmentation_pipeline skipped: {'✓ yes' if aug_skipped else '✗ no (check node ID)'}")

    # ── include_nodes with input_overrides ────────────────────────────
    print(f"\n{_h('Run 3 — include_nodes + input_overrides')}")
    print(f"  {_dim('Re-run only augmentation_pipeline→feature_frontend→dataset_builder→dataset_versioner, injecting pre-computed samples')}")

    # First, get the output of trim from the full run (simulate pre-computed data)
    from app.core.pipeline import run_pipeline_ir
    from app.core.ir.loader import load_ir, dump_ir
    from app.core.run_manager import RunManager
    from app.models.audio_sample import AudioSample
    import numpy as np

    # Create synthetic pre-computed samples (simulating cached trim output)
    rng = np.random.default_rng(42)
    pre_computed = [
        AudioSample(path=f"/fake/{i}.wav", sample_rate=16000,
                    data=rng.standard_normal(16000).astype(np.float32),
                    label="yes")
        for i in range(10)
    ]
    print(f"  Pre-computed samples: {len(pre_computed)} AudioSample objects")

    pipeline3 = build_pipeline()
    ir = load_ir(dump_ir(pipeline3.to_ir()))

    t0 = time.perf_counter()
    run_mgr3 = RunManager()
    run_pipeline_ir(
        ir,
        include_nodes=["augmentation_pipeline_4", "feature_frontend_5", "dataset_builder_6", "dataset_versioner_7"],
        input_overrides={"augmentation_pipeline_4": {"input": pre_computed}},
        run_manager=run_mgr3,
        use_cache=False,
    )
    t_partial = time.perf_counter() - t0
    executed3, _ = _nodes_from_logs(run_mgr3)
    print(f"  {_ok('✓')} Partial run (4/8 nodes): {t_partial:.2f}s  "
          f"run_id={run_mgr3.run_id[:8]}")
    print(f"    Nodes executed ({len(executed3)}): {', '.join(executed3)}")
    print(f"  Speedup vs full: {t_full/max(t_partial,0.001):.1f}×")

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{_h('Summary')}")
    print(f"  Full run (8 nodes):              {t_full:.2f}s")
    print(f"  exclude_nodes (7 nodes):         {t_excl:.2f}s")
    print(f"  include_nodes + overrides (4):   {t_partial:.2f}s")
    print(f"\n  include_nodes and exclude_nodes are mutually exclusive.")
    print(f"  input_overrides injects data at a specific node's input port.")
    print(f"\n  CLI:")
    print(f"  graphyn run --graph pipeline.graph.json \\")
    print(f"      --include-nodes augmentation_pipeline_4,feature_frontend_5,dataset_builder_6,dataset_versioner_7")
    print(f"  graphyn run --graph pipeline.graph.json \\")
    print(f"      --exclude-nodes augmentation_pipeline_4")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
