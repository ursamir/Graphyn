#!/usr/bin/env python3
"""
Example 15 — Event-Driven Pipeline (Priority 9 — A5)
=====================================================
Demonstrates event_driven=True with FileWatcherSource and TimerSource.

A pipeline watches a directory for new WAV files and processes each one
through clean → trim → silence_detector. Runs for a fixed duration then
cancels gracefully.

What this shows:
  - event_driven=True on Pipeline.run()
  - IRNode.event_trigger — binding a node to a FileWatcherSource
  - FileWatcherSource — watches a directory for new .wav files
  - TimerSource — alternative: fires every N seconds
  - run.cancel() — graceful shutdown
  - How to write an event-triggered node in the graph JSON

Usage:
  venv/bin/python examples/15_event_driven_pipeline/event_driven_demo.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import threading
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
_manager.install("PluginPackage/Audio/audio_exporter/")
_manager.load_enabled_plugins()

_RESET = "\033[0m"; _BOLD = "\033[1m"; _CYAN = "\033[36m"
_GREEN = "\033[32m"; _DIM = "\033[2m"; _YELLOW = "\033[33m"
def _h(t): return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t): return f"{_GREEN}{t}{_RESET}"
def _dim(t): return f"{_DIM}{t}{_RESET}"
def _warn(t): return f"{_YELLOW}{t}{_RESET}"

EXAMPLE_DIR  = Path(__file__).parent
WATCH_DIR    = EXAMPLE_DIR / "watch_inbox"
OUTPUT_DIR   = EXAMPLE_DIR / "output"
SOURCE_WAVS  = list((Path(WORKSPACE_ROOT) / "examples" / "02_speech_commands" / "data" / "yes").glob("*.wav"))[:5]


def demo_timer_source() -> None:
    """Demo 1: TimerSource — fires every 2 seconds, runs for 6 seconds."""
    print(f"\n{_h('Demo 1 — TimerSource (fires every 2s, runs 6s)')}")

    from app.core.events import TimerSource

    tick_count = [0]
    done_event = asyncio.Event()

    async def _run():
        source = TimerSource(interval_s=2.0)
        async for event in source.watch():
            tick_count[0] += 1
            print(f"  {_ok('tick')} #{event['tick']}  {_dim(event['timestamp'])}")
            if tick_count[0] >= 3:
                done_event.set()
                break

    asyncio.run(_run())
    print(f"  {_ok('✓')} TimerSource fired {tick_count[0]} times")


def demo_file_watcher() -> None:
    """Demo 2: FileWatcherSource — watches a directory, processes new WAV files."""
    print(f"\n{_h('Demo 2 — FileWatcherSource (watches directory for new WAV files)')}")

    if not SOURCE_WAVS:
        print(f"  {_warn('⚠')} No source WAV files found — skipping file watcher demo")
        print(f"  Run: venv/bin/python examples/prepare_real_data.py")
        return

    # Set up watch directory
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Clean up any previous files
    for f in WATCH_DIR.glob("*.wav"):
        f.unlink()

    print(f"  Watch dir: {WATCH_DIR}")
    print(f"  Will drop {len(SOURCE_WAVS)} WAV files into the watch dir...")

    from app.core.ir.loader import CURRENT_IR_VERSION
    from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode
    from app.core.pipeline import run_pipeline_ir
    from app.core.logger import PipelineLogger

    # Build a simple pipeline: dataset_ingest → audio_conditioner → segmenter → audio_exporter
    # In event-driven mode, dataset_ingest has an event_trigger that binds it
    # to the FileWatcherSource watching WATCH_DIR
    graph = GraphIR(
        schema_version=CURRENT_IR_VERSION,
        metadata=IRMetadata(name="event-driven-demo", seed=42),
        nodes=[
            IRNode(id="dataset_ingest_0",    node_type="dataset_ingest",
                   config={"path": str(WATCH_DIR), "recursive": False, "source_type": "filesystem"},
                   event_trigger={"source_type": "file_watcher",
                                  "source_config": {"path": str(WATCH_DIR), "pattern": "*.wav"}}),
            IRNode(id="audio_conditioner_1", node_type="audio_conditioner",
                   config={"target_sample_rate": 16000}),
            IRNode(id="segmenter_2",         node_type="segmenter",
                   config={"silence_threshold_db": 40.0, "mode": "silence"}),
            IRNode(id="audio_exporter_3",    node_type="audio_exporter",
                   config={"output_dir": str(OUTPUT_DIR), "version_tag": "v1",
                           "split_ratios": {"train": 1.0}, "append": True}),
        ],
        edges=[
            IREdge(src_id="dataset_ingest_0",    src_port="output", dst_id="audio_conditioner_1", dst_port="input"),
            IREdge(src_id="audio_conditioner_1", src_port="output", dst_id="segmenter_2",         dst_port="input"),
            IREdge(src_id="segmenter_2",         src_port="output", dst_id="audio_exporter_3",    dst_port="input"),
        ],
    )

    run_manager_ref = [None]
    logger = PipelineLogger()

    def _run_pipeline():
        from app.core.run_manager import RunManager
        run_mgr = RunManager()
        run_manager_ref[0] = run_mgr
        try:
            # Pipeline.run() supports event_driven=True — here we use the
            # lower-level run_pipeline_ir to pass a shared logger for inspection
            run_pipeline_ir(graph, logger=logger, event_driven=True,
                            run_manager=run_mgr, use_cache=False)
        except Exception:
            pass

    # Start pipeline in background thread
    thread = threading.Thread(target=_run_pipeline, daemon=True)
    thread.start()

    # Wait for run_manager to be available
    deadline = time.time() + 5
    while run_manager_ref[0] is None and time.time() < deadline:
        time.sleep(0.1)

    # Drop WAV files into the watch directory one by one
    print(f"\n  Dropping files into watch dir...")
    for i, wav in enumerate(SOURCE_WAVS):
        dest = WATCH_DIR / f"clip_{i:02d}.wav"
        shutil.copy(wav, dest)
        print(f"  {_dim('→')} dropped {dest.name}")
        time.sleep(1.5)

    # Let the pipeline process the files
    time.sleep(2)

    # Cancel the pipeline
    run_mgr = run_manager_ref[0]
    if run_mgr:
        run_mgr.cancel()
        print(f"\n  {_ok('✓')} Pipeline cancelled gracefully")
        print(f"    run_id: {run_mgr.run_id}")

    thread.join(timeout=5)

    # Count node_end events
    node_ends = [e for e in logger.logs if e.get("type") == "node_end"]
    print(f"  {_ok('✓')} node_end events: {len(node_ends)}")
    for e in node_ends[:12]:
        print(f"    {_dim(e.get('node_type', '?'))}: {e.get('output_count', 0)} items")

    # Report output files written
    out_v1 = OUTPUT_DIR / "v1"
    if out_v1.exists():
        wav_files = list(out_v1.rglob("*.wav"))
        print(f"  {_ok('✓')} Output WAV files written: {len(wav_files)}")
        print(f"    Location: {out_v1}")


def main() -> None:
    print(f"\n{'='*60}")
    print(_h("Example 15 — Event-Driven Pipeline"))
    print(f"{'='*60}")
    print(f"\n  event_driven=True runs the pipeline indefinitely,")
    print(f"  triggering on events from FileWatcherSource or TimerSource.")
    print(f"  run.cancel() stops execution gracefully after the current node.")

    demo_timer_source()
    demo_file_watcher()

    print(f"\n{_h('Key concepts')}")
    print(f"  IRNode.event_trigger = {{")
    print(f"    'source_type': 'file_watcher',")
    print(f"    'source_config': {{'path': '/watch/dir', 'pattern': '*.wav'}}")
    print(f"  }}")
    print(f"  pipeline.run(event_driven=True)  — runs indefinitely")
    print(f"  run.cancel()                     — graceful shutdown")
    print(f"\n  CLI: graphyn run --graph pipeline.graph.json --event-driven")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
