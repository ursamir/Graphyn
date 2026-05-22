# Python SDK and CLI

Graphyn provides a Python SDK and a CLI for running pipelines without the web UI.

---

## Python SDK

**File:** `app/core/sdk.py`

```python
from app.core.sdk import PipelineNode, Pipeline
```

### `PipelineNode`

Represents a single pipeline node with a type and configuration. Validates config against the node's Pydantic `Config` model on instantiation.

```python
class PipelineNode:
    def __init__(self, node_type: str, config: dict | None = None): ...
    def to_dict(self) -> dict: ...
```

**Validation on construction:** `PipelineNode` calls `registry.get_class(node_type).Config.model_validate(config)` immediately. If the node type is unknown or the config is invalid, a `ValueError` is raised with a descriptive message.

```python
# Valid
node = PipelineNode("audio_conditioner", {"sample_rate": 16000})

# Raises ValueError: Unknown node type 'foo'. Available types: audio_conditioner, segmenter, ...
node = PipelineNode("foo", {})

# Raises ValueError: Invalid config for node 'audio_conditioner': ...
node = PipelineNode("audio_conditioner", {"sample_rate": "not-a-number"})
```

---

### `Pipeline`

Represents a complete pipeline of nodes. Can be run directly, loaded from IR JSON or YAML, or serialized.

```python
class Pipeline:
    def __init__(self, nodes: list[PipelineNode], seed: int = 42,
                 name: str = "pipeline", description: str = ""): ...
    def run(self, logger=None, **kwargs) -> dict: ...
    def to_ir(self) -> GraphIR: ...
    def to_json(self, path: str) -> None: ...
    def to_yaml(self, path: str) -> None: ...
    def install_plugin(self, source: str, upgrade: bool = False) -> PluginRecord: ...

    @classmethod
    def from_json(cls, path: str) -> "Pipeline": ...   # canonical
    @classmethod
    def from_yaml(cls, path: str) -> "Pipeline": ...   # deprecated
```

#### `Pipeline.run()`

Converts the pipeline to a `GraphIR` and calls `run_pipeline_ir()`. Returns the outputs dict of the final node.

```python
result = pipeline.run()
```

#### `Pipeline.to_ir()`

Returns the backing `GraphIR` object without executing.

#### `Pipeline.to_json(path)` / `Pipeline.from_json(path)`

Canonical IR JSON serialization. Preferred over YAML.

```python
pipeline.to_json("my-pipeline.graph.json")
loaded = Pipeline.from_json("my-pipeline.graph.json")
```

#### `Pipeline.to_yaml(path)` / `Pipeline.from_yaml(path)`

YAML serialization (deprecated — emits `DeprecationWarning`). Use IR JSON instead.

---

#### `Pipeline.install_plugin(source, upgrade=False)`

Install a plugin and make its node types immediately available in the registry. Delegates to `PluginManager.install()`. All exceptions from `PluginManager` propagate unchanged.

```python
from app.core.sdk import Pipeline

pipeline = Pipeline([...])

# Install by name
record = pipeline.install_plugin("audio-denoiser")
print(f"Installed {record.name} {record.version}")

# Upgrade an existing installation
record = pipeline.install_plugin("audio-denoiser", upgrade=True)

# Install from a local path
record = pipeline.install_plugin("/path/to/my-plugin/")

# Install from a Git URL
record = pipeline.install_plugin("git+https://github.com/org/my-plugin.git")
```

Returns a `PluginRecord` for the newly installed plugin. Raises `PluginAlreadyInstalledError` if the plugin is already installed and `upgrade=False`.

---

### Full Example

