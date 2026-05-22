#!/usr/bin/env python3
"""
Example 08 — REST API Streaming Pipeline Execution (Priority 2 — E1)
======================================================================
Demonstrates the REST API as a real-time monitoring interface.

Submits a pipeline via POST /api/v1/pipelines/run and streams the NDJSON
execution log in real time, printing each event as it arrives with a live
progress bar.

Also demonstrates:
  - POST /api/v1/pipelines/validate  — validate before running
  - POST /api/v1/pipelines/run-async — fire-and-forget with run_id
  - GET  /api/v1/runs/{run_id}/status — poll async run status
  - GET  /api/v1/nodes               — discover nodes via REST
  - GET  /api/v1/system/health       — health check

The pipeline is built as IR JSON (canonical format) — no YAML.

Prerequisites:
  # Start the API server in a separate terminal:
  venv/bin/uvicorn app.api.main:app --reload --port 8001

Usage:
  venv/bin/python examples/08_rest_api_streaming/stream_client.py

  # Custom server URL
  venv/bin/python examples/08_rest_api_streaming/stream_client.py \\
      --url http://localhost:8001

  # With auth token
  GRAPHYN_API_TOKEN=secret \\
  venv/bin/python examples/08_rest_api_streaming/stream_client.py

  # Verbose — print every raw NDJSON line
  venv/bin/python examples/08_rest_api_streaming/stream_client.py --verbose

  # Also run async demo
  venv/bin/python examples/08_rest_api_streaming/stream_client.py --async-demo
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

# ── Path setup ────────────────────────────────────────────────────────────────
WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

# ── Colours ───────────────────────────────────────────────────────────────────
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_BLUE   = "\033[34m"
_DIM    = "\033[2m"
_MAGENTA = "\033[35m"


def _h(t: str) -> str: return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t: str) -> str: return f"{_GREEN}{t}{_RESET}"
def _warn(t: str) -> str: return f"{_YELLOW}{t}{_RESET}"
def _err(t: str) -> str: return f"{_RED}{t}{_RESET}"
def _dim(t: str) -> str: return f"{_DIM}{t}{_RESET}"
def _event_color(event_type: str) -> str:
    return {
        "pipeline_start":  _CYAN,
        "node_start":      _BLUE,
        "node_end":        _GREEN,
        "node_error":      _RED,
        "wave_start":      _MAGENTA,
        "wave_end":        _MAGENTA,
        "done":            _GREEN,
        "error":           _RED,
    }.get(event_type, _DIM)


# ── IR JSON builder ───────────────────────────────────────────────────────────

def build_pipeline_ir(data_path: str, output_path: str) -> dict:
    """Build a minimal preprocessing pipeline as IR JSON.

    Pipeline: dataset_ingest → audio_conditioner → segmenter →
              audio_quality_gate → dataset_builder → dataset_versioner

    This is the canonical format — no YAML, no SDK imports.
    The API detects IR JSON by the presence of 'schema_version'.
    """
    from app.core.ir.loader import CURRENT_IR_VERSION
    from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode
    from app.core.ir.loader import dump_ir

    nodes = [
        IRNode(id="dataset_ingest_0",    node_type="dataset_ingest",
               config={"path": data_path, "recursive": False, "source_type": "filesystem"}),
        IRNode(id="audio_conditioner_1", node_type="audio_conditioner",
               config={"target_sample_rate": 16000}),
        IRNode(id="segmenter_2",         node_type="segmenter",
               config={"silence_threshold_db": 40.0, "mode": "silence"}),
        IRNode(id="audio_quality_gate_3",node_type="audio_quality_gate",
               config={"min_snr_db": 5.0}),
        IRNode(id="feature_frontend_4",  node_type="feature_frontend",
               config={"feature_type": "mfcc", "n_mfcc": 40, "n_fft": 512,
                       "hop_length": 160, "fmax": 8000.0}),
        IRNode(id="dataset_builder_4",   node_type="dataset_builder",
               config={"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}, "fixed_length": 101}),
        IRNode(id="dataset_versioner_5", node_type="dataset_versioner",
               config={"output_dir": output_path,
                       "version_tag": "v1"}),
    ]
    edges = [
        IREdge(src_id="dataset_ingest_0",    src_port="output", dst_id="audio_conditioner_1", dst_port="input"),
        IREdge(src_id="audio_conditioner_1", src_port="output", dst_id="segmenter_2",         dst_port="input"),
        IREdge(src_id="segmenter_2",         src_port="output", dst_id="audio_quality_gate_3",dst_port="input"),
        IREdge(src_id="audio_quality_gate_3",src_port="output", dst_id="feature_frontend_4",   dst_port="input"),
        IREdge(src_id="feature_frontend_4",  src_port="output", dst_id="dataset_builder_4",   dst_port="input"),
        IREdge(src_id="dataset_builder_4",   src_port="output", dst_id="dataset_versioner_5", dst_port="input"),
    ]
    graph = GraphIR(
        schema_version=CURRENT_IR_VERSION,
        metadata=IRMetadata(name="streaming-demo", seed=42,
                            description="REST API streaming demo pipeline"),
        nodes=nodes,
        edges=edges,
    )
    return dump_ir(graph)


# ── Progress bar ──────────────────────────────────────────────────────────────

class ProgressBar:
    """Simple terminal progress bar for pipeline execution."""

    def __init__(self, total: int, width: int = 40) -> None:
        self.total = total
        self.width = width
        self.current = 0
        self.current_node = ""

    def update(self, completed: int, node_name: str = "") -> None:
        self.current = completed
        self.current_node = node_name
        self._render()

    def _render(self) -> None:
        pct = self.current / max(self.total, 1)
        filled = int(self.width * pct)
        bar = "█" * filled + "░" * (self.width - filled)
        label = f"{self.current_node[:20]:<20}" if self.current_node else " " * 20
        print(f"\r  [{bar}] {self.current}/{self.total}  {_dim(label)}", end="", flush=True)

    def finish(self) -> None:
        bar = "█" * self.width
        print(f"\r  [{_ok(bar)}] {self.total}/{self.total}  {'done':<20}", flush=True)


# ── Event handler ─────────────────────────────────────────────────────────────

class StreamEventHandler:
    """Processes NDJSON events from the streaming pipeline endpoint."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.progress: ProgressBar | None = None
        self.total_nodes = 0
        self.completed_nodes = 0
        self.node_timings: list[dict] = []
        self.errors: list[dict] = []
        self.run_id: str | None = None
        self.t_start = time.time()

    def handle(self, line: str) -> bool:
        """Process one NDJSON line. Returns False when stream is done."""
        line = line.strip()
        if not line:
            return True

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if self.verbose:
                print(f"  {_dim('[raw]')} {line}")
            return True

        event_type = event.get("type", "log")
        color = _event_color(event_type)
        ts = event.get("timestamp", event.get("time", ""))

        if self.verbose:
            print(f"\n  {_dim(ts)} {color}{event_type}{_RESET}")
            for k, v in event.items():
                if k not in ("type", "timestamp", "time"):
                    print(f"    {_dim(k + ':')} {v}")
            return True

        # ── Structured event handling ─────────────────────────────────────────
        if event_type == "pipeline_start":
            self.total_nodes = event.get("total_nodes", 0)
            self.progress = ProgressBar(self.total_nodes)
            print(f"  {_ok('▶')} Pipeline started — {self.total_nodes} nodes")
            self.progress.update(0)

        elif event_type == "node_start":
            node_type = event.get("node_type", "?")
            idx = event.get("node_index", 0)
            if self.progress:
                self.progress.update(idx, node_type)

        elif event_type == "node_end":
            node_type = event.get("node_type", "?")
            duration = event.get("duration_s", event.get("duration", 0))
            output_count = event.get("output_count", 0)
            idx = event.get("node_index", self.completed_nodes)
            self.completed_nodes += 1
            self.node_timings.append({
                "node_type": node_type,
                "duration_s": duration,
                "output_count": output_count,
            })
            if self.progress:
                self.progress.update(self.completed_nodes, node_type)

        elif event_type == "node_error":
            node_type = event.get("node_type", "?")
            msg = event.get("error_message", "")
            self.errors.append({"node_type": node_type, "message": msg})
            print(f"\n  {_err('✗')} {node_type}: {msg}")

        elif event_type in ("wave_start", "wave_end"):
            wave_idx = event.get("wave_index", "?")
            nodes = event.get("nodes", [])
            action = "starting" if event_type == "wave_start" else "done"
            print(f"\n  {_dim(f'Wave {wave_idx} {action}:')} {', '.join(nodes)}")

        elif event_type == "done":
            if self.progress:
                self.progress.finish()
            elapsed = time.time() - self.t_start
            print(f"  {_ok('✓')} Pipeline completed in {elapsed:.2f}s")
            return False  # stream finished

        elif event_type == "error":
            if self.progress:
                print()
            msg = event.get("message", "")
            print(f"  {_err('✗')} Pipeline error: {msg}")
            return False  # stream finished

        return True

    def print_summary(self) -> None:
        """Print per-node timing summary after stream completes."""
        if not self.node_timings:
            return
        print(f"\n  {_h('Node Timing Summary')}")
        total_time = sum(n["duration_s"] for n in self.node_timings)
        for node in self.node_timings:
            pct = node["duration_s"] / max(total_time, 0.001) * 100
            bar_len = int(pct / 5)
            bar = "▓" * bar_len + "░" * (20 - bar_len)
            print(f"    {node['node_type']:<25} [{bar}] "
                  f"{node['duration_s']:.3f}s ({pct:.0f}%)  "
                  f"{_dim(str(node['output_count']) + ' items')}")
        print(f"    {'Total':<25}  {_dim(' ' * 22)} {total_time:.3f}s")


