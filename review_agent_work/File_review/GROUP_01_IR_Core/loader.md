# Functional Review — app/core/ir/loader.py

**Group:** 1 — IR Core  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/ir/loader.py
FUNCTION:    load_ir
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate and return a GraphIR from a JSON-compatible dict. Raises `pydantic.ValidationError` on schema failure and `IRVersionError` on major version mismatch.

WHAT IT ACTUALLY DOES:
Calls `GraphIR.model_validate(data)` first, then `_check_version(graph.schema_version)`. If `data` is not a dict (e.g. `None`, a list, an int), `model_validate` will raise a `pydantic.ValidationError`. However, if `data` is a dict but missing the `schema_version` key entirely, `model_validate` raises `pydantic.ValidationError` with a message about a missing required field — which is correct. The ordering issue is that version checking happens AFTER full model validation. This means a document with a completely wrong major version (e.g. `"99.0"`) will first be fully validated by Pydantic (potentially succeeding if all other fields are present), and only then have its version rejected. This is acceptable behavior, but the docstring implies version is checked as part of validation — the ordering is misleading.

THE BUG / RISK:
More critically: if `data` is `None` or not a dict, `model_validate` raises `pydantic.ValidationError` — but the docstring does not document this case. Callers who pass `None` (e.g. from `yaml.safe_load` on an empty file) will get an undocumented exception type.

EVIDENCE:
```python
# ~lines 113-120
def load_ir(data: dict[str, Any]) -> GraphIR:
    graph = GraphIR.model_validate(data)
    _check_version(graph.schema_version)
    return graph
```
No guard for `data is None` or `not isinstance(data, dict)`.

REPRODUCTION SCENARIO:
```python
load_ir(None)
# Raises pydantic.ValidationError — not documented
load_ir([])
# Raises pydantic.ValidationError — not documented
```

IMPACT:
Callers (e.g. `load_yaml_with_deprecation`) that pass the result of `yaml.safe_load` on an empty or non-dict YAML file will get an undocumented exception. The caller has no way to distinguish "wrong type" from "missing required field" without inspecting the ValidationError detail.

FIX DIRECTION:
Add an explicit type guard at the top of `load_ir`:
```python
if not isinstance(data, dict):
    raise TypeError(f"load_ir expects a dict, got {type(data).__name__}")
```

--------------------------------------------------------------------
FILE:        app/core/ir/loader.py
FUNCTION:    load_ir_from_file
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Read a JSON file and return a validated GraphIR. Documents raised exceptions: `FileNotFoundError`, `json.JSONDecodeError`, `pydantic.ValidationError`, `IRVersionError`.

WHAT IT ACTUALLY DOES:
Opens the file with `p.open("r", encoding="utf-8")` and calls `json.load(f)`. This correctly raises `json.JSONDecodeError` on invalid JSON. However, it does not handle `PermissionError` (file exists but is not readable), `OSError` (disk error), or `UnicodeDecodeError` (file is not valid UTF-8). These are all plausible failure modes for a file-reading function.

THE BUG / RISK:
`PermissionError` and `UnicodeDecodeError` will propagate as undocumented exceptions. A caller that catches only the documented exceptions will miss these cases.

EVIDENCE:
```python
# ~lines 148-158
with p.open("r", encoding="utf-8") as f:
    data = json.load(f)
```
No handling for `PermissionError`, `OSError`, or `UnicodeDecodeError`.

REPRODUCTION SCENARIO:
```python
# File exists but is not readable
import os; os.chmod("graph.json", 0o000)
load_ir_from_file("graph.json")
# Raises PermissionError — not documented
```

IMPACT:
Callers that catch only documented exceptions will see unhandled `PermissionError` or `UnicodeDecodeError` propagate up the stack.

FIX DIRECTION:
Either document these additional exceptions in the docstring, or wrap them:
```python
except (PermissionError, OSError) as exc:
    raise OSError(f"Cannot read IR file '{path}': {exc}") from exc
```

--------------------------------------------------------------------
FILE:        app/core/ir/loader.py
FUNCTION:    dump_ir_to_file
CATEGORY:    Resource Management
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write a GraphIR to a JSON file with 2-space indentation. Parent directories must exist.

