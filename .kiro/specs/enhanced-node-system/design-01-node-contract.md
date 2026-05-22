# Design 01 — Node Contract: Configuration, Multi-Port Typed I/O, Domain Support

← [Back to design.md](design.md) | ← [Back to requirements](req-01-node-contract.md)

---

## 1. `PortDataType` and `AudioSample` Migration

`PortDataType` is the base class for all domain-specific data types carried on ports. It is a Pydantic `BaseModel` with `arbitrary_types_allowed=True` so that fields like `numpy.ndarray` are permitted.

### `app/core/nodes/ports.py` — PortDataType

```python
# app/core/nodes/ports.py
from __future__ import annotations

from typing import Any, Literal, get_args, get_origin
from pydantic import BaseModel, ConfigDict


class PortDataType(BaseModel):
    """Base class for all port data types.

    Subclass this to define custom domain types (e.g. AudioSample, TFLiteModel).
    AutoDiscovery registers every subclass in TypeCatalogue automatically.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)


class InputPort(BaseModel):
    """Descriptor for a node's input port."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    data_type: Any  # type | None — stored as Python type object
    cardinality: Literal["single", "multi"] = "single"
    required: bool = True
    description: str = ""


class OutputPort(BaseModel):
    """Descriptor for a node's output port."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    data_type: Any  # type | None
    description: str = ""
```

### `app/models/audio_sample.py` — Migrated to Pydantic + PortDataType

```python
# app/models/audio_sample.py
from __future__ import annotations

from typing import Any, Optional
import numpy as np
from pydantic import ConfigDict, field_validator
from app.core.nodes.ports import PortDataType


class AudioSample(PortDataType):
    """A single audio clip with its waveform, sample rate, label, and metadata.

    Replaces the old @dataclass. Registered in TypeCatalogue as
    'app.models.audio_sample.AudioSample' by AutoDiscovery.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: str
    sample_rate: int
    data: Optional[Any] = None   # numpy.ndarray | None
    label: str = ""
    metadata: dict[str, Any] = {}

    @field_validator("data", mode="before")
    @classmethod
    def _coerce_data(cls, v: Any) -> Any:
        if v is None:
            return np.array([], dtype=np.float32)
        return v

    def model_post_init(self, __context: Any) -> None:
        # Ensure data is always float32 ndarray
        if not isinstance(self.data, np.ndarray):
            object.__setattr__(self, "data", np.asarray(self.data, dtype=np.float32))
```

> **Migration note**: The old `@dataclass` had positional construction `AudioSample(path, sample_rate, data, label, metadata)`. All existing call sites use keyword arguments or are in node `process()` methods that will be updated. The Pydantic model accepts the same keyword arguments.

---

## 2. `NodeConfig` Base Class

```python
# app/core/nodes/config.py
from __future__ import annotations
from pydantic import BaseModel, ConfigDict


class NodeConfig(BaseModel):
    """Base class for all node configuration models.

    Each Node subclass declares an inner Config(NodeConfig) class.
    Supports lossless JSON round-trip via model_dump(mode='json') /
    model_validate_json(json_str).
    """
    model_config = ConfigDict(
        extra="forbid",          # unknown fields raise ValidationError
        frozen=False,            # configs are mutable after construction
        populate_by_name=True,
    )
```

### Example: `CleanConfig`

```python
class CleanConfig(NodeConfig):
    sample_rate: int = 16000
```

### Example: `AugmentConfig`

```python
from pydantic import field_validator

class AugmentConfig(NodeConfig):
    gain_db: list[float]          # [min, max]
    copies_per_sample: int = 1

    @field_validator("gain_db")
    @classmethod
    def _check_gain_range(cls, v: list[float]) -> list[float]:
        if len(v) != 2:
            raise ValueError("gain_db must be [min, max]")
        return v

    @field_validator("copies_per_sample")
    @classmethod
    def _check_copies(cls, v: int) -> int:
        if v < 0:
            raise ValueError("copies_per_sample must be >= 0")
        return v
```

---

## 3. `Node` Base Class