# ── Demo functions ────────────────────────────────────────────────────────────

def demo_health_check(client: httpx.Client, base_url: str) -> bool:
    """Step 0: Health check."""
    print(f"\n{_h('Step 0 — Health Check')}")
    print(f"  {_dim('GET ' + base_url + '/api/v1/system/health')}")

    resp = client.get(f"{base_url}/api/v1/system/health")
    if resp.status_code != 200:
        print(_err(f"  ✗ Server not healthy: HTTP {resp.status_code}"))
        return False

    data = resp.json()
    print(f"  {_ok('✓')} Server healthy — status: {data.get('status')}, "
          f"timestamp: {_dim(data.get('timestamp', ''))}")
    return True


def demo_node_discovery(client: httpx.Client, base_url: str) -> None:
    """Step 1: Discover nodes via REST API."""
    print(f"\n{_h('Step 1 — Node Discovery via REST API')}")
    print(f"  {_dim('GET ' + base_url + '/api/v1/nodes')}")

    resp = client.get(f"{base_url}/api/v1/nodes")
    nodes = resp.json()
    print(f"  {_ok('✓')} {len(nodes)} node types registered")

    # Show by category
    categories: dict[str, int] = {}
    for node in nodes:
        cat = node.get("category", "Unknown")
        categories[cat] = categories.get(cat, 0) + 1
    for cat, count in sorted(categories.items()):
        print(f"    {_dim(cat + ':')} {count} nodes")

    # Show capability metadata for one node
    print(f"\n  {_dim('GET ' + base_url + '/api/v1/nodes/audio_conditioner')}")
    resp = client.get(f"{base_url}/api/v1/nodes/audio_conditioner")
    node = resp.json()
    cap = node.get("capability_metadata", {})
    print(f"  {_ok('✓')} audio_conditioner node capability metadata:")
    for field, value in cap.items():
        print(f"    {_dim(field + ':')} {value}")