```python
from app.core.sdk import PipelineNode, Pipeline

# Build a pipeline
pipeline = Pipeline([
    PipelineNode("dataset_ingest", {
        "path": "workspace/datasets/input/speech"
    }),
    PipelineNode("audio_conditioner", {
        "sample_rate": 16000
    }),
    PipelineNode("segmenter", {
        "mode": "vad",
    }),
    PipelineNode("augmentation_pipeline", {
        "augmentations": [{"type": "gain", "apply_prob": 0.5, "gain_db": [-3.0, 3.0]}],
        "copies_per_sample": 2
    }),
    PipelineNode("feature_frontend", {
        "feature_type": "mfcc"
    }),
    PipelineNode("dataset_builder", {
        "split_ratios": {"train": 0.8, "val": 0.1, "test": 0.1}
    }),
], seed=42, name="my-pipeline", description="Audio preprocessing pipeline")

# Run it
result = pipeline.run()

# Save to IR JSON (canonical)
pipeline.to_json("my-pipeline.graph.json")

# Load from IR JSON
pipeline2 = Pipeline.from_json("my-pipeline.graph.json")

# Save to YAML (deprecated)
pipeline.to_yaml("my-pipeline.yaml")
```

### YAML format produced by `Pipeline.to_yaml()`

```yaml
pipeline:
  seed: 42
  nodes:
  - type: dataset_ingest
    config:
      path: workspace/datasets/input/speech
  - type: audio_conditioner
    config:
      sample_rate: 16000
  - type: segmenter
    config:
      mode: vad
  - type: feature_frontend
    config:
      feature_type: mfcc
  - type: dataset_builder
    config:
      split_ratios: {train: 0.8, val: 0.1, test: 0.1}
```

The SDK always produces the linear format (no `edges` key). To use the DAG format, write the YAML manually and use `Pipeline.from_yaml()` or call `run_pipeline()` directly.

---

## CLI

**File:** `app/cli/main.py`  
**Entry point:** `venv/bin/python -m app.cli.main` or `graphyn` (if installed via `setup.py`)

```
usage: graphyn COMMAND

Commands:
  run       Execute a pipeline synchronously
  validate  Validate a pipeline YAML or IR JSON file
  migrate   Convert a YAML pipeline config to IR JSON
  runs      Manage pipeline run history
  mcp       Start the MCP server (stdio transport)
```

---

### `graphyn run`

Execute a pipeline synchronously, printing structured logs to stdout.

```
usage: graphyn run --graph PATH [--seed N]
       graphyn run --config PATH [--seed N]   (deprecated)

options:
  --graph PATH    Path to the IR JSON graph file (canonical)
  --config PATH   Path to the pipeline YAML config file (deprecated)
  --seed N        Override the pipeline seed (integer, optional)
```

**Example:**

```bash
graphyn run --graph my-pipeline.graph.json
graphyn run --config workspace/configs/templates/basic-wakeword.yaml  # deprecated — use .graph.json
graphyn run --graph my-pipeline.graph.json --seed 123
```

**Output:**

```
Pipeline starting (5 nodes)…
[1/5] InputNode starting…
  ✓ InputNode done in 0.12s → 42 samples
[2/5] CleanNode starting…
  ✓ CleanNode done in 0.34s → 42 samples
...
Pipeline complete in 1.23s — 42 samples produced.
```

Exits with code `0` on success, `1` on failure.

If `--seed` is provided, the config is patched in-memory (a temp file is written) and the original file is not modified.

---

### `graphyn validate`

Validate a pipeline IR JSON or YAML file against the node registry.

```
usage: graphyn validate --graph PATH
       graphyn validate --config PATH   (deprecated)

options:
  --graph PATH    Path to the IR JSON graph file
  --config PATH   Path to the pipeline YAML config file (deprecated)
```

**Example:**

```bash
graphyn validate --graph my-pipeline.graph.json
graphyn validate --config my-pipeline.yaml  # deprecated
```

**Output (valid):**

```
✓ Valid pipeline — 5 node(s):
  [0] dataset_ingest
  [1] audio_conditioner
  [2] segmenter
  [3] feature_frontend
  [4] dataset_builder
```

