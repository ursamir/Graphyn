# req-04 — YAML Compatibility Shim, Migration Utility, CLI and API Updates

## Introduction

This document defines requirements for the YAML compatibility shim, the migration utility, and the updates to the CLI and REST API to support IR JSON as the canonical input format while keeping YAML working via a deprecated path.

The goal is a zero-breakage migration: all existing YAML configs continue to work, but users are guided toward the new IR JSON format via deprecation warnings and a migration utility.

---

## Glossary

See [requirements.md](requirements.md) for the full glossary. Terms used here:

- **YAML_Shim**, **Migration_Utility**, **IR**, **GraphIR**, **IR_Loader**, **Pipeline**, **CLI**, **REST_API**, **DAG_Executor**

---

## Requirements

### Requirement 4.1 — YAML Shim: Conversion Function

**User Story:** As a platform developer, I want a function that converts a YAML pipeline config dict to a `GraphIR` object, so that the YAML path can feed into the IR-native executor.

#### Acceptance Criteria

1. THE `YAML_Shim` SHALL provide a function `yaml_config_to_ir(raw: dict) -> GraphIR` in `app/core/ir/yaml_shim.py`.
2. THE `yaml_config_to_ir` function SHALL accept a raw YAML config dict (as produced by `yaml.safe_load`) and return a valid `GraphIR` object.
3. THE `yaml_config_to_ir` function SHALL support both the legacy linear YAML format (no `edges` key, auto-chained) and the explicit-edge YAML format.
4. THE `yaml_config_to_ir` function SHALL map `pipeline.seed` to `IRMetadata.seed`.
5. THE `yaml_config_to_ir` function SHALL map each node's `type` and `config` to an `IRNode` with `id` derived as `f"{node_type}_{index}"`.
6. THE `yaml_config_to_ir` function SHALL map explicit edges to `IREdge` objects with matching `src_id`, `src_port`, `dst_id`, `dst_port` fields.
7. THE `yaml_config_to_ir` function SHALL set `GraphIR.schema_version` to `CURRENT_IR_VERSION`.
8. THE `yaml_config_to_ir` function SHALL set `IRMetadata.name` to `pipeline.name` if present in the YAML, otherwise to `"pipeline"`.

---

### Requirement 4.2 — YAML Shim: Deprecation Warning

**User Story:** As a platform developer, I want loading a YAML config to emit a deprecation warning, so that users are informed that YAML is no longer the canonical format and are directed to the migration utility.

#### Acceptance Criteria

1. THE `YAML_Shim` SHALL provide a function `load_yaml_with_deprecation(path: str) -> GraphIR` that reads a YAML file, converts it to a `GraphIR`, and emits a `DeprecationWarning`.
2. THE `DeprecationWarning` message SHALL include: the path of the YAML file being loaded, the text `"YAML pipeline configs are deprecated"`, and the instruction `"Run 'audiobuilder migrate --config <path>' to convert to IR JSON"`.
3. THE `DeprecationWarning` SHALL be emitted using Python's `warnings.warn()` with `stacklevel=2` so that the warning points to the caller's code.
4. WHEN `Pipeline.from_yaml(path)` is called, THE `Pipeline` SHALL call `load_yaml_with_deprecation(path)` internally.
5. WHEN `run_pipeline(config_path)` is called with a YAML path, THE `DAG_Executor` SHALL call `load_yaml_with_deprecation(config_path)` internally.

---

### Requirement 4.3 — Migration Utility: CLI Command

**User Story:** As a pipeline author, I want a CLI command that converts my existing YAML pipeline config to an IR JSON file, so that I can migrate to the canonical format without writing code.

#### Acceptance Criteria

1. THE CLI SHALL expose a new `migrate` subcommand with the signature: `audiobuilder migrate --config <yaml_path> [--output <json_path>]`.
2. THE `--config` argument SHALL be required and SHALL specify the path to the YAML pipeline config file to convert.
3. THE `--output` argument SHALL be optional. WHEN omitted, THE CLI SHALL write the IR JSON to the same directory as the input file, replacing the `.yaml` extension with `.graph.json`.
4. WHEN `audiobuilder migrate` is called with a valid YAML file, THE CLI SHALL write a valid IR JSON file and print a success message: `"✓ Migrated <yaml_path> → <json_path>"`.
5. WHEN `audiobuilder migrate` is called with a file that does not exist, THE CLI SHALL print an error message and exit with code 1.
6. WHEN `audiobuilder migrate` is called with a file that contains invalid YAML, THE CLI SHALL print a parse error message and exit with code 1.
7. THE `migrate` command SHALL NOT emit a `DeprecationWarning` (it is the migration tool itself).

---

### Requirement 4.4 — Migration Utility: Programmatic API

**User Story:** As a Python developer, I want a programmatic migration function, so that I can convert YAML configs to IR JSON from within my own scripts.

#### Acceptance Criteria