```python
# app/core/nodes/base.py
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import (
    Any, AsyncGenerator, ClassVar, Generic, TypeVar
)

from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.core.nodes.retry import RetryPolicy

log = logging.getLogger(__name__)

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class Node(Generic[InputT, OutputT]):
    """Domain-agnostic base class for all pipeline nodes.

    Subclasses MUST declare:
        node_type: ClassVar[str]          (or rely on auto-derived name)
        metadata:  ClassVar[NodeMetadata]
        input_ports:  ClassVar[dict[str, InputPort]]
        output_ports: ClassVar[dict[str, OutputPort]]

        class Config(NodeConfig): ...     (inner Pydantic config model)

    SISO shorthand: if input_ports == {"input": ...} and
    output_ports == {"output": ...}, override process(self, data) instead
    of process(self, inputs: dict) -> dict.  The wrapper is installed by
    __init_subclass__ automatically.
    """

    # ── class-level declarations (overridden by subclasses) ──────────────────
    node_type: ClassVar[str] = ""
    metadata: ClassVar[NodeMetadata]
    input_ports: ClassVar[dict[str, InputPort]] = {}
    output_ports: ClassVar[dict[str, OutputPort]] = {}
    retry_policy: ClassVar[RetryPolicy | None] = None

    class Config(NodeConfig):
        """Default empty config — subclasses replace this."""
        pass

    # ── construction ─────────────────────────────────────────────────────────
    def __init__(
        self,
        config: "Config | dict[str, Any]",
        seed: int = 0,
        observer: "NodeObserver | None" = None,
    ) -> None:
        if isinstance(config, dict):
            self.config: NodeConfig = self.Config.model_validate(config)
        elif isinstance(config, self.Config):
            self.config = config
        else:
            # Accept any NodeConfig subclass (e.g. when called from tests)
            self.config = self.Config.model_validate(config.model_dump())
        self.seed = seed
        self.observer = observer
        self._run_id: str = ""   # set by pipeline executor per execution

    # ── SISO wrapper installation ─────────────────────────────────────────────
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _maybe_wrap_siso(cls)

    # ── SISO convenience properties ───────────────────────────────────────────
    @property
    def input_type(self) -> type | None:
        if not self._is_siso():
            raise AttributeError(
                f"{type(self).__name__} is not a SISO node; "
                "use input_ports directly"
            )
        return self.input_ports["input"].data_type

    @property
    def output_type(self) -> type | None:
        if not self._is_siso():
            raise AttributeError(
                f"{type(self).__name__} is not a SISO node; "
                "use output_ports directly"
            )
        return self.output_ports["output"].data_type

    @classmethod
    def _is_siso(cls) -> bool:
        return (
            set(cls.input_ports.keys()) == {"input"}
            and set(cls.output_ports.keys()) == {"output"}
        )

    # ── port schema introspection ─────────────────────────────────────────────
    @classmethod
    def port_schemas(cls) -> dict[str, Any]:
        """Return JSON Schema representations of all ports.

        Returns:
            {
                "inputs":  {port_name: json_schema_dict | null},
                "outputs": {port_name: json_schema_dict | null},
            }
        """
        from app.core.nodes.compat import _type_to_schema
        return {
            "inputs": {
                name: _type_to_schema(port.data_type)
                for name, port in cls.input_ports.items()
            },
            "outputs": {
                name: _type_to_schema(port.data_type)
                for name, port in cls.output_ports.items()
            },
        }

    # ── canonical multi-port process signature ────────────────────────────────
    def process(
        self, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Override in multi-port nodes.

        SISO nodes override process(self, data) instead; the wrapper
        installed by __init_subclass__ translates between conventions.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement process()"
        )

    # ── streaming ─────────────────────────────────────────────────────────────
    async def process_stream(
        self, inputs: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Override in streaming nodes.

        Default implementation wraps process() as a single-item generator.
        """
        result = self.process(inputs)
        yield result

    @classmethod
    @property
    def is_streaming(cls) -> bool:
        return cls.process_stream is not Node.process_stream  # type: ignore[comparison-overlap]

    # ── lifecycle hooks (no-op defaults) ─────────────────────────────────────
    def setup(self) -> None:
        """Called once before the first on_start(). Load models, open files."""

    def on_start(self) -> None:
        """Called immediately before each process() invocation."""

    def on_end(self) -> None:
        """Called immediately after process() returns without raising."""

    def on_error(self, exc: Exception) -> None:
        """Called when process() raises, before the exception propagates."""

    def teardown(self) -> None:
        """Called once after the final on_end() or after on_error() if not retried."""


# ── SISO wrapper helper ───────────────────────────────────────────────────────

def _maybe_wrap_siso(cls: type) -> None:
    """If cls is a SISO node that overrides process(self, data), wrap it.

    Detection: the class defines process() with a signature that does NOT
    match (self, inputs: dict) — i.e. the second parameter is not named
    'inputs'.  We check by inspecting the parameter names.
    """
    if "process" not in cls.__dict__:
        return  # no override in this class

    raw_process = cls.__dict__["process"]
    params = list(inspect.signature(raw_process).parameters.keys())

    # Multi-port signature: (self, inputs) — leave alone
    if len(params) >= 2 and params[1] == "inputs":
        return

    # SISO signature: (self, data) or (self, _) or (self, samples) etc.
    # Wrap it.
    def _siso_process(
        self: "Node",
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        data = inputs.get("input")
        result = raw_process(self, data)
        return {"output": result}

    _siso_process.__wrapped__ = raw_process  # type: ignore[attr-defined]
    cls.process = _siso_process  # type: ignore[method-assign]
```

