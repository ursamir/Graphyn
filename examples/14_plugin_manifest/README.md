# Example 14 — Plugin Manifest and Versioning

Demonstrates the full Phase 5 plugin lifecycle — not just dropping a `.py` file, but a proper versioned package with a `plugin.toml` manifest, dependency management, and hot enable/disable.

---

## What This Demonstrates

- `plugin.toml` manifest structure (name, version, entry_points, platform_version, dependencies)
- `PluginManager.install()` — local directory install
- `PluginManager.list_installed()` — list with version and status
- `PluginManager.enable()` / `disable()` — hot toggle (registers/unregisters node types)
- `PluginStore` — JSON-backed plugin registry in `workspace/plugins/`
- `AutoDiscovery` loading manifested plugins at startup
- Using a manifested plugin node in a pipeline

---

## Plugin Structure

```
text_stats_plugin/
├── plugin.toml     — manifest (name, version, entry_points, ...)
├── __init__.py     — package init
└── nodes.py        — TextStatsNode implementation
```

### `plugin.toml`

```toml
[plugin]
name             = "text-stats"
version          = "1.0.0"
description      = "Text statistics node — counts words, chars, sentences."
author           = "AudioBuilder Examples"
platform_version = ">=0.0"
entry_points     = ["nodes.py"]
license          = "MIT"
tags             = ["text", "statistics", "nlp"]
dependencies     = []
```

---

## How to Run

```bash
# Full lifecycle demo (install → use → disable → re-enable → inspect)
venv/bin/python examples/14_plugin_manifest/manifest_demo.py

# CLI equivalents
venv/bin/python -m app.cli.main plugin install examples/14_plugin_manifest/text_stats_plugin/
venv/bin/python -m app.cli.main plugin list
venv/bin/python -m app.cli.main plugin disable text-stats
venv/bin/python -m app.cli.main plugin enable text-stats
venv/bin/python -m app.cli.main plugin info text-stats
venv/bin/python -m app.cli.main plugin remove text-stats
```

---

## Expected Output

```
============================================================
Example 14 — Plugin Manifest and Versioning
============================================================

Step 0 — plugin.toml manifest
  [plugin]
  name             = "text-stats"
  version          = "1.0.0"
  ...

Step 1 — Install plugin from local directory
  ✓ Installed: text-stats v1.0.0
    enabled:     True
    install_path: .../plugins/text-stats

Step 2 — List installed plugins
  1 plugin(s) installed:
    text-stats           v1.0.0  [enabled]

Step 3 — Load plugin and use in pipeline
  ✓ text_stats node registered
    label:    Text Stats
    category: Text Processing
    version:  1.0.0
    tags:     ['text', 'statistics', 'nlp']
  ✓ Pipeline with plugin node completed

Step 4 — Disable and re-enable plugin
  ✓ Disabled:    text-stats  enabled=False
  ✓ Re-enabled:  text-stats  enabled=True

Step 5 — Inspect plugin record
  name:         text-stats
  version:      1.0.0
  enabled:      True
```

---

## Writing Your Own Plugin

1. Create a directory with a `plugin.toml` manifest
2. Add a `nodes.py` file with your `Node` subclass
3. Install with `audiobuilder plugin install ./my-plugin/`

```python
# my_plugin/nodes.py
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from typing import ClassVar

class MyNode(Node):
    node_type: ClassVar[str] = "my_node"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="my_node",
        label="My Node",
        description="Does something useful.",
        category="My Category",
        version="1.0.0",
    )
    input_ports:  ClassVar[dict] = {"input":  InputPort(name="input",  data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(NodeConfig):
        my_param: str = "default"

    def process(self, items: list) -> list:
        # Your processing logic here
        return items
```

---

## Plugin Lifecycle

```
install → load → enable ──► use in pipelines
                disable ──► node types unregistered
                enable  ──► node types re-registered
                remove  ──► uninstalled from workspace/plugins/
```

When a plugin is disabled, its node types are unregistered from the `NodeRegistry`. Pipelines that reference those node types will fail to execute until the plugin is re-enabled.
