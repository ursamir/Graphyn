---
inclusion: fileMatch
fileMatchPattern: "app/core/sdk.py,app/cli/**"
---

# SDK and CLI

Both delegate to `get_backend().execute()` via `GraphIR` — no separate execution logic. The SDK calls `get_backend().execute()` internally; the CLI calls `get_backend().execute()` for seed-override paths and `pipeline.run()` for standard paths.

## Python SDK (`app/core/sdk.py`)

```python
from app.core.sdk import PipelineNode, Pipeline

# PipelineNode — validates config at construction time.
# Note: _ir_node is NOT set in __init__ (ARCH-5 fix). Use to_ir_node(index)
# to get the correctly-indexed IRNode. to_dict() uses self.node_type/config directly.
node = PipelineNode("audio_conditioner", {"sample_rate": 16000})

# Linear pipeline — output → input auto-chained
pipeline = Pipeline([
    PipelineNode("dataset_ingest", {"path": "workspace/datasets/input/speech"}),
    PipelineNode("audio_conditioner", {"sample_rate": 16000}),
    PipelineNode("segmenter", {"window_ms": 1000}),
    PipelineNode("deployment_packager", {"project": "my-project", "version": "v1"}),
], seed=42, name="my-pipeline")
pipeline.run()

# Multi-input pipeline — explicit edges required
# edges: list of (src_node_index, src_port, dst_node_index, dst_port)
pipeline = Pipeline(
    nodes=[
        PipelineNode("dataset_builder", {...}),   # index 0
        PipelineNode("trainer", {...}),            # index 1
    ],
    edges=[(0, "output", 1, "dataset")],
    seed=42,
)

# Runtime modes
pipeline.run(parallel=True)                          # parallel wave execution
pipeline.run(resume_run_id="abc12345")               # resume from checkpoint
pipeline.run(include_nodes=["audio_conditioner_0"])  # partial execution — include
pipeline.run(exclude_nodes=["augmentation_pipeline_0"])  # partial execution — exclude
pipeline.run(input_overrides={"node_id": {"port": data}})  # inject inputs (all active nodes)
pipeline.run(event_driven=True)                      # event-driven mode

# Event subscription
def on_event(event: dict) -> None:
    if event["type"] == "node_end":
        print(f"{event['node_type']} done in {event['duration_s']:.2f}s")

unsubscribe = pipeline.subscribe(on_event)
pipeline.run()
unsubscribe()

# Runtime control
outputs, run = pipeline.run_with_manager()
run.pause()    # pause after current node
run.cancel()   # cancel after current node

# Validation
errors = pipeline.validate()  # → list[str]; empty = valid
# Uses IR-native validation: load_ir() structural check + PipelineGraph topology check.
# Does NOT round-trip through the deprecated YAML-format dict.

# Serialization
pipeline.to_json("pipeline.graph.json")
pipeline.to_ir()                              # → GraphIR object
loaded = Pipeline.from_json("pipeline.graph.json")

# Plugin install via SDK
pipeline.install_plugin("PluginPackage/Audio/my_plugin/")
pipeline.install_plugin("git+https://github.com/org/plugin.git")
```

**`run()` full signature:**
```python
pipeline.run(logger=None, use_cache=True, checkpoint=False, streaming=False,
    parallel=False, max_workers=None, resume_run_id=None,
    include_nodes=None, exclude_nodes=None, input_overrides=None,
    event_driven=False, observer=None, run_manager=None) -> ArtifactCollection
```

**`ArtifactCollection` return type** — dict-compatible but not a dict subclass:
```python
result = pipeline.run()
result["node_id"]                    # dict-style access
result.artifacts                     # list[ArtifactRecord]
result.run_id                        # run ID string
result.get_by_type("audio_samples")  # list[ArtifactRecord] filtered by type
result.lineage("artifact_id")        # provenance tree dict
```

## CLI (`app/cli/main.py`)

```bash
# Execute
graphyn run --graph PATH [--seed N] [--parallel] [--resume RUN_ID]
            [--include-nodes ID,...] [--exclude-nodes ID,...] [--event-driven]

# Inspect & validate
graphyn inspect --graph PATH
graphyn validate --graph PATH

# Registry
graphyn nodes [--category CATEGORY] [--capability KEY=VALUE ...]

# Manage runs
graphyn migrate --config PATH [--output PATH]   # YAML → IR JSON
graphyn runs list
graphyn runs logs RUN_ID
graphyn runs pause RUN_ID
graphyn runs resume RUN_ID
graphyn runs cancel RUN_ID

# Artifacts
graphyn artifacts list [--run RUN_ID] [--type ARTIFACT_TYPE]
graphyn artifacts get ARTIFACT_ID
graphyn artifacts lineage ARTIFACT_ID
graphyn artifacts replay RUN_ID

# Plugins
graphyn plugin install SOURCE [--upgrade]
graphyn plugin list [--enabled]
graphyn plugin enable NAME
graphyn plugin disable NAME
graphyn plugin remove NAME
graphyn plugin search QUERY
graphyn plugin info NAME

# MCP server
graphyn mcp
GRAPHYN_API_TOKEN=secret graphyn mcp
```

**`graphyn run` flags:**

| Flag | Default | Description |
|---|---|---|
| `--parallel` | False | Parallel wave execution |
| `--resume RUN_ID` | None | Resume from prior run checkpoint |
| `--include-nodes ID,...` | None | Partial execution — run only these nodes |
| `--exclude-nodes ID,...` | None | Partial execution — skip these nodes |
| `--event-driven` | False | Event-driven mode (runs until cancelled) |

`pause`, `resume`, `cancel` via `graphyn runs` only work on in-process runs (same process). Exit codes: `0` = success, `1` = failure.