**Output (invalid):**

```
✗ Validation failed: Unknown node type 'foo'. Available types: audio_conditioner, segmenter, ...
```

Exits with code `0` on success, `1` on failure.

---

### `graphyn runs list`

Print a table of recent pipeline runs, newest first.

```
usage: graphyn runs list
```

**Example:**

```bash
graphyn runs list
```

**Output:**

```
RUN ID        STATUS      CREATED AT                DURATION
--------------------------------------------------------------------
a1b2c3d4      completed   2024-01-01T00:00:00+00:00     1.2s
b2c3d4e5      failed      2023-12-31T23:59:00+00:00     0.3s
```

Status is color-coded in terminals that support ANSI: green for `completed`, red for `failed`, yellow for others.

---

### `graphyn runs logs`

Print log entries for a specific run.

```
usage: graphyn runs logs RUN_ID

positional arguments:
  RUN_ID   Run ID (or unique prefix) to fetch logs for
```

**Example:**

```bash
graphyn runs logs a1b2c3d4
graphyn runs logs a1b2   # prefix match
```

**Output:**

```
[2024-01-01T00:00:00+00:00] [INFO] Pipeline starting — 5 nodes
[2024-01-01T00:00:00+00:00] [INFO] [0] InputNode — starting
[2024-01-01T00:00:00+00:00] [INFO] [0] InputNode — done in 0.123s → 42 samples
...
```

Partial run ID prefix matching is supported: if the prefix uniquely identifies one run, it is used. If ambiguous, an error is printed.

Log entries are color-coded in terminals: red for `ERROR`, yellow for `WARNING`, default for others.

---

### `graphyn artifacts`

Inspect artifacts and lineage from the command line (Phase 4).

#### `graphyn artifacts list`

List registered artifacts, optionally filtered by run ID and/or artifact type.

```
usage: graphyn artifacts list [--run RUN_ID] [--type ARTIFACT_TYPE]

options:
  --run RUN_ID            Filter by run ID (optional)
  --type ARTIFACT_TYPE    Filter by artifact type (optional)
```

**Example:**

```bash
graphyn artifacts list
graphyn artifacts list --run a1b2c3d4
graphyn artifacts list --type audio_samples
```

**Output:**

```
ARTIFACT ID   TYPE              NODE TYPE   RUN ID      CREATED AT
---------------------------------------------------------------------------
abc12345      audio_samples     audio_conditioner   a1b2c3d4    2024-01-01T00:00:00+00:00
```

Prints `"No artifacts found."` and exits 0 when no artifacts match.

#### `graphyn artifacts get`

Print the full `ArtifactRecord` as formatted JSON.

```
usage: graphyn artifacts get ARTIFACT_ID

positional arguments:
  ARTIFACT_ID   The artifact ID to retrieve
```

**Example:**

```bash
graphyn artifacts get abc12345
```

Exits 1 with an error to stderr if the artifact ID is not found.

#### `graphyn artifacts lineage`

Print the upstream lineage tree for an artifact as formatted JSON.

```
usage: graphyn artifacts lineage ARTIFACT_ID

positional arguments:
  ARTIFACT_ID   The artifact ID to trace lineage for
```

**Example:**

```bash
graphyn artifacts lineage abc12345
```

Always exits 0 — returns a partial tree with `"error"` nodes for missing provenance records.

#### `graphyn artifacts replay`

Re-execute a pipeline using the `graph.json` stored for a prior run. Runs synchronously (blocking).

```
usage: graphyn artifacts replay RUN_ID

positional arguments:
  RUN_ID   The original run ID whose graph.json to replay
```

**Example:**

```bash
graphyn artifacts replay a1b2c3d4
# → Replayed as run b2c3d4e5
```

Exits 1 with an error to stderr if `workspace/runs/{run_id}/graph.json` does not exist.

---

### `graphyn plugin`

