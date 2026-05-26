# Group Review Index — 3: Registry & Discovery

**Files reviewed:** 4  
**Total findings:** 16 (CRITICAL: 0 | HIGH: 4 | MEDIUM: 8 | LOW: 4)  
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| registry.md | MEDIUM | 1 | `list_nodes()` returns live `NodeMetadata` references — caller mutation silently corrupts the registry for all subsequent callers. |
| discovery.md | HIGH | 3 | `_import_file` writes a broken module stub to `sys.modules` before `exec_module` completes — a plugin with a syntax error permanently poisons `sys.modules` for that module name, preventing recovery in the same process. |
| catalogue.md | MEDIUM | 1 | `NodeRegistry.register()` bypasses `TypeCatalogue` — port types for directly-registered nodes are absent from the catalogue, causing `PortTypeNotFoundError` at pipeline build time with no actionable diagnosis. |
| registry_runtime.md | HIGH | 2 | `resolve_capability` uses a bare `except Exception` that swallows `AttributeError` on `None` input and returns default capability metadata silently — GPU nodes may be scheduled on CPU-only workers with no error or warning. |

---

## Priority Findings (CRITICAL and HIGH only)

`[HIGH] discovery.md — AutoDiscovery._import_file — Broken module stub written to sys.modules before exec_module completes; syntax-error plugin permanently poisons sys.modules for the process lifetime.`

`[HIGH] discovery.md — AutoDiscovery._import_file — Module name collision: two plugins in different directories with the same subdirectory name produce identical sys.modules keys; second plugin silently returns first plugin's classes.`

`[HIGH] registry_runtime.md — get_registry — Function claims to return "fully-populated" registry but has no guard against being called before AutoDiscovery.run(); returns empty registry silently.`

`[HIGH] registry_runtime.md — resolve_capability — Bare except Exception swallows AttributeError on None/malformed ir_node input and returns default IRCapabilityMetadata silently; GPU nodes may be mis-scheduled with no error.`

---

## Most Dangerous File

`discovery.md` — Two independent HIGH-severity silent failures in `_import_file` (sys.modules poisoning + module name collision) mean that plugin load errors are unrecoverable within a process and wrong node classes can be silently registered, with no exception raised to the operator.
