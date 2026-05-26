# Functional Review — app/core/plugins/manifest.py

**Group:** 4 — Plugin Ecosystem  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/plugins/manifest.py
FUNCTION:    load_manifest
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Parse and validate the manifest file inside *plugin_dir*. Tries `plugin.toml` first; falls back to `plugin.json`.

WHAT IT ACTUALLY DOES:
```python
if toml_path.exists():
    data = _load_toml(toml_path)
elif json_path.exists():
    data = _load_json(json_path)
else:
    raise PluginManifestError(...)

return _parse_manifest_dict(data, source=str(toml_path if toml_path.exists() else json_path))
```

The `source` argument to `_parse_manifest_dict` re-evaluates `toml_path.exists()` at the time of the call. If `plugin.toml` was deleted between the first `toml_path.exists()` check (which returned `True`) and the `_parse_manifest_dict` call, `toml_path.exists()` now returns `False`, so `source` is set to `json_path` even though `data` was loaded from `toml_path`. This is a TOCTOU (time-of-check/time-of-use) issue that produces a misleading error message if validation fails.

THE BUG / RISK:
If `plugin.toml` is deleted between the `exists()` check and the `_parse_manifest_dict` call, validation error messages will reference `plugin.json` as the source even though the data came from `plugin.toml`. This is a minor diagnostic confusion, not a data corruption issue.

EVIDENCE:
```python
data = _load_toml(toml_path)   # data loaded from toml_path
# ... toml_path deleted here by another process ...
return _parse_manifest_dict(data, source=str(toml_path if toml_path.exists() else json_path))
#                                         ^^^ re-evaluates exists() — now False
#                                         source = json_path (wrong)
```

REPRODUCTION SCENARIO:
Plugin directory is on a network filesystem. `plugin.toml` is loaded successfully, then deleted by another process. Validation fails. Error message says "Manifest validation failed for 'plugin.json'" even though the data came from `plugin.toml`.

IMPACT:
Misleading error message. No data corruption.

FIX DIRECTION:
Capture the source path before loading:
```python
if toml_path.exists():
    source_path = toml_path
    data = _load_toml(toml_path)
elif json_path.exists():
    source_path = json_path
    data = _load_json(json_path)
else:
    raise PluginManifestError(...)
return _parse_manifest_dict(data, source=str(source_path))
```

--------------------------------------------------------------------
FILE:        app/core/plugins/manifest.py
FUNCTION:    PluginManifest.__init__
CATEGORY:    Contract Mismatch
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Wrap Pydantic `ValidationError` → `PluginManifestError` on direct construction (`PluginManifest(**data)`).

WHAT IT ACTUALLY DOES:
```python
def __init__(self, **data: Any) -> None:
    try:
        super().__init__(**data)
    except Exception as exc:
        _rewrap_validation_error(exc, source="<direct construction>")
```

`_rewrap_validation_error` always raises — it never returns. However, the `__init__` method has no `return` statement after the `except` block, and the `try` block's `super().__init__(**data)` can succeed (no exception). In that case, `__init__` returns normally. This is correct.

The issue is that `_rewrap_validation_error` is called with `source="<direct construction>"` for all direct construction failures. This means that `PluginRecord.load_manifest()` (which calls `PluginManifest.model_validate(self.manifest)`) will NOT go through this `__init__` override — `model_validate` bypasses `__init__` in Pydantic v2. So the `__init__` override only catches errors from `PluginManifest(**data)` calls, not from `PluginManifest.model_validate(data)` calls.

THE BUG / RISK:
`PluginManifest.model_validate(data)` (used in `_parse_manifest_dict` and `PluginRecord.load_manifest()`) raises raw `pydantic.ValidationError`, not `PluginManifestError`. The `__init__` override is ineffective for the primary code path. `_parse_manifest_dict` correctly wraps this via its own try/except, but `PluginRecord.load_manifest()` does not — it calls `PluginManifest.model_validate(self.manifest)` directly and lets `ValidationError` propagate.

EVIDENCE:
```python
# PluginRecord.load_manifest():
return PluginManifest.model_validate(self.manifest)   # ValidationError not wrapped
```
```python
# PluginManifest.__init__ override:
# Only called for PluginManifest(**data), not model_validate()
```

REPRODUCTION SCENARIO:
`record.load_manifest()` is called on a record with a corrupt manifest dict. `model_validate` raises `pydantic.ValidationError`. The caller catches `PluginManifestError` but the actual exception is `ValidationError` — it is not caught.

