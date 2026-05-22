#!/usr/bin/env python3
"""
Example 07 — Agent-Generated Pipeline via MCP (Priority 1 — D1)
================================================================
Demonstrates the platform as an AI-operable workflow operating system.

A Python agent communicates with the MCP server using the full tool loop:

  Step 1  DISCOVER  — list_nodes          → find all available node types
  Step 2  PLAN      — (rule-based planner) → select nodes for the task
  Step 3  BUILD     — generate_graph       → construct a validated GraphIR
  Step 4  CHECK     — get_graph_capability_summary → verify graph properties
  Step 5  VALIDATE  — validate_graph       → confirm the graph is valid
  Step 6  EXECUTE   — execute_pipeline     → run asynchronously, get run_id
  Step 7  POLL      — inspect_run          → wait for completion
  Step 8  INSPECT   — inspect_run(logs)    → retrieve execution log
  Step 9  REPORT    — print summary        → show what was built and run

The agent uses NO hardcoded graph JSON. It discovers the node vocabulary at
runtime and constructs the graph entirely through MCP tool calls — exactly
as an LLM-based agent would.

The task: "preprocess audio for keyword spotting"
  → dataset_ingest → audio_conditioner → segmenter → audio_quality_gate →
    dataset_builder → dataset_versioner

Usage:
  # Terminal 1: start the MCP server
  venv/bin/python -m app.mcp.server

  # Terminal 2: run the agent (connects to the server via subprocess)
  venv/bin/python examples/07_mcp_agent_pipeline/agent.py

  # Or run everything in one command (agent starts its own server subprocess):
  venv/bin/python examples/07_mcp_agent_pipeline/agent.py --self-contained

Options:
  --self-contained   Start the MCP server as a subprocess (default mode)
  --task TASK        Task description (default: "preprocess audio for keyword spotting")
  --data-path PATH   Input audio directory (default: examples/02_speech_commands/data/yes)
  --output-path PATH Output directory (default: examples/07_mcp_agent_pipeline/output)
  --verbose          Print full tool request/response JSON
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── Path setup ────────────────────────────────────────────────────────────────
WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

# ── Install required plugins ──────────────────────────────────────────────────
from app.core.plugins.manager import PluginManager  # noqa: E402

_manager = PluginManager()
_manager.install("PluginPackage/Audio/dataset_ingest/")
_manager.install("PluginPackage/Audio/audio_conditioner/")
_manager.install("PluginPackage/Audio/segmenter/")
_manager.install("PluginPackage/Audio/audio_quality_gate/")
_manager.install("PluginPackage/Audio/augmentation_pipeline/")
_manager.install("PluginPackage/Audio/audio_exporter/")
_manager.install("PluginPackage/Audio/feature_frontend/", upgrade=True)
_manager.install("PluginPackage/Common/dataset_builder/")
_manager.install("PluginPackage/Common/dataset_versioner/")
_manager.load_enabled_plugins()

# ── Colours for terminal output ───────────────────────────────────────────────
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_DIM    = "\033[2m"


def _h(text: str) -> str:
    """Header — bold cyan."""
    return f"{_BOLD}{_CYAN}{text}{_RESET}"


def _ok(text: str) -> str:
    """Success — green."""
    return f"{_GREEN}{text}{_RESET}"


def _warn(text: str) -> str:
    """Warning — yellow."""
    return f"{_YELLOW}{text}{_RESET}"


def _err(text: str) -> str:
    """Error — red."""
    return f"{_RED}{text}{_RESET}"


def _dim(text: str) -> str:
    """Dim — for secondary info."""
    return f"{_DIM}{text}{_RESET}"


# ── Rule-based planner ────────────────────────────────────────────────────────

# Maps task keywords → ordered list of node types to use.
# In a real agent this would be an LLM call; here it's a deterministic
# decision tree to keep the example self-contained and reproducible.
_TASK_PLANS: dict[str, list[dict]] = {
    "preprocess audio for keyword spotting": [
        {"node_type": "dataset_ingest",    "config": {"source_type": "filesystem"}},  # path injected later
        {"node_type": "audio_conditioner", "config": {"target_sample_rate": 16000}},
        {"node_type": "segmenter",         "config": {"silence_threshold_db": 40.0, "mode": "silence"}},
        {"node_type": "audio_quality_gate","config": {"min_snr_db": 5.0, "rejection_policy": "skip"}},
        {"node_type": "audio_exporter",    "config": {"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}, "random_seed": 42}},  # output injected later
    ],
    "augment audio dataset": [
        {"node_type": "dataset_ingest",       "config": {"source_type": "filesystem"}},
        {"node_type": "audio_conditioner",    "config": {"target_sample_rate": 16000}},
        {"node_type": "augmentation_pipeline","config": {
            "copies_per_sample": 2,
            "augmentations": [
                {"type": "gain", "apply_prob": 1.0, "gain_db": [-6.0, 6.0]},
                {"type": "pitch_shift", "apply_prob": 1.0, "semitones": [-2.0, 2.0]},
            ],
        }},
        {"node_type": "audio_exporter",       "config": {"split_ratios": {"train": 0.80, "val": 0.10, "test": 0.10}, "random_seed": 42}},  # output injected later
    ],
    "extract features for ml training": [
        {"node_type": "dataset_ingest",    "config": {"source_type": "filesystem"}},
        {"node_type": "audio_conditioner", "config": {"target_sample_rate": 16000}},
        {"node_type": "segmenter",         "config": {"silence_threshold_db": 40.0, "mode": "silence"}},
        {"node_type": "feature_frontend",  "config": {"feature_type": "mfcc", "n_mfcc": 40, "n_fft": 512, "hop_length": 160, "fmax": 8000.0, "fixed_length": 101, "normalize": True}},
        {"node_type": "dataset_builder",   "config": {"fixed_length": 101}},
        {"node_type": "dataset_versioner", "config": {}},  # output injected later
    ],
}


def _plan_nodes(task: str, data_path: str, output_path: str) -> list[dict]:
    """Select and configure nodes for the given task description.

    Matches the task string against known patterns (case-insensitive).
    Injects data_path into file_input and output_path into file_export.
    Falls back to a minimal clean → split pipeline for unknown tasks.
    """
    task_lower = task.lower().strip()

    # Find the best matching plan
    plan = None
    for key, nodes in _TASK_PLANS.items():
        if key in task_lower or any(word in task_lower for word in key.split()):
            plan = [dict(n) for n in nodes]  # deep copy
            break

    if plan is None:
        # Fallback: minimal pipeline
        plan = [
            {"node_type": "dataset_ingest",    "config": {"source_type": "filesystem"}},
            {"node_type": "audio_conditioner", "config": {"target_sample_rate": 16000}},
            {"node_type": "audio_exporter",    "config": {"split_ratios": {"train": 0.80, "val": 0.10, "test": 0.10}, "random_seed": 42}},  # output injected later
        ]

    # Inject runtime paths
    for node in plan:
        if node["node_type"] == "dataset_ingest":
            node["config"]["path"] = data_path
            node["config"]["recursive"] = False
        elif node["node_type"] == "dataset_versioner":
            node["config"]["output_dir"] = output_path
            node["config"]["version_tag"] = "v1"
        elif node["node_type"] == "audio_exporter":
            node["config"]["output_dir"] = output_path
            node["config"]["version_tag"] = "v1"
            node["config"]["append"] = False

    return plan


# ── MCP Agent ─────────────────────────────────────────────────────────────────

class MCPAgent:
    """A simple rule-based agent that operates the platform via MCP tools.

    Demonstrates the full agent loop:
      discover → plan → build → check → validate → execute → poll → inspect
    """

    def __init__(self, session, verbose: bool = False) -> None:
        self._session = session
        self._verbose = verbose
        self._step = 0

    def _print_step(self, number: int, name: str, description: str) -> None:
        print(f"\n{_h(f'Step {number} — {name}')}")
        print(f"  {_dim(description)}")

    def _print_tool(self, tool: str, args: dict) -> None:
        print(f"  {_dim('→ MCP tool:')} {_BOLD}{tool}{_RESET}")
        if self._verbose:
            print(f"  {_dim('  request:')} {json.dumps(args, indent=4)}")

    def _print_result(self, result: Any) -> None:
        if self._verbose:
            print(f"  {_dim('  response:')} {json.dumps(result, indent=4)}")

    async def _call(self, tool: str, args: dict) -> Any:
        """Call an MCP tool and return the parsed JSON result."""
        self._print_tool(tool, args)
        response = await self._session.call_tool(tool, args)
        # MCP returns list[TextContent]; first item is the JSON string
        raw = response.content[0].text if response.content else "{}"
        result = json.loads(raw)
        self._print_result(result)
        return result

    async def run(self, task: str, data_path: str, output_path: str) -> bool:
        """Execute the full agent loop. Returns True on success."""

        print(f"\n{'='*60}")
        print(f"{_h('MCP Agent — Agent-Generated Pipeline')}")
        print(f"{'='*60}")
        print(f"  Task:        {_BOLD}{task}{_RESET}")
        print(f"  Data path:   {data_path}")
        print(f"  Output path: {output_path}")

        # ── Step 1: DISCOVER ──────────────────────────────────────────────────
        self._print_step(1, "DISCOVER", "Query the MCP server for all available node types")

        result = await self._call("list_nodes", {})
        if "error" in result:
            print(_err(f"  ✗ list_nodes failed: {result.get('message')}"))
            return False

        all_nodes = result.get("nodes", [])
        print(f"  {_ok('✓')} Discovered {_BOLD}{len(all_nodes)}{_RESET} node types")

        # Print a summary by category
        categories: dict[str, list[str]] = {}
        for node in all_nodes:
            cat = node.get("category", "Unknown")
            categories.setdefault(cat, []).append(node["node_type"])
        for cat, types_list in sorted(categories.items()):
            print(f"    {_dim(cat + ':')} {', '.join(sorted(types_list))}")

        # ── Step 2: PLAN ──────────────────────────────────────────────────────
        self._print_step(2, "PLAN", f"Select nodes for task: \"{task}\"")

        planned_nodes = _plan_nodes(task, data_path, output_path)

        # Verify all planned nodes exist in the registry
        available_types = {n["node_type"] for n in all_nodes}
        missing = [n["node_type"] for n in planned_nodes if n["node_type"] not in available_types]
        if missing:
            print(_err(f"  ✗ Planned nodes not in registry: {missing}"))
            return False

        print(f"  {_ok('✓')} Selected {len(planned_nodes)} nodes for pipeline:")
        for i, node in enumerate(planned_nodes):
            cfg_summary = ", ".join(f"{k}={v!r}" for k, v in node["config"].items() if k != "path")
            print(f"    [{i}] {_BOLD}{node['node_type']}{_RESET}  {_dim(cfg_summary)}")

        # ── Step 3: BUILD ─────────────────────────────────────────────────────
        self._print_step(3, "BUILD", "Call generate_graph to construct a validated GraphIR")

        result = await self._call("generate_graph", {
            "nodes": planned_nodes,
            "seed": 42,
            "name": "agent-generated-pipeline",
            "description": f"Auto-generated for task: {task}",
        })

        if result.get("error"):
            print(_err(f"  ✗ generate_graph failed: {result.get('message')}"))
            return False

        graph = result
        node_count = len(graph.get("nodes", []))
        edge_count = len(graph.get("edges", []))
        print(f"  {_ok('✓')} Graph built: {_BOLD}{node_count} nodes{_RESET}, {edge_count} edges")
        print(f"    Schema version: {graph.get('schema_version')}")
        print(f"    Seed: {graph.get('metadata', {}).get('seed')}")

        # Print the edge chain
        for edge in graph.get("edges", []):
            print(f"    {_dim(edge['src_id'] + '.' + edge['src_port'])} → "
                  f"{_dim(edge['dst_id'] + '.' + edge['dst_port'])}")

        # ── Step 4: CHECK ─────────────────────────────────────────────────────
        self._print_step(4, "CHECK", "Inspect capability summary — is this graph edge-compatible?")

        result = await self._call("get_graph_capability_summary", {"graph": graph})

        if result.get("error"):
            print(_warn(f"  ⚠ capability summary failed: {result.get('message')}"))
        else:
            print(f"  {_ok('✓')} Capability summary:")
            print(f"    requires_gpu:    {result.get('any_requires_gpu', False)}")
            print(f"    all_support_cpu: {result.get('all_support_cpu', True)}")
            print(f"    all_support_edge:{result.get('all_support_edge', False)}")
            print(f"    all_deterministic:{result.get('all_deterministic', True)}")
            print(f"    any_batch_support:{result.get('any_batch_support', False)}")

            if result.get("any_requires_gpu"):
                print(_warn("  ⚠ Graph requires GPU — ensure GPU is available"))
            if not result.get("all_support_cpu", True):
                print(_warn("  ⚠ Some nodes do not support CPU execution"))

        # ── Step 5: VALIDATE ──────────────────────────────────────────────────
        self._print_step(5, "VALIDATE", "Call validate_graph to confirm the graph is structurally valid")

        result = await self._call("validate_graph", {"graph": graph})

        if not result.get("valid"):
            errors = result.get("errors", [])
            print(_err(f"  ✗ Graph validation failed:"))
            for e in errors:
                print(_err(f"    - {e}"))
            return False

        print(f"  {_ok('✓')} Graph is valid — {result.get('node_count')} nodes confirmed")

        # ── Step 6: EXECUTE ───────────────────────────────────────────────────
        self._print_step(6, "EXECUTE", "Call execute_pipeline — returns run_id within 500ms")

        t_start = time.time()
        result = await self._call("execute_pipeline", {
            "graph": graph,
            "use_cache": True,
        })
        t_dispatch = time.time() - t_start

        if result.get("error"):
            print(_err(f"  ✗ execute_pipeline failed: {result.get('message')}"))
            return False

        run_id = result.get("run_id")
        print(f"  {_ok('✓')} Execution started — run_id: {_BOLD}{run_id}{_RESET}")
        print(f"    Dispatch time: {t_dispatch*1000:.0f}ms (target: <500ms)")

        # ── Step 7: POLL ──────────────────────────────────────────────────────
        self._print_step(7, "POLL", "Poll inspect_run until pipeline completes")

        max_wait_s = 300
        poll_interval_s = 2.0
        t_poll_start = time.time()
        final_status = "unknown"

        print(f"  Polling every {poll_interval_s:.0f}s (max {max_wait_s}s)...")
        while time.time() - t_poll_start < max_wait_s:
            await asyncio.sleep(poll_interval_s)

            result = await self._call("inspect_run", {
                "run_id": run_id,
                "status_only": True,
            })
            status = result.get("status", "unknown")
            elapsed = time.time() - t_poll_start
            print(f"  {_dim(f'  [{elapsed:.0f}s]')} status: {_BOLD}{status}{_RESET}")

            if status in ("completed", "failed", "cancelled"):
                final_status = status
                break

        if final_status == "completed":
            print(f"  {_ok('✓')} Pipeline completed in {time.time() - t_poll_start:.1f}s")
        elif final_status == "failed":
            print(_err(f"  ✗ Pipeline failed"))
        else:
            print(_warn(f"  ⚠ Pipeline status: {final_status}"))

        # ── Step 8: INSPECT ───────────────────────────────────────────────────
        self._print_step(8, "INSPECT", "Retrieve full run metadata and execution log")

        # Get full meta.json
        result = await self._call("inspect_run", {"run_id": run_id})
        if not result.get("error"):
            print(f"  {_ok('✓')} Run metadata:")
            print(f"    status:     {result.get('status')}")
            print(f"    duration_s: {result.get('duration_s', 'N/A')}")
            node_stats = result.get("node_stats", [])
            if node_stats:
                print(f"    nodes executed: {len(node_stats)}")
                for stat in node_stats:
                    node_id = stat.get("node_id", "?")
                    duration = stat.get("duration_s", 0)
                    output_count = stat.get("output_count", 0)
                    print(f"      {_dim(node_id)}: {duration:.3f}s → {output_count} items")

        # Get execution log
        result = await self._call("inspect_run", {"run_id": run_id, "logs": True})
        if not result.get("error"):
            logs = result.get("logs", [])
            node_events = [e for e in logs if e.get("type") in ("node_start", "node_end", "node_error")]
            print(f"  {_ok('✓')} Execution log: {len(logs)} events ({len(node_events)} node events)")
            # Print node_end events as a summary
            for event in logs:
                if event.get("type") == "node_end":
                    node_type = event.get("node_type", "?")
                    duration = event.get("duration_s", 0)
                    output_count = event.get("output_count", 0)
                    print(f"    {_ok('✓')} {_BOLD}{node_type}{_RESET} "
                          f"— {duration:.3f}s → {output_count} items")
                elif event.get("type") == "node_error":
                    node_type = event.get("node_type", "?")
                    msg = event.get("error_message", "")
                    print(f"    {_err('✗')} {_BOLD}{node_type}{_RESET} — {msg}")

        # Get stored graph snapshot
        result = await self._call("inspect_run", {"run_id": run_id, "graph": True})
        if not result.get("error"):
            stored_graph = result.get("graph", {})
            print(f"  {_ok('✓')} Graph snapshot stored: "
                  f"{len(stored_graph.get('nodes', []))} nodes, "
                  f"{len(stored_graph.get('edges', []))} edges")

        # ── Step 9: REPORT ────────────────────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"{_h('Agent Summary')}")
        print(f"{'='*60}")
        print(f"  Task:        {task}")
        print(f"  Run ID:      {run_id}")
        print(f"  Status:      {_ok(final_status) if final_status == 'completed' else _err(final_status)}")
        print(f"  Pipeline:    {node_count} nodes, {edge_count} edges")
        print(f"  Output:      {output_path}/agent_output/v1/")
        print(f"\n  MCP tools used:")
        print(f"    list_nodes, generate_graph, get_graph_capability_summary,")
        print(f"    validate_graph, execute_pipeline, inspect_run (×3)")
        print(f"\n  The agent built and ran this pipeline without any hardcoded")
        print(f"  graph JSON — it discovered the node vocabulary at runtime")
        print(f"  and constructed the graph entirely through MCP tool calls.")
        print(f"{'='*60}\n")

        return final_status == "completed"


# ── Entry point ───────────────────────────────────────────────────────────────

async def main_async(args: argparse.Namespace) -> int:
    """Start the MCP server as a subprocess and run the agent against it."""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    data_path = str(Path(args.data_path).resolve())
    output_path = str(Path(args.output_path).resolve())

    # Ensure output directory exists
    Path(output_path).mkdir(parents=True, exist_ok=True)

    # Build server parameters — launch the MCP server as a subprocess
    server_params = StdioServerParameters(
        command=str(Path(WORKSPACE_ROOT) / "venv" / "bin" / "python"),
        args=["-m", "app.mcp.server"],
        cwd=WORKSPACE_ROOT,
        env={**os.environ},
    )

    print(f"\n{_dim('Starting MCP server subprocess...')}")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the MCP session
            await session.initialize()

            # Verify tools are available
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            print(f"{_ok('✓')} MCP server ready — {len(tool_names)} tools available")
            if args.verbose:
                print(f"  Tools: {', '.join(sorted(tool_names))}")

            # Run the agent
            agent = MCPAgent(session, verbose=args.verbose)
            success = await agent.run(
                task=args.task,
                data_path=data_path,
                output_path=output_path,
            )

    return 0 if success else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Example 07 — Agent-Generated Pipeline via MCP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--task",
        default="preprocess audio for keyword spotting",
        help="Task description for the agent (default: 'preprocess audio for keyword spotting')",
    )
    parser.add_argument(
        "--data-path",
        default="examples/02_speech_commands/data/yes",
        help="Input audio directory (default: examples/02_speech_commands/data/yes)",
    )
    parser.add_argument(
        "--output-path",
        default="examples/07_mcp_agent_pipeline/output",
        help="Output directory (default: examples/07_mcp_agent_pipeline/output)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full MCP tool request/response JSON",
    )
    args = parser.parse_args()

    # Validate data path
    if not Path(args.data_path).exists():
        print(_err(f"Error: data path not found: {args.data_path}"))
        print("Run first: venv/bin/python examples/prepare_real_data.py")
        sys.exit(1)

    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
