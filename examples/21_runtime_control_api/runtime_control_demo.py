#!/usr/bin/env python3
"""
Example 21 — Runtime Control via REST API and MCP (Priority 15 — A6)
=====================================================================
Demonstrates live control over a running pipeline:
pause → inspect → resume → cancel.

Uses both the REST API and the SDK's RunManager directly.

What this shows:
  - POST /api/v1/runs/{run_id}/pause   → {"status": "paused"}
  - POST /api/v1/runs/{run_id}/resume  → {"status": "running"}
  - POST /api/v1/runs/{run_id}/cancel  → {"status": "cancelled"}
  - GET  /api/v1/runs/{run_id}/status  → status + progress_pct
  - RunManager.pause() / resume() / cancel() — SDK control
  - _ACTIVE_RUNS registry — how active runs are tracked
  - MCP equivalents: pause_run, resume_run, cancel_run tools

Usage:
  # Terminal 1: start the API server
  venv/bin/uvicorn app.api.main:app --reload --port 8001

  # Terminal 2: run the demo
  venv/bin/python examples/21_runtime_control_api/runtime_control_demo.py
"""
from __future__ import annotations

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
_manager.install("PluginPackage/Audio/audio_quality_gate/")
_manager.install("PluginPackage/Audio/augmentation_pipeline/")
_manager.install("PluginPackage/Audio/feature_frontend/")
_manager.install("PluginPackage/Common/dataset_builder/")
_manager.install("PluginPackage/Common/dataset_versioner/")
_manager.load_enabled_plugins()

_RESET = "\033[0m"; _BOLD = "\033[1m"; _CYAN = "\033[36m"
_GREEN = "\033[32m"; _DIM = "\033[2m"; _YELLOW = "\033[33m"; _RED = "\033[31m"
def _h(t): return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t): return f"{_GREEN}{t}{_RESET}"
def _dim(t): return f"{_DIM}{t}{_RESET}"
def _warn(t): return f"{_YELLOW}{t}{_RESET}"
def _err(t): return f"{_RED}{t}{_RESET}"

EXAMPLE_DIR = Path(__file__).parent
DATA_PATH   = Path(WORKSPACE_ROOT) / "examples" / "02_speech_commands" / "data" / "yes"
OUTPUT_DIR  = EXAMPLE_DIR / "output"


# ── Demo A: SDK-level control ─────────────────────────────────────────────────