IMPACT:
Unexpected exception type from `PluginRecord.load_manifest()`. Any caller that catches `PluginManifestError` will miss this error.

FIX DIRECTION:
In `PluginRecord.load_manifest()`, wrap the call:
```python
def load_manifest(self):
    from app.core.plugins.manifest import PluginManifest, _rewrap_validation_error
    try:
        return PluginManifest.model_validate(self.manifest)
    except Exception as exc:
        _rewrap_validation_error(exc, source=f"<stored record for '{self.name}'>")
        raise  # unreachable
```

--------------------------------------------------------------------
FILE:        app/core/plugins/manifest.py
FUNCTION:    _load_toml
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Read and parse a TOML manifest file. Supports both `[plugin]` table and flat top-level keys.

WHAT IT ACTUALLY DOES:
```python
if "plugin" in raw and isinstance(raw["plugin"], dict):
    return raw["plugin"]
return raw
```

If the TOML file has both a `[plugin]` table and top-level keys (e.g. a TOML file that uses `[plugin]` for the manifest but also has other top-level sections like `[build]`), only the `[plugin]` table is returned. This is correct and intentional. However, if the TOML file has a `plugin` key that is NOT a dict (e.g. `plugin = "some-string"`), the condition `isinstance(raw["plugin"], dict)` is False, and the entire raw dict (including the non-dict `plugin` key) is passed to `_parse_manifest_dict`. Pydantic will then try to validate `plugin = "some-string"` as a field, which will fail with a confusing error about an unexpected field rather than a clear "plugin section must be a table" message.

THE BUG / RISK:
A TOML file with `plugin = "some-string"` (scalar, not table) produces a confusing Pydantic validation error instead of a clear "plugin section must be a dict/table" message.

EVIDENCE:
```python
if "plugin" in raw and isinstance(raw["plugin"], dict):
    return raw["plugin"]
return raw   # raw contains plugin="some-string" — confusing validation error
```

REPRODUCTION SCENARIO:
`plugin.toml` contains `plugin = "audio-classifier"` (a string, not a table). `_load_toml` returns the full raw dict. `_parse_manifest_dict` fails with "unexpected field 'plugin'" or similar.

IMPACT:
Confusing error message. No data corruption.

FIX DIRECTION:
```python
if "plugin" in raw:
    if not isinstance(raw["plugin"], dict):
        raise PluginManifestError(
            f"'plugin' key in {path!r} must be a TOML table, not {type(raw['plugin']).__name__}"
        )
    return raw["plugin"]
return raw
```

--------------------------------------------------------------------
FILE:        app/core/plugins/manifest.py
FUNCTION:    PluginManifest._validate_entry_points
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate that each entry point ends with `.py` and uses forward slashes.

WHAT IT ACTUALLY DOES:
Validates that each entry point string ends with `.py` and does not contain backslashes. However, it does not check for path traversal sequences (`..`). An entry point like `"../../evil.py"` would pass validation and be accepted as a valid entry point. `PluginLoader._import_entry_points` then constructs `path = plugin_dir / entry_point`, which resolves to a path outside the plugin directory.

THE BUG / RISK:
A malicious plugin manifest with `entry_points = ["../../app/core/nodes/registry.py"]` would cause `PluginLoader` to import a core platform file as a plugin entry point, potentially re-registering or overwriting node types.

EVIDENCE:
```python
if not item.endswith(".py"):
    raise ValueError(...)
if "\\" in item:
    raise ValueError(...)
# No check for ".." path traversal
```

REPRODUCTION SCENARIO:
Plugin manifest: `entry_points = ["../../app/core/nodes/registry.py"]`. `PluginLoader` constructs `path = plugin_dir / "../../app/core/nodes/registry.py"` which resolves to the platform's registry module. `AutoDiscovery._import_file(path)` imports it again, potentially causing duplicate registrations.

IMPACT:
Path traversal: a plugin can cause arbitrary `.py` files outside its directory to be imported as entry points.

FIX DIRECTION:
```python
if ".." in Path(item).parts:
    raise ValueError(
        f"Entry point {item!r} contains path traversal sequence '..' — not allowed"
    )
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | Entry point path traversal (`..`) not blocked by validator — a malicious plugin can cause platform core files to be imported as entry points |
