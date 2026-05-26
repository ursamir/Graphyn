# Group Review Index — 1: IR Core

**Files reviewed:** 4  
**Total findings:** 16 (CRITICAL: 1 | HIGH: 5 | MEDIUM: 7 | LOW: 3)  
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| models.md | MEDIUM | 3 | `IRNode._deep_copy_config` wraps config in a shallow `MappingProxyType` — nested dicts remain mutable, silently violating the P-23 immutability guarantee. |
| loader.md | MEDIUM | 1 | `dump_ir_to_file` performs a non-atomic write — a disk-full or serialization error mid-write leaves the output file truncated and corrupt, destroying the original content. |
| yaml_shim.md | HIGH | 2 | `yaml_config_to_ir` silently converts any non-`pipeline`-keyed YAML dict (including wrong files) into a valid empty GraphIR with no error or warning, masking configuration errors entirely. |
| migrate.md | MEDIUM | 1 | An empty YAML file passed to `migrate_yaml_to_ir_file` produces an `AttributeError` with no context, and a disk-full condition during write leaves a corrupt output file on disk with no cleanup. |

---

## Priority Findings (CRITICAL and HIGH only)

`[CRITICAL]` yaml_shim.md — `yaml_config_to_ir` — Missing `type` key in any YAML node entry raises bare `KeyError` with no context about which node or file is malformed.

`[HIGH]` yaml_shim.md — `yaml_config_to_ir` — Any YAML file without a top-level `pipeline` key (wrong file, empty file) is silently converted to a valid empty GraphIR with no error or warning.

`[HIGH]` yaml_shim.md — `yaml_config_to_ir` — Explicit-edge list format `{"from": [...], "to": [...]}` with fewer than 2 elements raises bare `IndexError` with no context about which edge is malformed.

`[HIGH]` models.md — `IRNode._deep_copy_config` — `MappingProxyType` is shallow; nested dicts inside `config` remain mutable, silently violating the P-23 immutability guarantee.

`[HIGH]` loader.md — `load_ir` — `load_ir(None)` or `load_ir([])` raises undocumented `pydantic.ValidationError`; callers (e.g. from `yaml.safe_load` on empty file) have no way to distinguish wrong-type from missing-field errors.

`[HIGH]` loader.md — `dump_ir_to_file` — Non-atomic write: a disk-full or mid-write error leaves the output file truncated and corrupt, destroying the original content with no recovery path.

`[HIGH]` migrate.md — `migrate_yaml_to_ir_file` — Inherits non-atomic write risk from `dump_ir_to_file`; additionally, an empty YAML file produces an `AttributeError` with no context.

---

## Most Dangerous File

yaml_shim.md — Contains 3 HIGH/CRITICAL findings, two of which are silent failures: a wrong or empty YAML file produces a valid empty GraphIR with no error, and a missing `type` field produces a bare `KeyError`. These are the most likely real-world failure modes for the migration path.