Manage plugins from the command line. All subcommands delegate to `PluginManager`.

#### `graphyn plugin install`

Install a plugin from a source string (local path, Git URL, HTTP archive URL, or plugin name).

```
usage: graphyn plugin install SOURCE [--upgrade]

positional arguments:
  SOURCE      Plugin source string

options:
  --upgrade   Replace an existing installation with the same name
```

**Example:**

```bash
graphyn plugin install audio-denoiser
# → ✓ Installed audio-denoiser 1.2.0
graphyn plugin install audio-denoiser --upgrade
graphyn plugin install git+https://github.com/org/my-plugin.git
graphyn plugin install /path/to/my-plugin/
```

Exits 1 with an error to stderr on any failure (`PluginError` subclass).

#### `graphyn plugin list`

Print a table of installed plugins with columns `NAME`, `VERSION`, `STATUS`, `SOURCE`.

```
usage: graphyn plugin list [--enabled]

options:
  --enabled   Show only enabled plugins
```

**Example:**

```bash
graphyn plugin list
graphyn plugin list --enabled
```

#### `graphyn plugin enable`

Enable an installed plugin and reload its node types.

```
usage: graphyn plugin enable NAME
```

**Example:**

```bash
graphyn plugin enable audio-denoiser
# → ✓ Enabled audio-denoiser
```

#### `graphyn plugin disable`

Disable an installed plugin and unload its node types.

```
usage: graphyn plugin disable NAME
```

**Example:**

```bash
graphyn plugin disable audio-denoiser
# → ✓ Disabled audio-denoiser
```

#### `graphyn plugin remove`

Uninstall a plugin (removes files and registry entry).

```
usage: graphyn plugin remove NAME
```

**Example:**

```bash
graphyn plugin remove audio-denoiser
# → ✓ Removed audio-denoiser
```

#### `graphyn plugin search`

Search the plugin index by name, description, or tags.

```
usage: graphyn plugin search QUERY
```

**Example:**

```bash
graphyn plugin search denois
```

Prints a table with columns `NAME`, `VERSION`, `DESCRIPTION`, `TAGS`.

#### `graphyn plugin info`

Print full details for a plugin as formatted JSON. Shows the installed `PluginRecord` if installed, otherwise falls back to the index entry.

```
usage: graphyn plugin info NAME
```

**Example:**

```bash
graphyn plugin info audio-denoiser
```

Exits 1 if the plugin is not installed and not found in the index.

---

### `graphyn migrate`

Convert a YAML pipeline config to the canonical IR JSON format.

```
usage: graphyn migrate --config PATH [--output PATH]

options:
  --config PATH   Path to the YAML pipeline config file (required)
  --output PATH   Output path for the IR JSON file (default: same dir, .graph.json extension)
```

**Example:**

```bash
graphyn migrate --config my-pipeline.yaml
# → writes my-pipeline.graph.json
graphyn migrate --config my-pipeline.yaml --output /tmp/out.graph.json
```

---

### `graphyn mcp`

Start the MCP server (stdio transport). Reads JSON-RPC from stdin, writes responses to stdout. Logs to stderr.

```
usage: graphyn mcp
```

**Example:**

```bash
graphyn mcp
GRAPHYN_API_TOKEN=secret graphyn mcp   # with auth
python -m app.mcp.server               # equivalent direct invocation
```

The server starts in-process, sharing the already-populated `NodeRegistry` singleton. All 8 MCP tools are registered at startup. See [MCP_SERVER.md](./MCP_SERVER.md) for the full tool reference.

---

## Environment Variables

Both the SDK and CLI respect:

| Variable | Default | Purpose |
|---|---|---|
| `GRAPHYN_PROJECT_DIR` | `"workspace"` | Root workspace directory for runs, datasets, cache |
| `GRAPHYN_PLUGINS_DIR` | `"plugins"` | Plugin directory scanned by AutoDiscovery |