### SISO Wrapper — Detailed Explanation

```
CleanNode defines:
    def process(self, samples):   ← SISO signature (param[1] != "inputs")
        ...

__init_subclass__ detects this and replaces it with:
    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        data = inputs.get("input")          # unpack
        result = raw_process(self, data)    # call original
        return {"output": result}           # repack

The original is stored as process.__wrapped__ for testing.

Pipeline executor always calls:
    node.process({"input": payload})
    result = node.process(...)["output"]

SISO nodes are transparent to the executor.
```

---

## 4. `CompatibilityChecker`

```python
# app/core/nodes/compat.py
from __future__ import annotations

from typing import Any, get_args, get_origin

from app.core.nodes.errors import NodeTypeError


class CompatibilityChecker:
    """Determines whether an output port type is compatible with an input port type."""

    @staticmethod
    def are_compatible(
        output_type: type | None,
        input_type: type | None,
    ) -> bool:
        """Return True if a value of output_type can flow into input_type.

        Rules (applied in order):
          1. Both None  → True   (source→sink direct connection)
          2. One None   → False  (type mismatch with untyped port)
          3. Both plain classes → issubclass(output_type, input_type)
          4. Either is a generic alias → origins must match AND
             each pair of type args must be recursively compatible.
        """
        if output_type is None and input_type is None:
            return True
        if output_type is None or input_type is None:
            return False

        out_origin = get_origin(output_type)
        in_origin = get_origin(input_type)

        # Both are plain (non-generic) classes
        if out_origin is None and in_origin is None:
            try:
                return issubclass(output_type, input_type)
            except TypeError:
                return False

        # At least one is a generic alias
        if out_origin != in_origin:
            return False

        out_args = get_args(output_type)
        in_args = get_args(input_type)

        if len(out_args) != len(in_args):
            return False

        return all(
            CompatibilityChecker.are_compatible(oa, ia)
            for oa, ia in zip(out_args, in_args)
        )

    @staticmethod
    def check_connection(
        src_node: "Node",
        src_port: str,
        dst_node: "Node",
        dst_port: str,
    ) -> None:
        """Raise NodeTypeError if the connection is invalid.

        Checks:
          - src_port exists on src_node.output_ports
          - dst_port exists on dst_node.input_ports
          - are_compatible(src_port.data_type, dst_port.data_type)
        """
        from app.core.nodes.errors import NodeTypeError

        if src_port not in src_node.output_ports:
            raise NodeTypeError(
                f"Node '{type(src_node).__name__}' has no output port '{src_port}'. "
                f"Available: {list(src_node.output_ports)}"
            )
        if dst_port not in dst_node.input_ports:
            raise NodeTypeError(
                f"Node '{type(dst_node).__name__}' has no input port '{dst_port}'. "
                f"Available: {list(dst_node.input_ports)}"
            )

        out_type = src_node.output_ports[src_port].data_type
        in_type = dst_node.input_ports[dst_port].data_type

        if not CompatibilityChecker.are_compatible(out_type, in_type):
            raise NodeTypeError(
                f"Incompatible connection: "
                f"{type(src_node).__name__}.{src_port} ({out_type!r}) "
                f"→ {type(dst_node).__name__}.{dst_port} ({in_type!r})"
            )


def _type_to_schema(t: type | None) -> dict[str, Any] | None:
    """Convert a port data_type to a minimal JSON Schema dict."""
    if t is None:
        return None

    from pydantic import BaseModel
    if isinstance(t, type) and issubclass(t, BaseModel):
        return t.model_json_schema()

    origin = get_origin(t)
    if origin is list:
        args = get_args(t)
        item_schema = _type_to_schema(args[0]) if args else {}
        return {"type": "array", "items": item_schema}
    if origin is dict:
        return {"type": "object"}
    if origin is tuple:
        return {"type": "array"}

    _BUILTIN_MAP = {
        int: "integer",
        float: "number",
        str: "string",
        bool: "boolean",
        bytes: "string",
    }
    return {"type": _BUILTIN_MAP.get(t, str(getattr(t, "__name__", t)))}
```

