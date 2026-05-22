# Example 07 — Agent-Generated Pipeline via MCP

Demonstrates the platform as an **AI-operable workflow operating system**.

A Python agent communicates with the MCP server and builds, validates, and executes a pipeline entirely through MCP tool calls — no hardcoded graph JSON, no SDK imports, no direct Python API calls. The agent discovers the node vocabulary at runtime and constructs the graph from scratch.

---

## What This Demonstrates

The full agent loop across 9 steps:

| Step | MCP Tool | What Happens |
|---|---|---|
| 1 DISCOVER | `list_nodes` | Query all available node types with capability metadata |
| 2 PLAN | *(rule-based planner)* | Select nodes for the task description |
| 3 BUILD | `generate_graph` | Construct a validated GraphIR from the node list |
| 4 CHECK | `get_graph_capability_summary` | Verify GPU/edge/determinism properties |
| 5 VALIDATE | `validate_graph` | Confirm structural validity before execution |
| 6 EXECUTE | `execute_pipeline` | Start async execution, get `run_id` within 500ms |
| 7 POLL | `inspect_run(status_only)` | Wait for completion by polling status |
| 8 INSPECT | `inspect_run(logs/graph)` | Retrieve execution log and stored graph snapshot |
| 9 REPORT | *(print summary)* | Show what was built and run |

---

## Architecture

```
agent.py
  │
  ├── MCPAgent (9-step loop)
  │     ├── list_nodes          → discover 31 node types
  │     ├── _plan_nodes()       → rule-based task planner
  │     ├── generate_graph      → build validated GraphIR
  │     ├── get_graph_capability_summary → check hardware requirements
  │     ├── validate_graph      → structural validation
  │     ├── execute_pipeline    → async execution (run_id in <500ms)
  │     ├── inspect_run (poll)  → wait for completion
  │     └── inspect_run (logs)  → retrieve results
  │
  └── MCP Client (mcp.client.stdio)
        └── stdio transport — JSON-RPC on stdin/stdout
              └── app/mcp/server.py subprocess (14 tools)
```

---

## How to Run

```bash
# Prepare data (if not already done)
venv/bin/python examples/prepare_real_data.py

# Run the agent — starts its own MCP server subprocess automatically
venv/bin/python examples/07_mcp_agent_pipeline/agent.py

# Different task descriptions
venv/bin/python examples/07_mcp_agent_pipeline/agent.py \
    --task "augment audio dataset"

venv/bin/python examples/07_mcp_agent_pipeline/agent.py \
    --task "extract features for ml training"

# Verbose — shows full MCP request/response JSON
venv/bin/python examples/07_mcp_agent_pipeline/agent.py --verbose

# Custom data and output paths
venv/bin/python examples/07_mcp_agent_pipeline/agent.py \
    --data-path examples/01_wake_word/data/wake_word \
    --output-path /tmp/agent_output
```

---

## Available Tasks

The rule-based planner recognises these task descriptions:

| Task | Pipeline |
|---|---|
| `"preprocess audio for keyword spotting"` | `dataset_ingest → audio_conditioner → segmenter → audio_quality_gate → audio_exporter` |
| `"augment audio dataset"` | `dataset_ingest → audio_conditioner → augmentation_pipeline → audio_exporter` |
| `"extract features for ml training"` | `dataset_ingest → audio_conditioner → segmenter → feature_frontend → dataset_builder → dataset_versioner` |
| *(any other)* | `dataset_ingest → audio_conditioner → audio_exporter` (fallback) |

---

## Expected Output

