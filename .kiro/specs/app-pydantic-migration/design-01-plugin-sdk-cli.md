# Design Sub-File 01 — Plugin, SDK, CLI

← Back to [design.md](design.md)

This sub-file covers the migration of:
1. `plugins/noise_node.py` — complete rewrite to use the Enhanced Node System
2. `app/core/sdk.py` — rename `Node` → `PipelineNode`, use `NodeRegistry` API
3. `app/cli/main.py` — update `cmd_validate` to use `NodeRegistry` accessor methods

---

## 1. NoiseNode Plugin Migration

### Current Implementation

```python
# plugins/noise_node.py (BEFORE)
import numpy as np
import copy
from app.core.nodes.base import Node


class NoiseNode(Node):
    REQUIRED_CONFIG = ["noise_level"]

    def __init__(self, config, seed):
        super().__init__(config, seed)
        self.rng = np.random.default_rng(seed)

    def process(self, samples):
        out = []
        for s in samples:
            new = copy.deepcopy(s)
            noise = self.rng.standard_normal(len(new.data)) * self.config["noise_level"]
            new.data = (new.data + noise).astype("float32")
            out.append(new)
        return out


def register(registry):
    registry["noise"] = {
        "class": NoiseNode,
        "label": "Noise",
        "description": "Add Gaussian noise to sample waveforms",
        "kind": "plugin",
        "schema": {
            "noise_level": {
                "type": "number",
                "required": True,
                "default": 0.005,
            }
        },
        "input_type": "samples",
        "output_type": "samples",
    }
```

**Problems**:
- Uses old dict-based registry format
- Requires manual `register()` function
- Config is accessed as `self.config["noise_level"]` (dict-style)
- No typed ports
- No `NodeMetadata`

### New Implementation

```python
# plugins/noise_node.py (AFTER)
"""NoiseNode plugin — adds Gaussian noise to audio samples."""
from __future__ import annotations

import copy
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample


class NoiseNode(Node):
    """Add Gaussian noise to sample waveforms.

    Scales noise by the configured `noise_level` parameter.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="noise",
        label="Noise",
        description="Add Gaussian noise to sample waveforms",
        category="augmentation",
        version="1.0.0",
        tags=["plugin", "augmentation", "noise"],
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="Audio samples to augment with noise",
        ),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Audio samples with added Gaussian noise",
        ),
    }

    class Config(NodeConfig):
        """Configuration for NoiseNode."""
        noise_level: float = 0.005

    def __init__(self, config=None, seed=0, observer=None):
        super().__init__(config, seed, observer)
        self.rng = np.random.default_rng(seed)

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        """Add Gaussian noise scaled by noise_level to each sample's data array.

        SISO shorthand: accepts list[AudioSample], returns list[AudioSample].
        The SISO wrapper installed by Node.__init_subclass__ translates this
        to the canonical process(self, inputs: dict) -> dict signature.
        """
        out = []
        for s in samples:
            new = copy.deepcopy(s)
            noise = self.rng.standard_normal(len(new.data)) * self.config.noise_level
            new.data = (new.data + noise).astype("float32")
            out.append(new)
        return out
```

**Changes**:
- ✅ Subclasses `Node` with `metadata` ClassVar
- ✅ Declares typed `input_ports` and `output_ports`
- ✅ Inner `Config(NodeConfig)` with `noise_level: float = 0.005`
- ✅ Uses SISO shorthand: `process(self, samples)` → `list[AudioSample]`
- ✅ Config accessed as `self.config.noise_level` (attribute access)
- ✅ No `register()` function — AutoDiscovery picks it up automatically

### Migration Notes

- The `REQUIRED_CONFIG` class variable is removed — Pydantic handles required fields via the `Config` model.
- The `__init__` signature changes from `(config, seed)` to `(config=None, seed=0, observer=None)` to match the `Node` base class.
- The `process` method signature is unchanged (SISO shorthand), but the return type annotation is added for clarity.
- The `register()` function is deleted entirely.

---

## 2. SDK Node Wrapper Migration

### Current Implementation