WHAT IT ACTUALLY DOES:
Opens the file for writing and calls `json.dump`. If `json.dump` raises (e.g. due to a non-serializable value in the graph — which should not happen with `model_dump(mode="json")` but could if `dump_ir` is bypassed), the file will be left in a partially written, truncated state. The `with` block ensures the file handle is closed, but the file content will be corrupt.

THE BUG / RISK:
If `json.dump` raises mid-write (e.g. disk full, or a serialization error), the output file is left truncated and corrupt. There is no atomic write (write-to-temp then rename). A subsequent `load_ir_from_file` on the same path will fail with `json.JSONDecodeError`.

EVIDENCE:
```python
# ~lines 175-180
with p.open("w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
```
No atomic write pattern.

REPRODUCTION SCENARIO:
Simulate disk-full mid-write: the file is opened and truncated (mode "w"), then `json.dump` raises `OSError: [Errno 28] No space left on device` after writing partial content. The file now contains partial JSON.

IMPACT:
Data loss — the original file is destroyed and the new file is corrupt. Any subsequent load will fail.

FIX DIRECTION:
Use an atomic write pattern:
```python
import tempfile, os
tmp = p.with_suffix(".tmp")
with tmp.open("w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
os.replace(tmp, p)
```

--------------------------------------------------------------------
FILE:        app/core/ir/loader.py
FUNCTION:    dump_ir_to_file
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write a GraphIR to a JSON file. "Parent directories must exist."

WHAT IT ACTUALLY DOES:
If the parent directory does not exist, `p.open("w")` raises `FileNotFoundError`. The docstring documents this as a precondition ("Parent directories must exist") but does not raise a clear error — the raw `FileNotFoundError` from the OS will surface with a message like "No such file or directory", which may be confusing since the file itself is being created.

THE BUG / RISK:
The error message from the OS does not distinguish "parent dir missing" from "file not found". Callers may be confused.

EVIDENCE:
```python
# ~line 175
with p.open("w", encoding="utf-8") as f:
```
No `p.parent.mkdir(parents=True, exist_ok=True)` call.

REPRODUCTION SCENARIO:
```python
dump_ir_to_file(graph, "/nonexistent/dir/out.json")
# FileNotFoundError: [Errno 2] No such file or directory: '/nonexistent/dir/out.json'
```

IMPACT:
Confusing error message; caller must know to create parent dirs.

FIX DIRECTION:
Either auto-create parent dirs (`p.parent.mkdir(parents=True, exist_ok=True)`) or improve the error message with an explicit check.

--------------------------------------------------------------------
FILE:        app/core/ir/loader.py
FUNCTION:    _check_version
CATEGORY:    Silent Failure
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate schema_version against CURRENT_IR_VERSION. Emits UserWarning if minor version is greater than SUPPORTED_MINOR_MAX.

WHAT IT ACTUALLY DOES:
Emits a `UserWarning` for future minor versions. However, `warnings.warn` with `UserWarning` is silenced by default in many production environments (Python's default warning filter suppresses duplicate warnings after the first occurrence). If the same future-version document is loaded multiple times in the same process, only the first call emits the warning — all subsequent calls are silent.

THE BUG / RISK:
In a long-running server process, the first load of a future-minor-version document emits the warning; all subsequent loads are silent. Operators monitoring logs for this warning will miss repeated occurrences.

EVIDENCE:
```python
# ~lines 91-98
warnings.warn(
    f"IR document schema_version '{schema_version}' ...",
    UserWarning,
    stacklevel=3,
)
```
Python's default warning filter deduplicates `UserWarning` by (message, category, module, lineno).

REPRODUCTION SCENARIO:
Load a `"1.2"` document twice in the same process — only the first call logs the warning.

IMPACT:
Operators may miss repeated use of unsupported IR versions in production.

FIX DIRECTION:
Use `warnings.warn(..., stacklevel=3)` with `warnings.simplefilter("always")` in the relevant context, or use the platform logger instead of `warnings.warn` for production-visible alerting.

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
| Top Risk | `dump_ir_to_file` performs a non-atomic write — a disk-full or serialization error mid-write leaves the output file truncated and corrupt, destroying the original content. |