1. THE `Migration_Utility` SHALL provide a function `migrate_yaml_to_ir_file(yaml_path: str, output_path: str | None = None) -> str` in `app/core/ir/migrate.py`.
2. THE function SHALL return the path of the written IR JSON file.
3. WHEN `output_path` is `None`, THE function SHALL derive the output path by replacing the `.yaml` or `.yml` extension with `.graph.json`.
4. THE function SHALL call `yaml_config_to_ir` to perform the conversion and `IR_Loader.dump_ir_to_file` to write the output.
5. THE function SHALL NOT emit a `DeprecationWarning`.

---

### Requirement 4.5 — CLI: `run` Command Updated

**User Story:** As a CLI user, I want to run a pipeline from either a YAML config (deprecated) or an IR JSON file (canonical), so that I can use both formats during the migration period.

#### Acceptance Criteria

1. THE CLI `run` command SHALL accept a new `--graph` argument specifying the path to an IR JSON file.
2. THE CLI `run` command SHALL retain the existing `--config` argument for YAML files (deprecated path).
3. WHEN `--graph` is provided, THE CLI SHALL load the IR JSON via `IR_Loader.load_ir_from_file` and execute via `run_pipeline_ir`.
4. WHEN `--config` is provided, THE CLI SHALL load the YAML via `load_yaml_with_deprecation` and execute via `run_pipeline_ir`.
5. WHEN both `--graph` and `--config` are provided, THE CLI SHALL print an error message `"Error: --graph and --config are mutually exclusive"` and exit with code 1.
6. WHEN neither `--graph` nor `--config` is provided, THE CLI SHALL print a usage error and exit with code 1.
7. THE `--seed` override argument SHALL continue to work with both `--graph` and `--config` inputs, overriding `IRMetadata.seed` in the loaded `GraphIR`.

---

### Requirement 4.6 — CLI: `validate` Command Updated

**User Story:** As a CLI user, I want to validate both IR JSON files and YAML configs, so that I can check graph correctness regardless of format.

#### Acceptance Criteria

1. THE CLI `validate` command SHALL accept a new `--graph` argument specifying the path to an IR JSON file.
2. THE CLI `validate` command SHALL retain the existing `--config` argument for YAML files.
3. WHEN `--graph` is provided, THE CLI SHALL load and validate the IR JSON, printing `"✓ Valid IR graph — <N> node(s)"` on success.
4. WHEN `--config` is provided, THE CLI SHALL load the YAML via the shim and validate the resulting `GraphIR`, printing `"✓ Valid pipeline — <N> node(s)"` on success (existing behavior preserved).
5. WHEN validation fails for either format, THE CLI SHALL print the validation error and exit with code 1.
6. WHEN `--graph` is provided and the IR JSON has an incompatible schema version, THE CLI SHALL print the `IRVersionError` message and exit with code 1.

---

### Requirement 4.7 — REST API: Pipeline Execution Endpoint Updated

**User Story:** As an API consumer, I want to submit a pipeline as IR JSON to the execution endpoint, so that I can use the canonical format over HTTP.

#### Acceptance Criteria

1. THE `/api/v1/pipelines/run` endpoint SHALL accept an IR JSON body (a `GraphIR`-compatible JSON object) as the primary input format.
2. THE `/api/v1/pipelines/run` endpoint SHALL continue to accept a YAML-format body for backward compatibility, routing it through the `YAML_Shim`.
3. WHEN an IR JSON body is submitted, THE endpoint SHALL execute via `run_pipeline_ir` and return the existing response schema.
4. WHEN a YAML-format body is submitted, THE endpoint SHALL convert via `yaml_config_to_ir` and execute via `run_pipeline_ir`, and SHALL include a `"X-Deprecation-Warning"` response header with the message `"YAML pipeline input is deprecated. Use IR JSON format."`.
5. THE endpoint SHALL distinguish IR JSON from YAML input by the presence of a `schema_version` field in the request body.

---

### Requirement 4.8 — REST API: Pipeline Validation Endpoint Updated

**User Story:** As an API consumer, I want to validate a pipeline as IR JSON via the REST API, so that I can check graph correctness before submitting for execution.

#### Acceptance Criteria

1. THE `/api/v1/pipelines/validate` endpoint SHALL accept an IR JSON body as the primary input format.
2. THE `/api/v1/pipelines/validate` endpoint SHALL continue to accept a YAML-format body for backward compatibility.
3. WHEN an IR JSON body is submitted and validation succeeds, THE endpoint SHALL return a response including `{"valid": true, "node_count": <N>}`.
4. WHEN an IR JSON body is submitted and validation fails, THE endpoint SHALL return HTTP 422 with a response body describing the validation error.
5. WHEN a YAML-format body is submitted, THE endpoint SHALL include a `"X-Deprecation-Warning"` response header.

---

### Requirement 4.9 — Existing YAML Examples Preserved

**User Story:** As a platform user, I want the existing example YAML pipeline files to continue working, so that the examples in the repository remain functional during the migration period.

#### Acceptance Criteria

1. THE existing YAML pipeline files in `examples/` SHALL continue to execute successfully via `audiobuilder run --config <path>`.
2. THE `DeprecationWarning` emitted when running YAML examples SHALL not cause test failures (warnings must not be treated as errors in the test suite for this warning category).
3. THE existing SDK example scripts (`run_sdk.py` in `examples/`) SHALL continue to work without modification.
