---
inclusion: fileMatch
fileMatchPattern: "app/**/*.py"
---

# File-Header Contracts

Every non-trivial Python file in `app/` must have a complete architectural
contract as its **module docstring — the very first statement in the file**.

This rule applies when you **create** a new file or **modify** an existing one.
Run the verification command at the end of every session.

---

## Required Format

```python
# app/path/to/file.py
"""
Bounded Context:  <BC name — e.g. "BC2 — Node Contract">
Responsibility:   <one sentence: what this file is for>
Owns:             <classes, functions, constants defined here>
Public Surface:   <what callers import from this file>
Must NOT:         <hard constraints — what this file must never do or import>
Dependencies:     <direct imports this file relies on>
Reason To Change: <the single reason this file should ever be modified>
"""
from __future__ import annotations   # ← AFTER the docstring, never before
```

All 7 fields are required. No field may be omitted or left blank.

---

## Placement Rule

The docstring must be the **first statement** in the file.
`from __future__ import annotations` goes **after** the docstring.

```python
# ✅ CORRECT
# app/core/mymodule.py
"""
Bounded Context:  ...
...
"""
from __future__ import annotations

# ❌ WRONG — ast.get_docstring() returns None; contract is invisible to tooling
from __future__ import annotations
"""
Bounded Context:  ...
"""
```

The optional `# app/path/to/file.py` comment line before the opening `"""`
is conventional and helps editors navigate quickly — include it.

---

## Exempt Files

Only these are exempt — no contract required:

| Pattern | Reason |
|---|---|
| Completely empty `__init__.py` | Package marker only — no logic |
| `__init__.py` with a single comment line | Package marker only |
| `__main__.py` entry points ≤ 5 lines | Trivial dispatch only |

Current exempt files in this codebase:
- `app/__init__.py`
- `app/api/routers/__init__.py`
- `app/cli/__init__.py`
- `app/domain/__init__.py`
- `app/mcp/__init__.py`
- `app/mcp/__main__.py`

Any `__init__.py` that contains real logic (re-exports, startup code, lazy
imports) is **not** exempt and must have a full contract.

---

## Bounded Context Reference

Use these BC names consistently in the `Bounded Context:` field:

| BC | Name | Key files |
|---|---|---|
| BC1 | Graph Language | `app/core/ir/` |
| BC2 | Node Contract | `app/core/nodes/base.py`, `ports.py`, `config.py`, `retry.py`, `metadata.py` |
| BC3 | Node Catalog | `app/core/nodes/registry.py`, `discovery.py`, `app/core/plugins/` |
| BC4 | Execution Planner | `app/core/planner.py` |
| BC5 | Execution Runtime | `app/core/orchestrator.py`, `node_executor.py`, `executor.py`, `conditions.py`, `events.py`, `pipeline.py` (shim) |
| BC6 | Observability & Storage | `app/core/checkpoint.py`, `artifact_store.py`, `run_journal.py`, `run_control.py`, `provenance.py`, `pipeline_cache.py`, `logger.py` |
| — | Platform Infrastructure | `app/core/config.py`, `app/core/utils/`, `app/core/validation.py`, `app/core/runtime_backend.py` |
| — | REST API Layer | `app/api/` |
| — | CLI Interface | `app/cli/` |
| — | MCP Server | `app/mcp/` |
| — | Domain — Audio Data Types | `app/models/audio_sample.py`, `audio_artifact_serializer.py` |
| — | Domain — Data Types | `app/models/` (non-audio) |
| — | Domain — Data Ingestion | `app/domain/ingestion.py` |
| — | Domain — Project Management | `app/domain/project_manager.py` |
| — | Domain — Data Quality | `app/domain/quality_checker.py` |

---

## Verification Command

Run this from the workspace root at the end of every session:

```bash
python3 -c "
import os, ast
app_root = 'app'
FIELDS = {
    'Bounded Context', 'Responsibility', 'Owns',
    'Public Surface', 'Must NOT', 'Dependencies', 'Reason To Change'
}
TRIVIAL = {
    'app/__init__.py', 'app/api/routers/__init__.py', 'app/cli/__init__.py',
    'app/domain/__init__.py', 'app/mcp/__init__.py', 'app/mcp/__main__.py'
}
bad = []
for dp, dns, fns in os.walk(app_root):
    dns.sort()
    for fn in sorted(fns):
        if not fn.endswith('.py'):
            continue
        rel = os.path.relpath(os.path.join(dp, fn))
        if rel in TRIVIAL:
            continue
        src = open(rel, encoding='utf-8').read()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            bad.append(f'SYNTAX  {rel}: {e}')
            continue
        doc = ast.get_docstring(tree) or ''
        missing = sorted(f for f in FIELDS if f not in doc)
        if missing:
            bad.append(f'MISSING {rel}: {missing}')
if bad:
    print(f'{len(bad)} violation(s):')
    for b in bad:
        print(f'  {b}')
else:
    print(f'All files compliant.')
"
```

Expected output: `All files compliant.`

Any violation must be fixed before the session is considered complete.

---

## Common Mistakes

**`Must NOT` field too vague** — be specific about which imports or patterns are forbidden:
```
# ❌ Too vague
Must NOT: Do bad things.

# ✅ Specific
Must NOT: Import from app.domain, app.api, or app.models at module level.
          Must not contain domain-specific serialization logic.
```

**`Responsibility` field too long** — one sentence only. If you need more, the file has too many responsibilities (RULE 2 violation):
```
# ❌ Too long — file probably needs splitting
Responsibility: Parse manifests, check compat, install deps, load entry points,
                register nodes, and manage the plugin lifecycle.

# ✅ One sentence
Responsibility: Validate and load a manifest-based plugin into the NodeRegistry.
```

**`Owns` vs `Public Surface` confusion**:
- `Owns` = what this file *defines* (classes, functions, constants)
- `Public Surface` = what *callers import* from this file (may be a subset of Owns)

**Docstring after `from __future__`** — always move the docstring above it.
