# Functional Review — app/core/ir/migrate.py

**Group:** 1 — IR Core  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/ir/migrate.py
FUNCTION:    migrate_yaml_to_ir_file
CATEGORY:    Resource Management
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Convert a YAML pipeline config file to an IR JSON file. Returns the path of the written IR JSON file.

WHAT IT ACTUALLY DOES:
Reads the YAML file, converts it, and writes the output. If `yaml_config_to_ir(raw)` raises (e.g. due to a malformed YAML structure — missing `type` key, malformed edge, etc.), the function raises before calling `dump_ir_to_file`. This is safe — no partial output file is created.

However, `dump_ir_to_file` itself performs a non-atomic write (see loader.md finding). If the write fails mid-way (disk full), the output file is left corrupt. Since `migrate_yaml_to_ir_file` is a CLI-facing migration tool, users may not notice the corrupt output and proceed with a broken `.graph.json` file.

THE BUG / RISK:
The migration tool inherits the non-atomic write risk from `dump_ir_to_file`. A disk-full condition during migration leaves a corrupt `.graph.json` file at the output path. The function returns the output path, implying success, but the file is unreadable.

EVIDENCE:
```python
# ~line 52
dump_ir_to_file(graph, output_path)
return output_path
```
`dump_ir_to_file` raises on disk-full, so `return output_path` is not reached — but the file is already truncated/corrupt at that point.

REPRODUCTION SCENARIO:
Simulate disk-full during `dump_ir_to_file` write. The output `.graph.json` file exists but contains partial JSON. The function raises `OSError`, but the corrupt file remains on disk.

IMPACT:
Data loss — the output file is corrupt. User may not notice if they catch the `OSError` and retry, finding a corrupt file at the expected path.

FIX DIRECTION:
This is inherited from `dump_ir_to_file`. Fix the atomic write there (see loader.md). Alternatively, add a try/except in `migrate_yaml_to_ir_file` that deletes the partial output file on failure:
```python
try:
    dump_ir_to_file(graph, output_path)
except Exception:
    Path(output_path).unlink(missing_ok=True)
    raise
```

--------------------------------------------------------------------
FILE:        app/core/ir/migrate.py
FUNCTION:    migrate_yaml_to_ir_file
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Read and convert a YAML file. Raises implicitly on file-not-found or YAML parse errors.

WHAT IT ACTUALLY DOES:
Opens the YAML file with `open(yaml_path, "r", encoding="utf-8")`. If the file does not exist, raises `FileNotFoundError`. If the YAML is syntactically invalid, `yaml.safe_load` raises `yaml.YAMLError`. Neither exception is documented in the docstring. Callers (e.g. the CLI) must know to catch these undocumented exceptions.

THE BUG / RISK:
The docstring documents only the return value and the `output_path` derivation logic. It does not document any raised exceptions. A CLI caller that wraps this function without knowing about `yaml.YAMLError` will let YAML parse errors propagate as unhandled exceptions with a raw traceback.

EVIDENCE:
```python
# ~lines 46-48
with open(yaml_path, "r", encoding="utf-8") as f:
    raw = yaml.safe_load(f)
```
`yaml.YAMLError` is not caught or documented.

REPRODUCTION SCENARIO:
```python
# Create a file with invalid YAML
with open("bad.yaml", "w") as f:
    f.write("pipeline:\n  nodes:\n  - type: [unclosed")
migrate_yaml_to_ir_file("bad.yaml")
# yaml.scanner.ScannerError — not documented
```

IMPACT:
Undocumented exception propagates to CLI with a raw traceback instead of a user-friendly error message.

FIX DIRECTION:
Document the exceptions in the docstring, or catch and re-raise with a user-friendly message:
```python
except yaml.YAMLError as exc:
    raise ValueError(f"Invalid YAML in '{yaml_path}': {exc}") from exc
```

--------------------------------------------------------------------
FILE:        app/core/ir/migrate.py
FUNCTION:    migrate_yaml_to_ir_file
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Derive output path by replacing `.yaml`/`.yml` extension with `.graph.json` when `output_path` is None (Req 4.4.3).

WHAT IT ACTUALLY DOES:
Uses `yaml_p.stem` to get the filename without extension, then constructs `f"{stem}.graph.json"`. For a file named `my.pipeline.yaml`, `yaml_p.stem` is `"my.pipeline"` (removes only the last extension), producing `"my.pipeline.graph.json"` — which is correct. However, for a file with no extension (e.g. `"pipeline"`), `yaml_p.stem` is `"pipeline"` and the output is `"pipeline.graph.json"` — also correct.