---

## 5. Migrated Audio Node Examples

All audio nodes follow the same migration pattern. Below are two representative examples.

### `CleanNode` (migrated)

```python
# app/core/nodes/clean.py  (excerpt — migrated)
from __future__ import annotations

from typing import ClassVar
import librosa
import numpy as np
from copy import deepcopy

from pydantic import field_validator
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample


class CleanConfig(NodeConfig):
    sample_rate: int = 16000


class CleanNode(Node[list[AudioSample], list[AudioSample]]):
    node_type: ClassVar[str] = "clean"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="clean",
        label="Clean",
        description="Resample to a target sample rate and peak-normalize.",
        category="Preprocessing",
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list[AudioSample])
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[AudioSample])
    }

    class Config(CleanConfig): pass

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        # Unchanged from pre-migration — SISO wrapper handles dict convention
        out = []
        for s in samples:
            new = deepcopy(s)
            y = new.data
            if new.sample_rate != self.config.sample_rate:
                y = librosa.resample(
                    y=y, orig_sr=new.sample_rate, target_sr=self.config.sample_rate
                )
            peak = max(abs(y).max(), 1e-6)
            new.data = (y / peak).astype("float32")
            new.sample_rate = self.config.sample_rate
            out.append(new)
        return out
```

### `InputNode` (source node — no input port)

```python
# app/core/nodes/input.py  (excerpt — migrated)
from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

import librosa
from pydantic import field_validator

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

SUPPORTED_AUDIO_EXTENSIONS = (".wav", ".mp3", ".m4a", ".ogg", ".webm")
INPUT_ROOT = Path("workspace/datasets/input").resolve()


class InputConfig(NodeConfig):
    path: str

    @field_validator("path")
    @classmethod
    def _validate_path(cls, v: str) -> str:
        resolved = Path(v).resolve()
        if os.path.commonpath([str(INPUT_ROOT), str(resolved)]) != str(INPUT_ROOT):
            raise ValueError("input.path must be inside workspace/datasets/input")
        return v


class InputNode(Node[None, list[AudioSample]]):
    node_type: ClassVar[str] = "input"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="input",
        label="Input",
        description="Load audio files from a workspace input folder.",
        category="Input",
    )
    # Source node: no input ports
    input_ports: ClassVar[dict[str, InputPort]] = {}
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[AudioSample])
    }

    class Config(InputConfig): pass

    def process(self, inputs: dict) -> dict:
        # Source node uses multi-port signature directly (no SISO wrap)
        samples = []
        path = Path(self.config.path).resolve()
        for root, _, files in os.walk(path):
            for f in sorted(files):
                if f.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS):
                    file_path = os.path.join(root, f)
                    label = os.path.basename(root)
                    y, sr = librosa.load(file_path, sr=None)
                    samples.append(AudioSample(
                        path=file_path, sample_rate=sr,
                        data=y, label=label, metadata={}
                    ))
        return {"output": samples}
```

### `SplitNode` (non-SISO: `list[AudioSample]` in, `dict[str, list[AudioSample]]` out)

```python
# app/core/nodes/split.py  (excerpt — migrated)
from __future__ import annotations

from typing import ClassVar
from pydantic import model_validator

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample


class SplitConfig(NodeConfig):
    train: float = 0.8
    val: float = 0.1

    @model_validator(mode="after")
    def _check_fractions(self) -> "SplitConfig":
        if self.train + self.val >= 1.0:
            raise ValueError("train + val must be < 1")
        return self


SplitOutput = dict[str, list[AudioSample]]


class SplitNode(Node[list[AudioSample], SplitOutput]):
    node_type: ClassVar[str] = "split"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="split",
        label="Split",
        description="Partition samples into train / val / test splits.",
        category="Splitting",
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list[AudioSample])
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=SplitOutput)
    }

    class Config(SplitConfig): pass

    def process(self, samples: list[AudioSample]) -> SplitOutput:
        # Unchanged logic — SISO wrapper handles dict convention
        ...
```

---

## 6. Complete Config Classes for All Existing Nodes

