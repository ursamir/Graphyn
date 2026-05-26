# Functional Review — app/core/nodes/errors.py

**Group:** 2 — Node Base
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/nodes/errors.py
FUNCTION:    module-level import (ResumeError re-export)
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Re-export `ResumeError` from `app.core.errors` for backward compatibility,
so existing imports of `from app.core.nodes.errors import ResumeError`
continue to work.

WHAT IT ACTUALLY DOES:
Imports `from app.core.errors import ResumeError` at module level (line ~50).
This creates a hard import-time dependency from `app.core.nodes.errors`
(BC2 — Node Contract) on `app.core.errors` (BC6 — Platform Infrastructure).

The file header contract states:
```
Must NOT: Import from any other app module. Pure stdlib only.
```
This import violates the stated `Must NOT` constraint. If `app.core.errors`
fails to import (e.g. due to a circular import, missing dependency, or
syntax error in that module), `app.core.nodes.errors` also fails to import.
Since `app.core.nodes.errors` is imported by `app.core.nodes.base`, which
is imported by virtually every node, a failure in `app.core.errors` would
cascade and prevent the entire node system from loading.

THE BUG / RISK:
Import-time circular dependency risk. `app.core.errors` may import from
`app.core.nodes.errors` (or a module that does), creating a circular import.
Even without a cycle, the `Must NOT` contract is violated, making the
bounded context boundary leaky.

EVIDENCE:
Lines ~50-54 (bottom of file):
```python
from app.core.errors import ResumeError  # noqa: E402, F401
```
File header: `Must NOT: Import from any other app module. Pure stdlib only.`

REPRODUCTION SCENARIO:
If `app.core.errors` has a bug or circular import, importing
`app.core.nodes.errors` raises `ImportError`, which cascades to
`app.core.nodes.base` and then to every node in the system.

IMPACT:
Cascade import failure — the entire node system fails to load if
`app.core.errors` has any import-time issue.

FIX DIRECTION:
Move the re-export to a lazy import to break the hard dependency:
```python
def __getattr__(name):
    if name == "ResumeError":
        from app.core.errors import ResumeError
        return ResumeError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```
Or remove the re-export entirely and update the one or two call sites that
use `from app.core.nodes.errors import ResumeError`.

--------------------------------------------------------------------
FILE:        app/core/nodes/errors.py
FUNCTION:    module (exception hierarchy)
CATEGORY:    Testability
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Define the exception hierarchy for the node system.

WHAT IT ACTUALLY DOES:
All exception classes are bare subclasses with no `__init__` override and
no structured fields (e.g. `node_type`, `port_name`). Callers must embed
all context in the message string. This makes it impossible to
programmatically inspect the error (e.g. "which node type caused the
`NodeNotFoundError`?") without parsing the message string.

THE BUG / RISK:
Not a functional bug, but a testability and usability gap. Tests that
check for specific error conditions must parse message strings, which is
fragile. Monitoring systems cannot extract structured fields from exceptions.

EVIDENCE:
Lines 18-42 — all exception classes are `pass` bodies.

REPRODUCTION SCENARIO:
```python
try:
    registry.get("missing_node")
except NodeNotFoundError as e:
    node_type = e.node_type  # AttributeError — no such field
```

IMPACT:
Low — no functional bug, but poor testability and observability.

FIX DIRECTION:
Add structured fields to key exceptions:
```python
class NodeNotFoundError(NodeSystemError):
    def __init__(self, node_type: str):
        self.node_type = node_type
        super().__init__(f"Node type not found: {node_type!r}")
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 0 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | The `ResumeError` re-export violates the `Must NOT` contract and creates a hard import-time dependency on `app.core.errors`, risking cascade import failure across the entire node system. |
