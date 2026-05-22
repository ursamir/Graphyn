#!/usr/bin/env python3
"""
Example 10 — Resumable Pipeline with Checkpointing (Priority 4 — A2)
======================================================================
Demonstrates checkpoint-based resumability — a pipeline that is cancelled
mid-run and then resumed from the last checkpoint without re-processing
completed nodes.

What this shows:
  - pipeline.run(checkpoint=True)         — write per-node checkpoints
  - pipeline.run(resume_run_id=run_id)    — resume from prior run
  - resume_state.json                     — tracks completed nodes
  - node_skip(reason="resumed_from_checkpoint") — skipped node log events
  - run_with_manager()                    — access RunManager for control
  - run.cancel()                          — graceful cancellation
  - graphyn runs list                — find the interrupted run ID
  - graphyn run --graph ... --resume <run_id>  — CLI resume

Pipeline: dataset_ingest → audio_conditioner → segmenter → audio_quality_gate →
          augmentation_pipeline → audio_exporter

The pipeline is run with checkpoint=True. After 3 nodes complete,
run.cancel() is called. The run is then resumed — only the remaining
nodes execute; completed nodes are skipped.

Usage:
  venv/bin/python examples/10_resumable_pipeline/resumable_pipeline.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from app.core.sdk import Pipeline, PipelineNode  # noqa: E402
from app.core.ir.loader import dump_ir_to_file   # noqa: E402
from app.core.plugins.manager import PluginManager  # noqa: E402

# ── Install required plugins ──────────────────────────────────────────────────
_manager = PluginManager()
_manager.install("PluginPackage/Audio/dataset_ingest/")
_manager.install("PluginPackage/Audio/audio_conditioner/")
_manager.install("PluginPackage/Audio/segmenter/")
_manager.install("PluginPackage/Audio/audio_quality_gate/")
_manager.install("PluginPackage/Audio/augmentation_pipeline/")
_manager.install("PluginPackage/Audio/audio_exporter/")
_manager.load_enabled_plugins()

# ── Colours ───────────────────────────────────────────────────────────────────
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_DIM    = "\033[2m"

def _h(t: str) -> str: return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t: str) -> str: return f"{_GREEN}{t}{_RESET}"
def _warn(t: str) -> str: return f"{_YELLOW}{t}{_RESET}"
def _err(t: str) -> str: return f"{_RED}{t}{_RESET}"
def _dim(t: str) -> str: return f"{_DIM}{t}{_RESET}"


# ── Constants ─────────────────────────────────────────────────────────────────
EXAMPLE_DIR = Path(__file__).parent
OUTPUT_DIR  = EXAMPLE_DIR / "output"
DATA_PATH   = Path(WORKSPACE_ROOT) / "examples" / "02_speech_commands" / "data" / "yes"


# ── Build pipeline ────────────────────────────────────────────────────────────

def build_pipeline() -> Pipeline:
    """Build a multi-stage preprocessing pipeline."""
    return Pipeline(
        nodes=[
            PipelineNode("dataset_ingest",       {"path": str(DATA_PATH), "recursive": False, "source_type": "filesystem"}),
            PipelineNode("audio_conditioner",    {"target_sample_rate": 16000}),
            PipelineNode("segmenter",            {"silence_threshold_db": 40.0, "mode": "silence"}),
            PipelineNode("audio_quality_gate",   {"min_snr_db": 5.0, "rejection_policy": "skip"}),
            PipelineNode("augmentation_pipeline",{
                "copies_per_sample": 2,
                "augmentations": [
                    {"type": "gain",        "apply_prob": 1.0, "gain_db": [-3.0, 3.0]},
                    {"type": "pitch_shift", "apply_prob": 1.0, "semitones": [-2.0, 2.0]},
                    {"type": "time_stretch","apply_prob": 1.0, "rate": [0.9, 1.1]},
                ],
            }),
            PipelineNode("audio_exporter", {
                "output_dir": str(OUTPUT_DIR),
                "split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15},
                "version_tag": "v1",
                "random_seed": 42,
                "append": False,
            }),
        ],
        seed=42,
        name="resumable-demo",
    )


# ── Phase 1: Run with checkpoint, cancel mid-run after first 3 nodes ─────────

def phase1_run_with_checkpoint() -> str:
    """Start the pipeline with checkpointing and cancel it after 3 nodes complete.

    Uses a background thread to call run_mgr.cancel() once the first 3 nodes
    have written their checkpoints, producing a genuinely interrupted run.
    Phase 2 then resumes from those checkpoints.
    """
    import json, os, threading
    workspace = os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")

    print(f"\n{_h('Phase 1 — Run with Checkpointing, Cancel After 3 Nodes')}")
    print(f"  {_dim('checkpoint=True writes per-node WAV files to workspace/runs/{id}/checkpoints/')}")
    print(f"  {_dim('A background thread calls run_mgr.cancel() after 3 checkpoints appear.')}")

    pipeline = build_pipeline()
    total_nodes = len(pipeline.nodes)
    print(f"  Pipeline: {total_nodes} nodes")

    # Save graph.json for CLI use
    graph_path = EXAMPLE_DIR / "pipeline.graph.json"
    dump_ir_to_file(pipeline.to_ir(), str(graph_path))
    print(f"  Graph saved: {graph_path}")

    # We need the run_manager before the pipeline starts so the cancel thread
    # can reference it. run_with_manager() creates it internally, so we watch
    # the workspace/runs/ directory for a new run and grab its RunManager via
    # the active-run registry.
    run_mgr_ref: list = [None]
    cancel_after = 3  # cancel once this many checkpoint dirs exist

    def _cancel_watcher():
        """Poll for checkpoints and cancel after cancel_after nodes complete."""
        from app.core.run_manager import get_active_run
        deadline = time.time() + 120
        while time.time() < deadline:
            time.sleep(0.3)
            # Find the run_manager once it's registered
            if run_mgr_ref[0] is None:
                # Scan active runs — the pipeline registers itself on start
                runs_base = Path(workspace) / "runs"
                if runs_base.exists():
                    for run_dir in sorted(runs_base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                        rm = get_active_run(run_dir.name)
                        if rm is not None:
                            run_mgr_ref[0] = rm
                            break
                continue

            rm = run_mgr_ref[0]
            checkpoint_base = Path(workspace) / "runs" / rm.run_id / "checkpoints"
            if checkpoint_base.exists():
                n_done = len(list(checkpoint_base.iterdir()))
                if n_done >= cancel_after:
                    print(f"\n  {_warn('→')} Cancel triggered after {n_done} checkpoint(s) written")
                    rm.cancel()
                    return

    watcher = threading.Thread(target=_cancel_watcher, daemon=True)
    watcher.start()

    print(f"\n  Running with checkpoint=True (will be cancelled after {cancel_after} nodes)...")
    t0 = time.perf_counter()
    try:
        _, run_mgr = pipeline.run_with_manager(checkpoint=True, use_cache=False)
    except Exception as exc:
        # Cancellation may surface as an exception depending on executor version
        run_mgr = run_mgr_ref[0]
        if run_mgr is None:
            raise
        print(f"  {_dim(f'Pipeline stopped: {type(exc).__name__}')}")
    elapsed = time.perf_counter() - t0
    watcher.join(timeout=5)

    run_id = run_mgr.run_id
    print(f"  {_ok('✓')} Phase 1 stopped in {elapsed:.2f}s  run_id={_BOLD}{run_id}{_RESET}")

    # Read completed nodes from resume_state.json
    resume_state_path = Path(workspace) / "runs" / run_id / "resume_state.json"
    resume_state: dict = {}
    completed_nodes: list[str] = []
    if resume_state_path.exists():
        with open(resume_state_path) as f:
            resume_state = json.load(f)
        completed_nodes = resume_state.get("completed_nodes", [])

    print(f"\n    completed nodes ({len(completed_nodes)}):")
    for nid in completed_nodes:
        print(f"      {_ok('✓')} {nid}")

    # Show checkpoint files
    checkpoint_dir = Path(workspace) / "runs" / run_id / "checkpoints"
    if checkpoint_dir.exists():
        checkpoints = sorted(checkpoint_dir.iterdir())
        print(f"    checkpoints written: {len(checkpoints)}")
        for cp in checkpoints:
            manifest = cp / "manifest.json"
            if manifest.exists():
                with open(manifest) as f:
                    m = json.load(f)
                n_samples = len(m.get("samples", []))
                print(f"      {_dim(cp.name)}: {n_samples} samples")

    if not completed_nodes:
        print(f"  {_warn('⚠')} No checkpoints written — pipeline may have completed too fast.")
        print(f"  {_dim('Phase 2 will re-run the full pipeline (nothing to resume).')}")

    return run_id


# ── Phase 2: Resume from checkpoint ──────────────────────────────────────────

def phase2_resume(run_id: str) -> None:
    """Resume the pipeline from the interrupted run's checkpoints."""
    print(f"\n{_h('Phase 2 — Resume from Checkpoint')}")
    print(f"  {_dim('resume_run_id=' + repr(run_id))}")
    print(f"  {_dim('Completed nodes will be skipped; their outputs loaded from checkpoints')}")

    pipeline = build_pipeline()

    print(f"\n  Resuming run {_BOLD}{run_id}{_RESET}...")
    t0 = time.perf_counter()

    result, run_mgr = pipeline.run_with_manager(
        resume_run_id=run_id,
        checkpoint=True,
        use_cache=False,
    )

    elapsed = time.perf_counter() - t0
    print(f"\n  {_ok('✓')} Resume completed in {elapsed:.2f}s")
    print(f"    new run_id: {_BOLD}{run_mgr.run_id}{_RESET}")

    # Show which nodes were skipped vs executed
    # node_stats in meta.json: {node_id, node_type, node_index, duration_s}
    # skipped nodes appear in logs with type="node_skip"
    import json, os
    workspace = os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")
    meta_path = Path(workspace) / "runs" / run_mgr.run_id / "meta.json"
    logs_path = Path(workspace) / "runs" / run_mgr.run_id / "logs.json"

    executed_ids: set[str] = set()
    skipped_ids: set[str] = set()

    if logs_path.exists():
        with open(logs_path) as f:
            logs = json.load(f)
        for entry in logs:
            if entry.get("type") == "node_end":
                executed_ids.add(entry.get("node_type", ""))
            elif entry.get("type") == "node_skip":
                skipped_ids.add(entry.get("node_type", ""))

    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        node_stats = meta.get("node_stats", [])
        print(f"\n  Node execution summary:")
        for stat in node_stats:
            nid  = stat.get("node_id", "?")
            ntype = stat.get("node_type", "?")
            dur  = stat.get("duration_s", 0)
            print(f"    {_ok('✓')} {nid:<35} {dur:.3f}s")

    # Show skipped nodes from logs
    if skipped_ids:
        print(f"  Skipped nodes (loaded from checkpoint):")
        for ntype in sorted(skipped_ids):
            print(f"    {_dim('⏭')} {ntype}")

    # Verify the resume actually skipped some nodes
    if executed_ids and skipped_ids:
        print(f"\n  {_ok('✓')} Resume confirmed: {len(skipped_ids)} node(s) skipped, "
              f"{len(executed_ids)} re-executed")
    elif executed_ids and not skipped_ids:
        print(f"\n  {_warn('⚠')} No nodes were skipped — the pipeline ran fully.")
        print(f"  {_dim('This happens when Phase 1 completed before the cancel took effect.')}")
        print(f"  {_dim('The resume mechanism is correct; the pipeline was just too fast to interrupt.')}")
    else:
        print(f"\n  {_dim('(logs.json not found — cannot verify skip behaviour)')}")

    # Show output
    output_dir = OUTPUT_DIR / "resumable_demo" / "v1"
    if output_dir.exists():
        wav_files = list(output_dir.rglob("*.wav"))
        print(f"\n  Output: {len(wav_files)} WAV files in {output_dir}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not DATA_PATH.exists():
        print(_err(f"Error: data path not found: {DATA_PATH}"))
        print("Run first: venv/bin/python examples/prepare_real_data.py")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"{_h('Example 10 — Resumable Pipeline with Checkpointing')}")
    print(f"{'='*60}")
    print(f"  Data:   {DATA_PATH}")
    print(f"  Output: {OUTPUT_DIR}")

    # Phase 1: run with checkpoint, cancel mid-run
    run_id = phase1_run_with_checkpoint()

    # Phase 2: resume from checkpoint
    phase2_resume(run_id)

    print(f"\n{'='*60}")
    print(f"{_h('Summary')}")
    print(f"{'='*60}")
    print(f"  Phase 1: pipeline.run_with_manager(checkpoint=True)")
    print(f"           → writes resume_state.json + per-node checkpoints")
    print(f"           → cancelled after 3 nodes via run.cancel()")
    print(f"  Phase 2: pipeline.run_with_manager(resume_run_id=run_id)")
    print(f"           → skips completed nodes (loads from checkpoints)")
    print(f"           → executes only remaining nodes")
    print(f"\n  CLI equivalent:")
    print(f"    # Phase 1 (run until interrupted)")
    print(f"    graphyn run --graph examples/10_resumable_pipeline/pipeline.graph.json \\")
    print(f"        --checkpoint")
    print(f"    # Find the run_id")
    print(f"    graphyn runs list")
    print(f"    # Phase 2 (resume)")
    print(f"    graphyn run --graph examples/10_resumable_pipeline/pipeline.graph.json \\")
    print(f"        --resume <run_id>")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