The real edge case: if `yaml_path` is a path like `"./pipeline.yaml"` and the current working directory changes between the call and the write, `yaml_p.parent` resolves to `"."` which is the CWD at call time. This is standard Python behavior but worth noting.

More critically: if `output_path` is provided but its parent directory does not exist, `dump_ir_to_file` will raise `FileNotFoundError`. The function does not create parent directories for the provided `output_path`.

THE BUG / RISK:
When `output_path` is explicitly provided with a non-existent parent directory, the function raises `FileNotFoundError` with a message about the output file, not the missing directory. This is confusing for CLI users.

EVIDENCE:
```python
# ~line 52
dump_ir_to_file(graph, output_path)
```
No `Path(output_path).parent.mkdir(parents=True, exist_ok=True)` before the write.

REPRODUCTION SCENARIO:
```python
migrate_yaml_to_ir_file("pipeline.yaml", "/nonexistent/dir/out.graph.json")
# FileNotFoundError: [Errno 2] No such file or directory: '/nonexistent/dir/out.graph.json'
```

IMPACT:
Confusing error for CLI users who specify a new output directory.

FIX DIRECTION:
```python
Path(output_path).parent.mkdir(parents=True, exist_ok=True)
dump_ir_to_file(graph, output_path)
```

--------------------------------------------------------------------
FILE:        app/core/ir/migrate.py
FUNCTION:    migrate_yaml_to_ir_file
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Convert a YAML pipeline config file to an IR JSON file.

WHAT IT ACTUALLY DOES:
Calls `yaml.safe_load(f)` which returns `None` for an empty file. Then calls `yaml_config_to_ir(None)`. As documented in yaml_shim.md, this causes `AttributeError: 'NoneType' object has no attribute 'get'` inside `yaml_config_to_ir`. The error propagates from `migrate_yaml_to_ir_file` as an `AttributeError` with no context about the file path or the cause.

THE BUG / RISK:
An empty YAML file passed to the migration tool produces an `AttributeError` with no useful context. The CLI user sees a raw traceback instead of "the YAML file is empty".

EVIDENCE:
```python
# ~lines 46-50
with open(yaml_path, "r", encoding="utf-8") as f:
    raw = yaml.safe_load(f)
graph = yaml_config_to_ir(raw)  # AttributeError if raw is None
```

REPRODUCTION SCENARIO:
```python
open("empty.yaml", "w").close()
migrate_yaml_to_ir_file("empty.yaml")
# AttributeError: 'NoneType' object has no attribute 'get'
```

IMPACT:
Confusing error for CLI users; root cause (empty file) is not surfaced.

FIX DIRECTION:
Add a None check after `yaml.safe_load`:
```python
if raw is None:
    raise ValueError(f"YAML file '{yaml_path}' is empty or contains only comments.")
```

--------------------------------------------------------------------
FILE:        app/core/ir/migrate.py
FUNCTION:    migrate_yaml_to_ir_file
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
The module docstring states: "Must not emit DeprecationWarning — this is the migration tool itself, not a deprecated call site." (Req 4.4)

WHAT IT ACTUALLY DOES:
Calls `yaml_config_to_ir(raw)` directly (not `load_yaml_with_deprecation`), so no `DeprecationWarning` is emitted from this function. This is correct.

However, the module imports `yaml_config_to_ir` inside the function body (lazy import), which means import errors for `yaml` or `app.core.ir.yaml_shim` will surface as `ImportError` at call time rather than at module import time. This is an unusual pattern that makes the module's dependencies invisible to static analysis tools.

THE BUG / RISK:
If `yaml` is not installed, the `ImportError` surfaces at call time with a traceback pointing into the function body, not at module import time. This makes dependency checking harder.

EVIDENCE:
```python
# ~lines 43-45
import yaml
from app.core.ir.yaml_shim import yaml_config_to_ir
from app.core.ir.loader import dump_ir_to_file
```
These are inside the function body, not at module level.

REPRODUCTION SCENARIO:
`import app.core.ir.migrate` succeeds even if `yaml` is not installed. `migrate_yaml_to_ir_file(...)` then raises `ImportError`.

IMPACT:
Dependency errors surface late (at call time) rather than early (at import time). Low severity since `yaml` is a standard dependency.

FIX DIRECTION:
Move imports to module level. The module docstring already lists `yaml` as a dependency.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | NO |
| Top Risk | An empty YAML file passed to `migrate_yaml_to_ir_file` produces an `AttributeError` with no context, and a disk-full condition during write leaves a corrupt output file on disk with no cleanup. |