```python
# app/core/sdk.py (BEFORE — excerpt)
class Node:
    """Represents a single pipeline node with a type and configuration.

    Validates config against the registry schema on instantiation.
    """

    def __init__(self, node_type: str, config: dict[str, Any] | None = None):
        self.node_type = node_type
        self.config = config or {}
        self._validate()

    def _validate(self) -> None:
        """Validate config against the registry schema."""
        from app.core.registry_runtime import get_registry
        from app.core.validation import validate_node_config

        registry = get_registry()
        if self.node_type not in registry:
            raise ValueError(
                f"Unknown node type '{self.node_type}'. "
                f"Available types: {', '.join(sorted(registry.keys()))}"
            )

        schema = registry[self.node_type]["schema"]  # ❌ dict-style access
        errors = validate_node_config(self.node_type, self.config, schema)  # ❌ legacy function
        if errors:
            error_lines = [f"  {field}: {msg}" for field, msg in errors.items()]
            raise ValueError(
                f"Invalid config for node '{self.node_type}':\n"
                + "\n".join(error_lines)
            )

    def to_dict(self) -> dict:
        return {"type": self.node_type, "config": self.config}
```

**Problems**:
- Class name `Node` shadows `app.core.nodes.base.Node`
- Uses `registry[node_type]["schema"]` dict-style access
- Calls legacy `validate_node_config` function

### New Implementation

```python
# app/core/sdk.py (AFTER — excerpt)
class PipelineNode:
    """Represents a single pipeline node with a type and configuration.

    Validates config against the registry schema on instantiation.
    """

    def __init__(self, node_type: str, config: dict[str, Any] | None = None):
        self.node_type = node_type
        self.config = config or {}
        self._validate()

    def _validate(self) -> None:
        """Validate config against the registry schema."""
        from app.core.registry_runtime import get_registry

        registry = get_registry()
        
        # Check node type exists
        try:
            node_class = registry.get_class(self.node_type)
        except Exception:
            raise ValueError(
                f"Unknown node type '{self.node_type}'. "
                f"Available types: {', '.join(sorted(registry._classes.keys()))}"
            )

        # Validate config using the node's Config model
        try:
            node_class.Config.model_validate(self.config)
        except Exception as exc:
            raise ValueError(
                f"Invalid config for node '{self.node_type}': {exc}"
            ) from exc

    def to_dict(self) -> dict:
        return {"type": self.node_type, "config": self.config}
```

**Changes**:
- ✅ Renamed `Node` → `PipelineNode`
- ✅ Uses `registry.get_class(node_type)` instead of `registry[node_type]`
- ✅ Validates via `node_class.Config.model_validate(config)` instead of `validate_node_config`
- ✅ No import of `validate_node_config`

### Pipeline Class Changes

```python
# app/core/sdk.py (AFTER — Pipeline class excerpt)
class Pipeline:
    """Represents a complete pipeline of nodes."""

    def __init__(self, nodes: list[PipelineNode], seed: int = 42):
        self.nodes = nodes
        self.seed = seed

    @classmethod
    def from_yaml(cls, path: str) -> "Pipeline":
        """Load a Pipeline from a YAML file."""
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        pipeline_cfg = config.get("pipeline", {})
        seed = pipeline_cfg.get("seed", 42)
        node_dicts = pipeline_cfg.get("nodes", [])

        nodes = [
            PipelineNode(nd["type"], nd.get("config", {}))  # ✅ PipelineNode
            for nd in node_dicts
        ]
        return cls(nodes=nodes, seed=seed)
```

**Changes**:
- ✅ `from_yaml` constructs `PipelineNode` instances instead of `Node`
- ✅ Type hint updated: `nodes: list[PipelineNode]`

### Migration Notes

- The `Pipeline.run()` method is unchanged — it still writes a temp YAML and calls `run_pipeline()`.
- The `to_yaml()` method is unchanged — it calls `node.to_dict()` which still works.
- All SDK users must update their imports: `from app.core.sdk import PipelineNode` (not `Node`).

---

## 3. CLI Validate Command Migration

### Current Implementation

```python
# app/cli/main.py (BEFORE — cmd_validate excerpt)
def cmd_validate(args):
    """Validate a pipeline YAML file and print the result."""
    from app.core.validation import validate_pipeline
    from app.core.registry_runtime import get_registry

    config_path = args.config

    if not os.path.isfile(config_path):
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        print(f"YAML parse error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        registry = get_registry()
        nodes = validate_pipeline(config, registry)
        print(f"✓ Valid pipeline — {len(nodes)} node(s):")
        for i, node in enumerate(nodes):
            print(f"  [{i}] {node['type']}")  # ❌ assumes dict format
        sys.exit(0)
    except ValueError as exc:
        print(f"✗ Validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
```

**Problems**:
- The loop `for i, node in enumerate(nodes)` assumes `node` is a dict with a `'type'` key.
- The `validate_pipeline` function returns a list of dicts in the old format.
- No explicit use of `registry[node_type]` in this function, but the output loop assumes dict format.

### New Implementation

