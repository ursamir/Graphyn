# Tasks 01 — Plugin, SDK, CLI

← Back to [tasks.md](tasks.md) | Design: [design-01-plugin-sdk-cli.md](design-01-plugin-sdk-cli.md)

**Requirements covered:** 1, 2, 3, 9

**Files changed:**
- `plugins/noise_node.py` — complete rewrite ✅
- `app/core/sdk.py` — rename `Node` → `PipelineNode`, update `_validate` ✅
- `app/cli/main.py` — no code changes; verified by tests ✅
- `tests/test_migration.py` — new/updated unit tests ✅
- `tests/test_properties.py` — new property tests ✅

---

## Task 1.1 — Rewrite `plugins/noise_node.py` to use the Enhanced Node System

**Requirement:** 1.1–1.8

### Sub-tasks

- [x] 1.1.1 Delete the `register(registry)` function and all dict-based registry assignments
- [x] 1.1.2 Add `metadata: ClassVar[NodeMetadata]` with `node_type="noise"`, `label="Noise"`, `description="Add Gaussian noise to sample waveforms"`, `category="augmentation"`, `version="1.0.0"`, `tags=["plugin", "augmentation", "noise"]`
- [x] 1.1.3 Add `input_ports: ClassVar[dict[str, InputPort]]` with a single `"input"` port of `data_type=list[AudioSample]`, `cardinality="single"`, `required=True`
- [x] 1.1.4 Add `output_ports: ClassVar[dict[str, OutputPort]]` with a single `"output"` port of `data_type=list[AudioSample]`
- [x] 1.1.5 Add inner `class Config(NodeConfig)` with `noise_level: float = 0.005`
- [x] 1.1.6 Update `__init__` signature to `(self, config=None, seed=0, observer=None)` matching `Node` base class
- [x] 1.1.7 Update `process` to use `self.config.noise_level` (attribute access, not dict access)
- [x] 1.1.8 Add SISO type annotations: `process(self, samples: list[AudioSample]) -> list[AudioSample]`
- [x] 1.1.9 Remove `REQUIRED_CONFIG` class variable
- [x] 1.1.10 Verify `AutoDiscovery` picks up `NoiseNode` without any `register()` call

### Acceptance checks
- `"noise" in get_registry()` is `True` after import ✅
- `NoiseNode.metadata.node_type == "noise"` ✅
- `NoiseNode().config.noise_level == 0.005` ✅
- `not hasattr(noise_node_module, 'register')` is `True` ✅
- `NoiseNode(config={"noise_level": "bad"})` raises `pydantic.ValidationError` ✅

---

## Task 1.2 — Rename `Node` → `PipelineNode` in `app/core/sdk.py`

**Requirement:** 2.1, 9.5

### Sub-tasks

- [x] 1.2.1 Rename class `Node` to `PipelineNode` in the class definition
- [x] 1.2.2 Update all references to `Node` within `sdk.py`
- [x] 1.2.3 Update `__all__` in `sdk.py` if it exports `Node`
- [x] 1.2.4 Search the codebase for any `from app.core.sdk import Node` and update those imports

### Acceptance checks
- `from app.core.sdk import PipelineNode` succeeds ✅
- `from app.core.sdk import Node` raises `ImportError` ✅
- No occurrence of `class Node` in `app/core/sdk.py` ✅

---

## Task 1.3 — Update `PipelineNode._validate` to use `registry.get_class()` + `Config.model_validate()`

**Requirement:** 2.2–2.5, 2.8, 9.1, 9.2

### Sub-tasks

- [x] 1.3.1 Remove the import of `validate_node_config` from `app/core/validation`
- [x] 1.3.2 Replace `registry[self.node_type]["schema"]` access with `registry.get_class(self.node_type)`
- [x] 1.3.3 Replace the `validate_node_config(...)` call with `node_class.Config.model_validate(self.config)`
- [x] 1.3.4 Wrap the `get_class` call in a `try/except` that raises `ValueError` with the unknown type name
- [x] 1.3.5 Wrap the `model_validate` call in a `try/except` that raises `ValueError` wrapping the `pydantic.ValidationError`
- [x] 1.3.6 Confirm no remaining `registry[node_type]` dict-style access in `sdk.py`