def demo_validate(client: httpx.Client, base_url: str, graph: dict) -> bool:
    """Step 2: Validate the pipeline before running."""
    print(f"\n{_h('Step 2 — Validate Pipeline (IR JSON)')}")
    print(f"  {_dim('POST ' + base_url + '/api/v1/pipelines/validate')}")
    print(f"  {_dim('Body: IR JSON with schema_version=' + repr(graph.get('schema_version')))}")

    resp = client.post(f"{base_url}/api/v1/pipelines/validate", json=graph)
    data = resp.json()

    # Confirm no X-Deprecation-Warning header (IR JSON path)
    deprecation = resp.headers.get("X-Deprecation-Warning")
    if deprecation:
        print(_warn(f"  ⚠ Unexpected deprecation warning: {deprecation}"))
    else:
        print(f"  {_ok('✓')} No deprecation warning — IR JSON path confirmed")

    if not data.get("valid"):
        print(_err(f"  ✗ Validation failed: {data.get('error')}"))
        return False

    print(f"  {_ok('✓')} Valid — {data.get('node_count')} nodes")
    return True


def demo_streaming_run(
    client: httpx.Client,
    base_url: str,
    graph: dict,
    verbose: bool,
) -> bool:
    """Step 3: Run pipeline with NDJSON streaming."""
    print(f"\n{_h('Step 3 — Streaming Execution (NDJSON)')}")
    print(f"  {_dim('POST ' + base_url + '/api/v1/pipelines/run')}")
    print(f"  {_dim('Content-Type: application/x-ndjson (response)')}")
    print()

    handler = StreamEventHandler(verbose=verbose)
    t_request = time.time()

    with client.stream(
        "POST",
        f"{base_url}/api/v1/pipelines/run",
        json=graph,
        timeout=300.0,
    ) as response:
        if response.status_code != 200:
            print(_err(f"  ✗ HTTP {response.status_code}: {response.text}"))
            return False

        content_type = response.headers.get("content-type", "")
        print(f"  {_ok('✓')} Response Content-Type: {content_type}")
        print()

        for line in response.iter_lines():
            if not handler.handle(line):
                break

    t_total = time.time() - t_request
    print(f"\n  Total request time (including network): {t_total:.2f}s")

    handler.print_summary()

    if handler.errors:
        print(_warn(f"\n  ⚠ {len(handler.errors)} node error(s) during execution"))
        return False

    return True