def demo_sdk_control() -> None:
    """Demonstrate pause/resume/cancel via RunManager directly (no HTTP)."""
    print(f"\n{_h('Demo A — SDK Runtime Control (no HTTP server needed)')}")

    from app.core.sdk import Pipeline, PipelineNode
    from app.core.run_manager import get_active_run

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pipeline = Pipeline(
        nodes=[
            PipelineNode("dataset_ingest",       {"path": str(DATA_PATH), "recursive": False, "source_type": "filesystem"}),
            PipelineNode("audio_conditioner",    {"target_sample_rate": 16000}),
            PipelineNode("segmenter",            {"silence_threshold_db": 40.0, "mode": "silence"}),
            PipelineNode("audio_quality_gate",   {"min_snr_db": 5.0}),
            PipelineNode("augmentation_pipeline",{"augmentations": [
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
            PipelineNode("dataset_builder",      {"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}, "fixed_length": 101}),
            PipelineNode("dataset_versioner",    {"output_dir": str(OUTPUT_DIR),
                                                  "version_tag": "v1"}),
        ],
        seed=42,
    )

    run_manager_ref = [None]
    result_holder   = [None]

    def _run():
        result, run_mgr = pipeline.run_with_manager(use_cache=False)
        result_holder[0]   = result
        run_manager_ref[0] = run_mgr

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    # Wait for run_manager to be allocated
    deadline = time.time() + 10
    while run_manager_ref[0] is None and time.time() < deadline:
        time.sleep(0.05)

    run_mgr = run_manager_ref[0]
    if run_mgr is None:
        print(f"  {_warn('⚠')} Pipeline completed before we could control it")
        thread.join(timeout=5)
        return

    run_id = run_mgr.run_id
    print(f"  Pipeline started — run_id: {_BOLD}{run_id}{_RESET}")

    # Wait for at least 1 node to start
    time.sleep(0.3)

    # ── Pause ─────────────────────────────────────────────────────────
    print(f"\n  {_dim('→')} Calling run_mgr.pause()...")
    run_mgr.pause()
    time.sleep(0.5)

    active = get_active_run(run_id)
    if active:
        print(f"  {_ok('✓')} Paused — run is still active (waiting between nodes)")
    else:
        print(f"  {_dim('(pipeline completed before pause took effect)')}")

    # ── Resume ────────────────────────────────────────────────────────
    print(f"\n  {_dim('→')} Calling run_mgr.resume()...")
    run_mgr.resume()
    time.sleep(0.5)
    print(f"  {_ok('✓')} Resumed")

    # ── Cancel ────────────────────────────────────────────────────────
    print(f"\n  {_dim('→')} Calling run_mgr.cancel()...")
    run_mgr.cancel()
    thread.join(timeout=15)

    # Read final status from meta.json
    import json, os
    workspace = os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")
    meta_path = Path(workspace) / "runs" / run_id / "meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        status = meta.get("status", "unknown")
        node_stats = meta.get("node_stats", [])
        completed = [s for s in node_stats if s.get("status") == "completed"]
        print(f"  {_ok('✓')} Final status: {_BOLD}{status}{_RESET}")
        print(f"    Nodes completed before cancel: {len(completed)}")
        for s in completed:
            print(f"      {_ok('✓')} {s.get('node_id', '?')}")
    else:
        print(f"  {_dim('(meta.json not found)')}")


# ── Demo B: REST API control ──────────────────────────────────────────────────

def demo_rest_control(base_url: str) -> None:
    """Demonstrate pause/resume/cancel via REST API."""
    print(f"\n{_h('Demo B — REST API Runtime Control')}")
    print(f"  Server: {base_url}")

    import httpx

    # Check server is up
    try:
        resp = httpx.get(f"{base_url}/api/v1/system/health", timeout=3)
        if resp.status_code != 200:
            print(f"  {_warn('⚠')} Server not healthy — skipping REST demo")
            print(f"  Start with: venv/bin/uvicorn app.api.main:app --port 8001")
            return
    except Exception:
        print(f"  {_warn('⚠')} Server not reachable at {base_url} — skipping REST demo")
        print(f"  Start with: venv/bin/uvicorn app.api.main:app --port 8001")
        return

    # Build IR JSON pipeline
    from app.core.ir.loader import CURRENT_IR_VERSION, dump_ir
    from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    nodes = [
        IRNode(id="dataset_ingest_0",        node_type="dataset_ingest",
               config={"path": str(DATA_PATH), "recursive": False, "source_type": "filesystem"}),
        IRNode(id="audio_conditioner_1",     node_type="audio_conditioner",
               config={"target_sample_rate": 16000}),
        IRNode(id="segmenter_2",             node_type="segmenter",
               config={"silence_threshold_db": 40.0, "mode": "silence"}),
        IRNode(id="audio_quality_gate_3",    node_type="audio_quality_gate",
               config={"min_snr_db": 5.0}),
        IRNode(id="augmentation_pipeline_4", node_type="augmentation_pipeline",
               config={"augmentations": [
                   {"type": "gain",        "gain_db": [-3.0, 3.0],   "copies_per_sample": 1},
                   {"type": "pitch_shift", "semitones": [-2.0, 2.0], "copies_per_sample": 1},
               ]}),
        IRNode(id="feature_frontend_4b",     node_type="feature_frontend",
               config={"feature_type": "mfcc", "n_mfcc": 40, "n_fft": 512,
                       "hop_length": 160, "fmax": 8000.0}),
        IRNode(id="dataset_builder_5",       node_type="dataset_builder",
               config={"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}, "fixed_length": 101}),
        IRNode(id="dataset_versioner_6",     node_type="dataset_versioner",
               config={"output_dir": str(OUTPUT_DIR),
                       "version_tag": "v1"}),
    ]
    edges = [IREdge(src_id=nodes[i].id, src_port="output",
                    dst_id=nodes[i+1].id, dst_port="input")
             for i in range(len(nodes)-1)]
    graph = GraphIR(schema_version=CURRENT_IR_VERSION,
                    metadata=IRMetadata(name="control-demo", seed=42),
                    nodes=nodes, edges=edges)
    graph_dict = dump_ir(graph)

    with httpx.Client(timeout=30) as client:
        # Start async run
        resp = client.post(f"{base_url}/api/v1/pipelines/run-async", json=graph_dict)
        run_id = resp.json()["run_id"]
        print(f"  {_ok('✓')} Run started — run_id: {_BOLD}{run_id}{_RESET}")

        time.sleep(0.3)

        # Pause
        resp = client.post(f"{base_url}/api/v1/runs/{run_id}/pause")
        data = resp.json()
        if resp.status_code == 200:
            print(f"  {_ok('✓')} Paused:  {data}")
        else:
            print(f"  {_warn('⚠')} Pause: HTTP {resp.status_code} — {data}")

        time.sleep(0.3)

        # Status check
        resp = client.get(f"{base_url}/api/v1/runs/{run_id}/status")
        status_data = resp.json()
        print(f"  {_dim('→')} Status: {status_data.get('status')}  "
              f"progress: {status_data.get('progress_pct') or 0:.0f}%")

        # Resume
        resp = client.post(f"{base_url}/api/v1/runs/{run_id}/resume")
        data = resp.json()
        if resp.status_code == 200:
            print(f"  {_ok('✓')} Resumed: {data}")
        else:
            print(f"  {_warn('⚠')} Resume: HTTP {resp.status_code} — {data}")

        time.sleep(0.3)

        # Cancel
        resp = client.post(f"{base_url}/api/v1/runs/{run_id}/cancel")
        data = resp.json()
        if resp.status_code == 200:
            print(f"  {_ok('✓')} Cancelled: {data}")
        else:
            print(f"  {_warn('⚠')} Cancel: HTTP {resp.status_code} — {data}")

        # Poll until done
        for _ in range(20):
            time.sleep(1)
            resp = client.get(f"{base_url}/api/v1/runs/{run_id}/status")
            s = resp.json().get("status", "unknown")
            if s in ("completed", "failed", "cancelled"):
                print(f"  {_ok('✓')} Final status: {_BOLD}{s}{_RESET}")
                break

    print(f"\n  REST API endpoints used:")
    print(f"    POST /api/v1/pipelines/run-async  → start")
    print(f"    POST /api/v1/runs/{{run_id}}/pause   → pause")
    print(f"    GET  /api/v1/runs/{{run_id}}/status  → poll")
    print(f"    POST /api/v1/runs/{{run_id}}/resume  → resume")
    print(f"    POST /api/v1/runs/{{run_id}}/cancel  → cancel")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Example 21 — Runtime Control")
    parser.add_argument("--url", default="http://localhost:8001",
                        help="API server URL (default: http://localhost:8001)")
    parser.add_argument("--sdk-only", action="store_true",
                        help="Run SDK demo only (no HTTP server needed)")
    args = parser.parse_args()

    if not DATA_PATH.exists():
        print(f"Missing data: {DATA_PATH}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(_h("Example 21 — Runtime Control via REST API and SDK"))
    print(f"{'='*60}")
    print(f"\n  Demonstrates: pause → inspect → resume → cancel")
    print(f"  Both SDK (RunManager) and REST API paths shown.")

    # Demo A: SDK control (always runs)
    demo_sdk_control()

    # Demo B: REST API control (requires server)
    if not args.sdk_only:
        demo_rest_control(args.url)

    print(f"\n{_h('MCP equivalents')}")
    print(f"  pause_run  {{\"run_id\": \"{'{run_id}'}\"}}  → {{\"status\": \"paused\"}}")
    print(f"  resume_run {{\"run_id\": \"{'{run_id}'}\"}}  → {{\"status\": \"running\"}}")
    print(f"  cancel_run {{\"run_id\": \"{'{run_id}'}\"}}  → {{\"status\": \"cancelled\"}}")
    print(f"\n  All three interfaces (SDK, REST, MCP) delegate to the same")
    print(f"  RunManager.pause()/resume()/cancel() implementation.")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