### Acceptance checks
- `PipelineNode("unknown_type", {})` raises `ValueError` containing `"unknown_type"` ✅
- `PipelineNode("clean", {"sample_rate": "not_an_int"})` raises `ValueError` ✅
- `PipelineNode("clean", {"sample_rate": 16000})` succeeds without error ✅
- No `registry[node_type]["schema"]` or `registry[node_type]["class"]` in `sdk.py` ✅

---

## Task 1.4 — Update `Pipeline.from_yaml` to construct `PipelineNode` instances

**Requirement:** 2.7

### Sub-tasks

- [x] 1.4.1 Update `Pipeline.from_yaml` to call `PipelineNode(nd["type"], nd.get("config", {}))` for each node dict
- [x] 1.4.2 Update `Pipeline.__init__` type annotation: `nodes: list[PipelineNode]`
- [x] 1.4.3 Verify `Pipeline.run()` is unchanged — it still writes a temp YAML and calls `run_pipeline()`

### Acceptance checks
- `Pipeline.from_yaml(valid_yaml_path).nodes` is a list of `PipelineNode` instances ✅
- Each `PipelineNode` in the list has `.node_type` and `.config` matching the YAML ✅

---

## Task 1.5 — Verify `app/cli/main.py` requires no changes

**Requirement:** 3.1–3.5

### Sub-tasks

- [x] 1.5.1 Read `app/cli/main.py` and confirm no `registry[node_type]` dict-style access
- [x] 1.5.2 Confirm `cmd_validate` calls `validate_pipeline(config, registry)` and prints node count
- [x] 1.5.3 Confirm `cmd_validate` exits with code 0 on success and code 1 on failure
- [x] 1.5.4 Confirm no `from app.core.sdk import Node` import in `app/cli/main.py`

### Acceptance checks
- `app/cli/main.py` contains zero occurrences of `registry[node_type]` ✅
- `cmd_validate` with a valid YAML exits 0 and prints `"✓ Valid pipeline"` ✅

---

## Task 1.6 — Write unit tests for Group 01

**Requirement:** 1.1–1.8, 2.1–2.8, 3.1–3.5

### Tests to implement

- [x] 1.6.1 `test_noise_node_registration`
- [x] 1.6.2 `test_noise_node_no_register_function`
- [x] 1.6.3 `test_noise_node_metadata`
- [x] 1.6.4 `test_noise_node_config_default`
- [x] 1.6.5 `test_noise_node_config_validation_error`
- [x] 1.6.6 `test_sdk_pipeline_node_unknown_type`
- [x] 1.6.7 `test_sdk_pipeline_node_invalid_config`
- [x] 1.6.8 `test_sdk_pipeline_node_valid_config`
- [x] 1.6.9 `test_sdk_pipeline_node_renamed`
- [x] 1.6.10 `test_sdk_from_yaml_constructs_pipeline_nodes`
- [x] 1.6.11 `test_cli_validate_success`
- [x] 1.6.12 `test_cli_validate_failure`
- [x] 1.6.13 `test_cli_no_dict_registry_access`

### Acceptance checks
- All tests in `tests/test_migration.py` pass for Group 01 items ✅

---

## Task 1.7 — Write property-based tests: Properties 1, 2, 3

**Requirement:** 1.5, 2.3, 2.7

### Tests to implement

- [x] 1.7.1 **Property 1 — NoiseNode noise scaling** (`test_property_1_noise_scaling`) — passes with `max_examples=100` ✅
- [x] 1.7.2 **Property 2 — SDK validation equivalence** (`test_property_2_sdk_validation_equivalence`) — passes with `max_examples=100` ✅
- [x] 1.7.3 **Property 3 — SDK from_yaml round-trip** (`test_property_3_sdk_from_yaml_roundtrip`) — passes with `max_examples=50` ✅

### Acceptance checks
- All three property tests pass ✅
- Each test is annotated with `# Feature:` and `# Validates:` comments ✅
