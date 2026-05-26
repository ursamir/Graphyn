# Functional Review — app/core/nodes/metadata.py

**Group:** 2 — Node Base
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/nodes/metadata.py
FUNCTION:    NodeMetadata._version_format
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate that `version` is a semver-like string (e.g. `'1.0.0'`, `'2.1'`,
`'1.0.0-beta'`).

WHAT IT ACTUALLY DOES:
Uses the regex `r"^\d+(\.\d+)*([.\-+][a-zA-Z0-9._\-+]*)?$"`. This regex
accepts strings like `"1"` (single digit, no dots), `"1.0.0-"` (trailing
hyphen with no suffix), and `"1..0"` (double dot — actually rejected because
`\.\d+` requires at least one digit after the dot, so `"1..0"` is rejected).

However, `"1"` is accepted as a valid version. The docstring example shows
`'2.1'` as valid, implying at least two components. A single-digit version
like `"1"` may be unintentional.

More importantly, the regex allows `"1.0.0-"` (trailing hyphen) because the
optional group `([.\-+][a-zA-Z0-9._\-+]*)?` matches `"-"` followed by zero
or more characters — the `*` allows zero characters after the separator.

THE BUG / RISK:
`"1.0.0-"` passes validation and is stored as a version string. Downstream
consumers that parse the version (e.g. semver comparison) may fail or produce
incorrect results.

EVIDENCE:
Lines 79-84:
```python
if not re.match(r"^\d+(\.\d+)*([.\-+][a-zA-Z0-9._\-+]*)?$", v):
    raise ValueError(...)
```

REPRODUCTION SCENARIO:
```python
m = NodeMetadata(node_type="x", label="x", description="x",
                 category="x", version="1.0.0-")
# Passes validation; version="1.0.0-" stored
```

IMPACT:
Invalid version string stored silently. Low severity — only affects downstream
version parsing.

FIX DIRECTION:
Tighten the regex to require at least one character after the separator:
```python
r"^\d+(\.\d+)*([.\-+][a-zA-Z0-9._\-+]+)?$"
#                                       ^ + instead of *
```

--------------------------------------------------------------------
FILE:        app/core/nodes/metadata.py
FUNCTION:    NodeMetadata (model)
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Describe a node's identity, ports, and display properties. `tags` defaults
to `[]` and `dependency_requirements` defaults to `[]`.

WHAT IT ACTUALLY DOES:
Both `tags: list[str] = []` and `dependency_requirements: list[str] = []`
use mutable default values. In Pydantic v2, mutable defaults in `BaseModel`
fields are handled correctly (each instance gets its own copy), so this is
not a Python mutable-default-argument bug. However, it is worth confirming
that Pydantic v2 is in use — if Pydantic v1 is used, these would be shared
across instances.

THE BUG / RISK:
If Pydantic v1 is used (unlikely given `ConfigDict` usage, but possible in
a mixed environment), `tags` and `dependency_requirements` would be shared
mutable lists across all `NodeMetadata` instances. Appending to one instance's
`tags` would affect all instances.

EVIDENCE:
Lines 38-39, 72:
```python
tags: list[str] = []
dependency_requirements: list[str] = []
```

REPRODUCTION SCENARIO:
Only a risk under Pydantic v1. Under Pydantic v2, this is safe.

IMPACT:
Low — Pydantic v2 handles this correctly. Only a risk if the environment
downgrades to Pydantic v1.

FIX DIRECTION:
Use `default_factory` for clarity and forward-compatibility:
```python
from pydantic import Field
tags: list[str] = Field(default_factory=list)
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | LOW |
| Silent Failures | 1 |
| Error Handling | COMPLETE |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | Version regex accepts trailing-separator strings like "1.0.0-" which may break downstream version parsers. |