def demo_async_run(
    client: httpx.Client,
    base_url: str,
    graph: dict,
) -> None:
    """Step 4 (optional): Fire-and-forget async run with status polling."""
    print(f"\n{_h('Step 4 — Async Run with Status Polling')}")
    print(f"  {_dim('POST ' + base_url + '/api/v1/pipelines/run-async')}")

    resp = client.post(f"{base_url}/api/v1/pipelines/run-async", json=graph)
    data = resp.json()
    run_id = data.get("run_id")
    print(f"  {_ok('✓')} Run started — run_id: {_BOLD}{run_id}{_RESET}")
    print(f"  {_dim('(run_id returned immediately — execution is async)')}")

    # Poll status
    print(f"\n  Polling {_dim('GET /api/v1/runs/' + run_id + '/status')} ...")
    max_polls = 60
    for i in range(max_polls):
        time.sleep(2)
        resp = client.get(f"{base_url}/api/v1/runs/{run_id}/status")
        status_data = resp.json()
        status = status_data.get("status", "unknown")
        progress = status_data.get("progress_pct", 0)
        current_node = status_data.get("current_node", "")

        bar_len = int(progress / 5)
        bar = "▓" * bar_len + "░" * (20 - bar_len)
        print(f"  [{bar}] {progress:.0f}%  {_BOLD}{status}{_RESET}  "
              f"{_dim(current_node)}", end="\r", flush=True)

        if status in ("completed", "failed", "cancelled"):
            print()
            if status == "completed":
                print(f"  {_ok('✓')} Async run completed")
            else:
                print(_err(f"  ✗ Async run {status}"))
            break
    else:
        print(f"\n  {_warn('⚠ Timed out waiting for async run')}")

    # Show run list
    print(f"\n  {_dim('GET /api/v1/runs — recent runs:')}")
    resp = client.get(f"{base_url}/api/v1/runs")
    runs = resp.json()
    for run in runs[:3]:
        rid = run.get("run_id", "?")[:8]
        status = run.get("status", "?")
        duration = run.get("duration_s")
        dur_str = f"{duration:.2f}s" if duration else "N/A"
        color = _ok if status == "completed" else _err if status == "failed" else _dim
        print(f"    {_dim(rid + '...')}  {color(status):<12}  {_dim(dur_str)}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Example 08 — REST API Streaming Pipeline Execution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8001",
        help="API server base URL (default: http://localhost:8001)",
    )
    parser.add_argument(
        "--data-path",
        default="examples/02_speech_commands/data/yes",
        help="Input audio directory",
    )
    parser.add_argument(
        "--output-path",
        default="examples/08_rest_api_streaming/output",
        help="Output directory",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every raw NDJSON event line",
    )
    parser.add_argument(
        "--async-demo",
        action="store_true",
        help="Also run the async run + status polling demo (Step 4)",
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    data_path = str(Path(args.data_path).resolve())
    output_path = str(Path(args.output_path).resolve())

    # Validate data path
    if not Path(data_path).exists():
        print(_err(f"Error: data path not found: {data_path}"))
        print("Run first: venv/bin/python examples/prepare_real_data.py")
        sys.exit(1)

    # Ensure output directory exists
    Path(output_path).mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"{_h('Example 08 — REST API Streaming Execution')}")
    print(f"{'='*60}")
    print(f"  API server: {base_url}")
    print(f"  Data path:  {data_path}")
    print(f"  Output:     {output_path}")

    # Build auth headers
    token = os.environ.get("GRAPHYN_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if token:
        print(f"  Auth:       Bearer token set")

    # Build the IR JSON pipeline
    graph = build_pipeline_ir(data_path, output_path)
    print(f"\n  Pipeline: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
    print(f"  Format:   IR JSON (schema_version={graph['schema_version']})")

    with httpx.Client(headers=headers, timeout=30.0) as client:
        # Step 0: Health check
        try:
            healthy = demo_health_check(client, base_url)
        except httpx.ConnectError:
            print(_warn(f"\n  ⚠ Server not reachable at {base_url} — skipping REST demo"))
            print(_warn("  Start with: venv/bin/uvicorn app.api.main:app --reload --port 8001"))
            sys.exit(0)
        if not healthy:
            print(_err("\nStart the API server first:"))
            print(_err("  venv/bin/uvicorn app.api.main:app --reload --port 8001"))
            sys.exit(1)

        # Step 1: Node discovery
        demo_node_discovery(client, base_url)

        # Step 2: Validate
        if not demo_validate(client, base_url, graph):
            sys.exit(1)

        # Step 3: Streaming run
        success = demo_streaming_run(client, base_url, graph, args.verbose)

        # Step 4: Async demo (optional)
        if args.async_demo:
            demo_async_run(client, base_url, graph)

    print(f"\n{'='*60}")
    print(f"{_h('Summary')}")
    print(f"{'='*60}")
    print(f"  Endpoints used:")
    print(f"    GET  /api/v1/system/health          — health check")
    print(f"    GET  /api/v1/nodes                  — node discovery")
    print(f"    GET  /api/v1/nodes/{{type}}            — node detail + capability")
    print(f"    POST /api/v1/pipelines/validate     — IR JSON validation")
    print(f"    POST /api/v1/pipelines/run           — NDJSON streaming execution")
    if args.async_demo:
        print(f"    POST /api/v1/pipelines/run-async    — async fire-and-forget")
        print(f"    GET  /api/v1/runs/{{run_id}}/status   — status polling")
        print(f"    GET  /api/v1/runs                   — run history")
    print(f"\n  Key points:")
    print(f"    • IR JSON detected by 'schema_version' field — no deprecation warning")
    print(f"    • NDJSON stream: one JSON event per line, Content-Type: application/x-ndjson")
    print(f"    • Events: pipeline_start, node_start, node_end, node_error, done/error")
    print(f"    • All timestamps: UTC ISO 8601 ending in +00:00")
    print(f"    • run-async returns run_id immediately — execution is non-blocking")
    print(f"{'='*60}\n")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