```
============================================================
MCP Agent — Agent-Generated Pipeline
============================================================
  Task:        preprocess audio for keyword spotting
  Data path:   .../examples/02_speech_commands/data/yes
  Output path: .../examples/07_mcp_agent_pipeline/output

Step 1 — DISCOVER
  ✓ Discovered 31 node types
    Augmentation: augmentation_pipeline, environment_simulator ...
    Export: dataset_versioner ...
    ...

Step 2 — PLAN
  ✓ Selected 6 nodes for pipeline:
    [0] dataset_ingest   path='...', recursive=False, source_type='filesystem'
    [1] audio_conditioner  target_sample_rate=16000
    [2] segmenter        silence_threshold_db=40.0, mode='silence'
    [3] audio_quality_gate  min_snr_db=-60.0, rejection_policy='skip'
    [4] audio_exporter   output_dir='...', split_ratios={train:0.70, val:0.15, test:0.15}, version_tag='v1'

Step 3 — BUILD
  ✓ Graph built: 5 nodes, 4 edges
    Schema version: 1.1
    dataset_ingest_0.output → audio_conditioner_1.input
    audio_conditioner_1.output → segmenter_2.input
    segmenter_2.output → audio_quality_gate_3.input
    audio_quality_gate_3.output → audio_exporter_4.input

Step 4 — CHECK
  ✓ Capability summary:
    requires_gpu:     False
    all_support_cpu:  True
    all_support_edge: False
    all_deterministic: True

Step 5 — VALIDATE
  ✓ Graph is valid — 5 nodes confirmed

Step 6 — EXECUTE
  ✓ Execution started — run_id: abc12345
    Dispatch time: 7ms (target: <500ms)

Step 7 — POLL
  ✓ Pipeline completed in 2.0s

Step 8 — INSPECT
  ✓ Run metadata: status=completed, duration=1.8s
  ✓ Execution log: 18 events
  ✓ Graph snapshot stored: 5 nodes, 4 edges

============================================================
Agent Summary
============================================================
  The agent built and ran this pipeline without any hardcoded
  graph JSON — it discovered the node vocabulary at runtime
  and constructed the graph entirely through MCP tool calls.
============================================================
```

---

## Key Concepts

### Why MCP?

The MCP (Model Context Protocol) server exposes the platform's full capability as structured tools that any AI agent can call. The agent needs only to:

1. Know the tool names and their JSON schemas
2. Parse JSON responses
3. Make sequential tool calls

This is exactly how an LLM-based agent (Claude, GPT-4, Gemini) would operate the platform.

### The Planner

In this example the planner is a rule-based decision tree. In production, replace it with an LLM call:

```python
response = llm.complete(f"""
Available nodes: {json.dumps(all_nodes)}
Task: {task}
Return a JSON array of {{"node_type": "...", "config": {{...}}}} objects.
""")
planned_nodes = json.loads(response)
```

The rest of the agent loop (build → check → validate → execute → poll → inspect) is identical regardless of whether the planner is rule-based or LLM-based.

### stdio Transport

The MCP server communicates via JSON-RPC on stdin/stdout. The agent starts the server as a subprocess and communicates through its stdio streams — no HTTP server, no ports, no network configuration.

### Capability Metadata

Step 4 (`get_graph_capability_summary`) shows how the platform's machine-readable capability fields enable hardware-aware scheduling:

- `any_requires_gpu` — does this graph need a GPU?
- `all_support_edge` — can this graph run on edge hardware?
- `all_deterministic` — will this graph produce identical output on replay?

---

## Extending This Example

### Replace the planner with an LLM

```python
import anthropic

def llm_plan_nodes(task, all_nodes, data_path, output_path):
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": f"""
You are a pipeline planning agent. Available nodes:
{json.dumps([{"node_type": n["node_type"], "description": n["description"]} for n in all_nodes])}

Task: {task}
Input: {data_path}
Output: {output_path}

Return a JSON array of node specifications.
"""}]
    )
    return json.loads(response.content[0].text)
```

### Add runtime control

```python
# Start execution, pause after 5 seconds, then resume
exec_result = await self._call("execute_pipeline", {"graph": graph})
run_id = exec_result["run_id"]
await asyncio.sleep(5)
await self._call("pause_run", {"run_id": run_id})
# ... inspect intermediate state ...
await self._call("resume_run", {"run_id": run_id})
```
