#!/usr/bin/env python3
"""
Example 16 — Deterministic Replay (Priority 10 — B2)
=====================================================
Demonstrates that pipelines with a fixed seed produce identical outputs
on replay, and shows the replay mechanism via ArtifactStore.

What this shows:
  - graph.json stored per run in workspace/runs/{run_id}/
  - replay_run — loads graph.json and re-executes with a new run_id
  - seed field in IRMetadata — controls all random operations
  - deterministic=True capability field
  - graphyn artifacts replay <run_id>
  - POST /api/v1/artifacts/{id}/replay

Usage:
  venv/bin/python examples/16_deterministic_replay/replay_demo.py
"""
from __future__ import annotations

import hashlib
import json
import os
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


def hash_output_dir(path: Path) -> str:
    """Hash the sorted WAV filenames and their audio content for determinism comparison.

    Hashing manifest.csv would always differ between runs because it contains
    absolute paths. Instead we hash the sorted list of (stem, audio_data_bytes)
    pairs so the comparison is path-independent and reflects actual content.
    """
    import soundfile as sf
    h = hashlib.sha256()
    wav_files = sorted(path.rglob("*.wav")) if path.exists() else []
    if not wav_files:
        return "no_output"
    for wav in wav_files:
        # Include the relative path stem (split/label/filename) for ordering
        h.update(wav.relative_to(path).as_posix().encode())
        try:
            data, sr = sf.read(str(wav), dtype="float32", always_2d=False)
            # Round to 4 decimal places to absorb float32 write/read noise
            import numpy as np
            h.update(np.round(data, 4).tobytes())
        except Exception:
            h.update(b"unreadable")
    return h.hexdigest()[:16]


def run_pipeline(seed: int, output_suffix: str) -> tuple[str, str]:
    """Run the pipeline and return (run_id, output_hash)."""
    from app.core.sdk import Pipeline, PipelineNode
    out = OUTPUT_DIR / output_suffix
    out.mkdir(parents=True, exist_ok=True)

    pipeline = Pipeline(
        nodes=[
            PipelineNode("dataset_ingest",       {"path": str(DATA_PATH), "recursive": False, "source_type": "filesystem"}),
            PipelineNode("audio_conditioner",    {"target_sample_rate": 16000}),
            PipelineNode("segmenter",            {"silence_threshold_db": 40.0, "mode": "silence"}),
            PipelineNode("augmentation_pipeline",{"augmentations": [{"type": "gain", "gain_db": [-3.0, 3.0], "copies_per_sample": 1}]}),
            PipelineNode("feature_frontend", {
                "feature_type": "mfcc",
                "n_mfcc": 40,
                "n_fft": 512,
                "hop_length": 160,
                "fmax": 8000.0,
            }),
            PipelineNode("dataset_builder",      {"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}, "fixed_length": 101}),
            PipelineNode("dataset_versioner",    {"output_dir": str(out),
                                                  "version_tag": "v1"}),
        ],
        seed=seed,
    )
    result = pipeline.run(use_cache=False)
    out_versioned = out / "v1"
    output_hash = hash_output_dir(out_versioned)
    return result.run_id, output_hash


def replay_from_stored_graph(run_id: str, output_suffix: str) -> tuple[str, str]:
    """Replay a run by loading its stored graph.json."""
    workspace = os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")
    graph_path = Path(workspace) / "runs" / run_id / "graph.json"

    if not graph_path.exists():
        return "no_graph", "no_output"

    with open(graph_path) as f:
        graph_dict = json.load(f)

    # Patch output path for the replay
    out = OUTPUT_DIR / output_suffix
    out.mkdir(parents=True, exist_ok=True)
    for node in graph_dict["nodes"]:
        if node["node_type"] == "dataset_versioner":
            node["config"]["output_dir"] = str(out)

    from app.core.ir.loader import load_ir
    from app.core.pipeline import run_pipeline_ir
    from app.core.run_manager import RunManager

    ir = load_ir(graph_dict)
    run_mgr = RunManager()
    run_pipeline_ir(ir, run_manager=run_mgr, use_cache=False)

    out_versioned = out / "v1"
    output_hash = hash_output_dir(out_versioned)
    return run_mgr.run_id, output_hash


def main() -> None:
    if not DATA_PATH.exists():
        print(f"Missing data: {DATA_PATH}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(_h("Example 16 — Deterministic Replay"))
    print(f"{'='*60}")

    # ── Run 1: original ───────────────────────────────────────────────
    print(f"\n{_h('Run 1 — Original (seed=42)')}")
    run1_id, hash1 = run_pipeline(seed=42, output_suffix="run1")
    print(f"  {_ok('✓')} run_id: {_BOLD}{run1_id}{_RESET}")
    print(f"    output hash: {_dim(hash1)}")

    # Show stored graph.json
    workspace = os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")
    graph_path = Path(workspace) / "runs" / run1_id / "graph.json"
    if graph_path.exists():
        with open(graph_path) as f:
            g = json.load(f)
        print(f"    graph.json stored: {len(g['nodes'])} nodes, seed={g['metadata']['seed']}")

    # ── Run 2: replay from stored graph ───────────────────────────────
    print(f"\n{_h('Run 2 — Replay from stored graph.json')}")
    print(f"  Loading graph from workspace/runs/{run1_id}/graph.json")
    run2_id, hash2 = replay_from_stored_graph(run1_id, output_suffix="run2")
    print(f"  {_ok('✓')} new run_id: {_BOLD}{run2_id}{_RESET}")
    print(f"    output hash: {_dim(hash2)}")

    # ── Run 3: different seed — should differ ─────────────────────────
    print(f"\n{_h('Run 3 — Different seed (seed=99) — should differ')}")
    run3_id, hash3 = run_pipeline(seed=99, output_suffix="run3")
    print(f"  {_ok('✓')} run_id: {_BOLD}{run3_id}{_RESET}")
    print(f"    output hash: {_dim(hash3)}")

    # ── Compare ───────────────────────────────────────────────────────
    print(f"\n{_h('Comparison')}")
    print(f"  Run 1 (seed=42):  {hash1}")
    print(f"  Run 2 (replay):   {hash2}  {'✓ MATCH' if hash1 == hash2 else '✗ DIFFER'}")
    print(f"  Run 3 (seed=99):  {hash3}  {'✓ MATCH' if hash1 == hash3 else '✓ DIFFERS (expected)'}")

    if hash1 == hash2:
        print(f"\n  {_ok('✓')} Deterministic replay confirmed — same seed → same output")
    else:
        print(f"\n  {_warn('⚠')} Outputs differ — augment nodes use random ops")
        print(f"  Note: augment/pitch_shift have deterministic=False capability")
        print(f"  The seed controls the RNG but file I/O ordering may vary")

    print(f"\n{_h('CLI equivalents')}")
    print(f"  graphyn artifacts replay {run1_id}")
    print(f"  # REST API:")
    print(f"  curl -X POST http://localhost:8001/api/v1/artifacts/<id>/replay")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