| Node class | Config class | Required fields | Defaults |
|---|---|---|---|
| `InputNode` | `InputConfig` | `path: str` | — |
| `MicInputNode` | `MicInputConfig` | — | `path="workspace/datasets/input/mic"` |
| `SegmentNode` | `SegmentConfig` | `window_ms: int` | `overlap=0.0` |
| `CleanNode` | `CleanConfig` | — | `sample_rate=16000` |
| `TrimNode` | `TrimConfig` | — | `threshold_db=-40`, `frame_length=2048`, `hop_length=512` |
| `ResampleNode` | `ResampleConfig` | `target_sample_rate: int` | `quality="kaiser_best"` |
| `FormatConvertNode` | `FormatConvertConfig` | — | `channels="mono"` |
| `NormalizeNode` | `NormalizeConfig` | — | `method="peak"`, `target_level=0.0` |
| `GainNode` | `GainConfig` | — | `gain_db=0.0` |
| `AugmentNode` | `AugmentConfig` | `gain_db: list[float]` | `copies_per_sample=1` |
| `PitchShiftNode` | `PitchShiftConfig` | `semitones: list[float]` | `copies_per_sample=1` |
| `TimeStretchNode` | `TimeStretchConfig` | `rate: list[float]` | `copies_per_sample=1` |
| `SpeedPerturbNode` | `SpeedPerturbConfig` | `speed_factor: list[float]` | `copies_per_sample=1` |
| `ReverbNode` | `ReverbConfig` | `impulse_response_path: str` | `copies_per_sample=1` |
| `NoiseMixNode` | `NoiseMixConfig` | `noise_dir: str`, `snr_db: list[float]` | `copies_per_sample=1` |
| `FilterNode` | `FilterConfig` | — | `filter_type="lowpass"`, `cutoff_freq=4000`, `order=5` |
| `FadeNode` | `FadeConfig` | — | `fade_in_ms=10`, `fade_out_ms=10`, `fade_shape="linear"` |
| `DenoiseNode` | `DenoiseConfig` | — | `method="spectral_subtraction"`, `noise_profile_ms=100` |
| `ConcatenateNode` | `ConcatenateConfig` | — | `group_by="label"`, `max_samples_per_group=10` |
| `TagNode` | `TagConfig` | — | `tags="{}"` |
| `DuplicateNode` | `DuplicateConfig` | — | `target_count=100`, `strategy="balance"` |
| `SpectrogramNode` | `SpectrogramConfig` | `output_path: str` | `feature_type="mel"`, `output_format="npy"` |
| `CompressionNode` | `CompressionConfig` | — | `threshold_db=-20`, `ratio=4.0`, `attack_ms=5`, `release_ms=50` |
| `VADNode` | `VADConfig` | — | `mode="trim"`, `aggressiveness=2`, `frame_ms=30` |
| `PaddingNode` | `PaddingConfig` | — | `pad_start_ms=0`, `pad_end_ms=0` |
| `SilenceDetectorNode` | `SilenceDetectorConfig` | — | `threshold_db=-60`, `action="flag"` |
| `SplitNode` | `SplitConfig` | — | `train=0.8`, `val=0.1` |
| `StratifiedSplitNode` | `StratifiedSplitConfig` | — | `train=0.8`, `val=0.1` |
| `ExportNode` | `ExportConfig` | `output: str`, `project: str`, `version: str` | — |
| `HFExportNode` | `HFExportConfig` | — | `mode="local"`, `repo_id=""`, `output_path=""`, `token=""` |
| `TFRecordExportNode` | `TFRecordExportConfig` | `output_path: str` | — |

---

## 7. Errors Module

```python
# app/core/nodes/errors.py
from __future__ import annotations


class NodeSystemError(Exception):
    """Base class for all Enhanced Node System errors."""


class NodeNotFoundError(NodeSystemError):
    """Raised when a node_type is not found in the registry."""


class DuplicateNodeTypeError(NodeSystemError):
    """Raised when two classes resolve to the same node_type during AutoDiscovery."""


class NodeMetadataError(NodeSystemError):
    """Raised when a Node subclass is missing required metadata fields."""


class NodeTypeError(NodeSystemError):
    """Raised when an output port type is incompatible with an input port type."""


class PortTypeNotFoundError(NodeSystemError):
    """Raised when a type name cannot be resolved in TypeCatalogue."""


class DuplicatePortTypeError(NodeSystemError):
    """Raised when a PortDataType subclass is registered under a name already in use."""


class PipelineGraphError(NodeSystemError):
    """Raised for invalid pipeline graph structure (cycles, missing ports, etc.)."""
```