```python
# app/cli/main.py (AFTER — cmd_validate excerpt)
def cmd_validate(args):
    """Validate a pipeline YAML file and print the result."""
    from app.core.validation import validate_pipeline
    from app.core.registry_runtime import get_registry

    config_path = args.config

    if not os.path.isfile(config_path):
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        print(f"YAML parse error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        registry = get_registry()
        nodes = validate_pipeline(config, registry)
        print(f"✓ Valid pipeline — {len(nodes)} node(s):")
        for i, node in enumerate(nodes):
            print(f"  [{i}] {node['type']}")  # ✅ still works (validate_pipeline returns dicts)
        sys.exit(0)
    except ValueError as exc:
        print(f"✗ Validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
```

**Changes**:
- ✅ No changes required — `validate_pipeline` still returns a list of dicts with `'type'` keys.
- ✅ The function already uses `get_registry()` correctly.
- ✅ No dict-style access to `registry[node_type]` in this function.

### Migration Notes

- `validate_pipeline` in `app/core/validation.py` internally calls `registry[node_type]["schema"]` (dict-style access). `NodeRegistry` does not implement `__getitem__`, so this call would raise `TypeError` at runtime. **This is a pre-existing incompatibility** that must be fixed as part of this migration.

  The fix is to add a `__getitem__` compatibility shim to `NodeRegistry` that returns a dict in the old format. This allows `validate_pipeline` and any other legacy caller to continue working without changes to `validation.py` (preserving Requirement 9.7):

  ```python
  # app/core/nodes/registry.py — add compatibility shims
  def __getitem__(self, node_type: str) -> dict:
      """Compatibility shim for legacy code that uses registry[node_type] dict-style access."""
      node_class = self.get_class(node_type)  # raises NodeNotFoundError if missing
      meta = self.get_metadata(node_type)
      return {
          "class": node_class,
          "schema": node_class.Config.model_json_schema(),
          "label": meta.label,
          "description": meta.description,
          "category": meta.category,
          "kind": "plugin" if "plugin" in meta.tags else "base",
          "input_type": "samples",   # legacy string — kept for backward compat
          "output_type": "samples",  # legacy string — kept for backward compat
      }

  def keys(self):
      """Compatibility shim for legacy code that calls registry.keys()."""
      return self._classes.keys()

  def items(self):
      """Compatibility shim for legacy code that iterates registry.items()."""
      return {k: self[k] for k in self._classes}.items()
  ```

- The `cmd_validate` function does not need to change because it only reads the `'type'` key from the returned dicts, which is still present.
- The `cmd_run` function is already correct — it calls `run_pipeline()` which uses the new `NodeRegistry` internally.

---

## Before/After Summary

| File | Lines Changed | Key Changes |
|------|---------------|-------------|
| `plugins/noise_node.py` | ~60 (complete rewrite) | Add `metadata`, `input_ports`, `output_ports`, `Config` inner class; remove `register()` |
| `app/core/sdk.py` | ~15 | Rename `Node` → `PipelineNode`; use `registry.get_class()` + `Config.model_validate()` |
| `app/core/nodes/registry.py` | ~20 | Add `__getitem__`, `keys()`, `items()` compatibility shims |
| `app/cli/main.py` | 0 | No changes required (already correct) |

---

## Testing

**Unit tests** (in `tests/test_migration.py`):
- `test_noise_node_registration()` — assert `"noise" in registry`
- `test_noise_node_no_register_function()` — assert `not hasattr(noise_node_module, 'register')`
- `test_noise_node_metadata()` — assert `NoiseNode.metadata.node_type == "noise"`
- `test_noise_node_config_default()` — assert `NoiseNode().config.noise_level == 0.005`
- `test_sdk_pipeline_node_unknown_type()` — assert `PipelineNode("unknown", {})` raises `ValueError`
- `test_sdk_pipeline_node_invalid_config()` — assert `PipelineNode("clean", {"sample_rate": "invalid"})` raises `ValueError`
- `test_cli_validate_success()` — run `cmd_validate` with valid YAML, assert exit 0
- `test_cli_validate_failure()` — run `cmd_validate` with invalid YAML, assert exit 1

**Property tests** (in `tests/test_properties.py`):
- `test_property_1_noise_scaling()` — Property 1 (NoiseNode noise scaling)
- `test_property_2_sdk_validation_equivalence()` — Property 2 (SDK validation equivalence)
- `test_property_3_sdk_from_yaml_roundtrip()` — Property 3 (SDK from_yaml round-trip)

**Integration tests** (in `tests/test_pipeline_integration.py`):
- `test_noise_node_end_to_end()` — build a pipeline with NoiseNode, run it, verify output
- `test_sdk_pipeline_run()` — use SDK `Pipeline.run()` with a minimal YAML, verify success
