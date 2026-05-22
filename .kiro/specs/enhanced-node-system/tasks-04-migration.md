# Tasks 04 — Migration: AudioSample, All Audio Nodes, registry_runtime.py, validation.py

← [Back to tasks.md](tasks.md)

---

## Tasks

- [x] 21. Migrate `app/models/audio_sample.py` — `AudioSample` to `PortDataType`
  - Change `AudioSample` from `@dataclass` to `class AudioSample(PortDataType)` (Pydantic BaseModel subclass)
  - Add `model_config = ConfigDict(arbitrary_types_allowed=True)`
  - Keep fields: `path: str`, `sample_rate: int`, `data: Optional[Any]`, `label: str`, `metadata: dict`
  - Add `@field_validator("data", mode="before")` coercing `None` → `np.array([], dtype=np.float32)`
  - Add `model_post_init` ensuring `data` is always `float32` ndarray
  - _Requirements: R10.1, R9.1_
  - _Design: design-01-node-contract.md § 1, design.md § Key Decision 4_

- [x] 22. Migrate input/source nodes: `InputNode`, `MicInputNode`
  - For each node: add `node_type: ClassVar[str]`, `metadata: ClassVar[NodeMetadata]`, `input_ports`, `output_ports`
  - `InputNode`: zero input ports (source), output port `data_type=list[AudioSample]`; add `InputConfig(NodeConfig)` with `path: str` and path validator
  - `MicInputNode`: zero input ports (source), output port `data_type=list[AudioSample]`; add `MicInputConfig(NodeConfig)` with `path` defaulting to `"workspace/datasets/input/mic"`
  - Change `__init__(self, config: dict, seed: int)` → `__init__(self, config: Config | dict, seed: int, observer=None)`
  - Keep `process` logic unchanged; use multi-port signature for source nodes (no SISO wrap)
  - _Requirements: R10.1–R10.7, R9.3_
  - _Design: design-01-node-contract.md § 5, § 6_

- [x] 23. Migrate preprocessing nodes: `CleanNode`, `TrimNode`, `ResampleNode`, `FormatConvertNode`, `NormalizeNode`, `GainNode`
  - For each node: add `node_type`, `metadata`, `input_ports` (`data_type=list[AudioSample]`), `output_ports` (`data_type=list[AudioSample]`)
  - Add concrete `Config(NodeConfig)` subclass per node (see design-01-node-contract.md § 6 for field specs)
  - Update `__init__` signature to accept `Config | dict` and `observer=None`
  - Keep `process(self, samples)` signature unchanged — SISO wrapper handles dict convention
  - _Requirements: R10.1–R10.7_
  - _Design: design-01-node-contract.md § 5, § 6_

- [x] 24. Migrate augmentation nodes: `AugmentNode`, `PitchShiftNode`, `TimeStretchNode`, `SpeedPerturbNode`, `ReverbNode`, `NoiseMixNode`
  - For each node: add `node_type`, `metadata`, `input_ports`, `output_ports`
  - Add concrete `Config(NodeConfig)` subclass per node with field validators (e.g. `gain_db` must be `[min, max]` list of length 2)
  - Update `__init__` signature; keep `process(self, samples)` unchanged
  - _Requirements: R10.1–R10.7_
  - _Design: design-01-node-contract.md § 5, § 6_

- [x] 25. Migrate processing/composition nodes: `FilterNode`, `FadeNode`, `DenoiseNode`, `ConcatenateNode`, `TagNode`, `DuplicateNode`, `SegmentNode`, `SpectrogramNode`
  - For each node: add `node_type`, `metadata`, `input_ports`, `output_ports`
  - Add concrete `Config(NodeConfig)` subclass per node
  - Update `__init__` signature; keep `process(self, samples)` unchanged
  - _Requirements: R10.1–R10.7_
  - _Design: design-01-node-contract.md § 5, § 6_

- [x] 26. Migrate compression/VAD nodes: `CompressionNode`, `VADNode`, `PaddingNode`, `SilenceDetectorNode`
  - For each node: add `node_type`, `metadata`, `input_ports`, `output_ports`
  - Add concrete `Config(NodeConfig)` subclass per node
  - Update `__init__` signature; keep `process(self, samples)` unchanged
  - _Requirements: R10.1–R10.7_
  - _Design: design-01-node-contract.md § 5, § 6_

- [x] 27. Migrate split/export nodes: `SplitNode`, `StratifiedSplitNode`, `ExportNode`, `HFExportNode`, `TFRecordExportNode`
  - `SplitNode` / `StratifiedSplitNode`: output port `data_type=dict[str, list[AudioSample]]`; add `SplitConfig` / `StratifiedSplitConfig` with `@model_validator` checking `train + val < 1`
  - `ExportNode`: zero output ports (sink); add `ExportConfig` with `output`, `project`, `version` fields
  - `HFExportNode` / `TFRecordExportNode`: zero output ports (sink); add respective `Config` classes
  - Update `__init__` signatures; keep `process` logic unchanged
  - _Requirements: R10.1–R10.7, R9.4_
  - _Design: design-01-node-contract.md § 5, § 6_

- [x] 28. Delete old `app/core/nodes/registry.py` hand-written format and update `registry_runtime.py`
  - Delete the `NODE_REGISTRY` dict from `app/core/nodes/registry.py` (the file will be replaced by the new `NodeRegistry` class from task 12)
  - Rewrite `app/core/registry_runtime.py` to import and return the `NodeRegistry` singleton:
    ```python
    from app.core.nodes import registry
    def get_registry():
        return registry
    ```
  - Update `app/core/plugins/loader.py` if it references `NODE_REGISTRY` directly — replace with `registry` singleton calls
  - Verify `app/core/pipeline.py` (old linear executor) still imports correctly after this change
  - _Requirements: R10.4_
  - _Design: design.md § Migration Strategy, design-02-registration.md § 3_

- [x] 29. Update `app/core/validation.py` to use `CompatibilityChecker`
  - Replace `_validate_connections` string-based type comparison with `CompatibilityChecker.check_connection`
  - Import `from app.core.nodes.compat import CompatibilityChecker` and `from app.core.nodes import registry as node_registry`
  - Update `_validate_connections` to instantiate minimal node objects (via `__new__`) for type-check-only use
  - Keep all other validation logic (`_validate_types`, `_validate_required`, `validate_node_config`, `validate_pipeline`) unchanged
  - _Requirements: R10.3_
  - _Design: design-04-serialisation.md § 3.6_

- [x]* 30. Write migration regression tests (`tests/test_migration.py`)
  - For each migrated SISO node: construct with the same dict config previously accepted; verify `process` returns same type as before
  - Test `AudioSample` Pydantic construction: `AudioSample(path="x", sample_rate=16000)` works; `data` defaults to empty float32 array
  - Test `AudioSample` with `data=None` → coerced to empty array (not `None`)
  - Test `SplitConfig` with `train + val >= 1` → `ValidationError`
  - Test `InputConfig` with path outside `workspace/datasets/input` → `ValidationError`
  - Test `ExportNode` config dict previously accepted by old `REQUIRED_CONFIG` check → `model_validate` succeeds
  - _Requirements: R10.6–R10.7_

- [x] 31. Checkpoint — migration complete
  - Ensure all tests pass, ask the user if questions arise.
