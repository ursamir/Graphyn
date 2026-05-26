# Functional Review — app/core/conditions.py

**Group:** 6 — Execution Runtime  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/conditions.py
FUNCTION:    _validate_ast
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Walk the AST and raise `ConditionEvaluationError` for disallowed node types.
Whitelist: comparisons, boolean ops, subscript access on 'output', len() only.

WHAT IT ACTUALLY DOES:
The whitelist includes `ast.Subscript` but does NOT check what is being
subscripted. The rule is "subscript access on 'output'" but the validator
only checks that `ast.Name` nodes have `id == "output"` or `id == "len"`.
A subscript like `output[output["key"]]` (nested subscript) is allowed because
both `Name` nodes are `"output"`. More importantly, `ast.Slice` is not in
`_ALLOWED_NODE_TYPES`, so `output[1:3]` would be rejected — but `ast.Index`
(Python 3.8 compatibility wrapper) is also not in the whitelist, which means
on Python 3.8 `output["key"]` would be rejected because `ast.Index` wraps
the key.

THE BUG / RISK:
On Python 3.8, `ast.parse('output["key"]', mode="eval")` produces an
`ast.Index` node wrapping the `ast.Constant`. `ast.Index` is not in
`_ALLOWED_NODE_TYPES`, so all subscript access would be rejected on Python 3.8
with a confusing "Disallowed expression element 'Index'" error.

EVIDENCE:
```python
_ALLOWED_NODE_TYPES = frozenset({
    ...
    ast.Subscript,
    ast.Constant,
    ast.Load,
    # ast.Index is NOT listed — present in Python 3.8 AST
})
```
In Python 3.8: `ast.parse('output["key"]', mode="eval")` produces
`Subscript(value=Name(id='output'), slice=Index(value=Constant(value='key')))`.
`Index` is not in the whitelist → `ConditionEvaluationError`.

REPRODUCTION SCENARIO:
Run on Python 3.8: `evaluate_condition('output["key"] > 0', {"key": 1})`
→ `ConditionEvaluationError: Disallowed expression element 'Index'`

IMPACT:
All condition expressions fail on Python 3.8. If the platform supports
Python 3.8, this is a complete breakage of conditional edge routing.

FIX DIRECTION:
Add `ast.Index` to `_ALLOWED_NODE_TYPES` (it is a no-op wrapper in 3.8,
removed in 3.9+):
```python
_ALLOWED_NODE_TYPES = frozenset({
    ...
    getattr(ast, "Index", None),   # Python 3.8 compat
} - {None})
```

--------------------------------------------------------------------
FILE:        app/core/conditions.py
FUNCTION:    evaluate_condition
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Evaluate a condition expression against a node's output dict; raises
`ConditionEvaluationError` on syntax errors, disallowed constructs, or
runtime evaluation errors.

WHAT IT ACTUALLY DOES:
The `eval()` call uses `{"__builtins__": {"len": len}}` as the globals dict.
This correctly restricts builtins to only `len`. However, `output` is passed
as a local variable. If `output` is a dict subclass that overrides `__getitem__`
to raise a custom exception (not a `KeyError`), the exception is caught by the
outer `except Exception as exc` and re-raised as `ConditionEvaluationError`.
This is correct behavior.

However, if `output["key"]` raises `KeyError` (key not present), the exception
is also caught and re-raised as `ConditionEvaluationError`. The error message
will be something like "Condition 'output["missing_key"] > 0' raised an error
during evaluation: 'missing_key'". This is technically correct but the error
message is confusing — it looks like a security error rather than a missing key.

THE BUG / RISK:
`KeyError` from a missing output key is reported as a `ConditionEvaluationError`
with a confusing message. The caller cannot distinguish "malformed condition"
from "condition references a key that doesn't exist in the output."

EVIDENCE:
```python
except Exception as exc:
    raise ConditionEvaluationError(
        f"Condition '{expression}' raised an error during evaluation: {exc}"
    ) from exc
```
A `KeyError('missing_key')` produces: "Condition '...' raised an error during
evaluation: 'missing_key'" — the single-quoted key looks like a string literal,
not a missing key name.

REPRODUCTION SCENARIO:
```python
evaluate_condition("output['missing'] > 0", {"score": 0.9})
# → ConditionEvaluationError: "Condition ... raised an error: 'missing'"
```

IMPACT:
Confusing error messages. Low functional impact but poor debuggability.

FIX DIRECTION:
Catch `KeyError` separately and provide a clearer message:
```python
except KeyError as exc:
    raise ConditionEvaluationError(
        f"Condition '{expression}' references key {exc} which is not present "
        f"in the output dict. Available keys: {sorted(output.keys())}"
    ) from exc
```

--------------------------------------------------------------------
FILE:        app/core/conditions.py
FUNCTION:    _validate_ast / evaluate_condition
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Only allow `len()` function calls; disallow all other function calls.

WHAT IT ACTUALLY DOES:
The validator checks `isinstance(node, ast.Call)` and verifies the function
name is `"len"`. However, it does not check the number of arguments to `len()`.
`len()` with zero arguments or two arguments raises `TypeError` at eval time,
which is caught and re-raised as `ConditionEvaluationError`. This is handled
correctly — but `len(output, output)` passes the AST validator and only fails
at runtime.

THE BUG / RISK:
`len(output, output)` passes `_validate_ast()` but raises `TypeError` at
`eval()` time. The error is caught and re-raised as `ConditionEvaluationError`,
so the behavior is correct. This is a minor validator gap — the AST check
could be tighter.

EVIDENCE:
```python
if isinstance(node, ast.Call):
    if not (isinstance(node.func, ast.Name) and node.func.id == "len"):
        raise ConditionEvaluationError(...)
# ↑ does not check len()'s argument count
```

REPRODUCTION SCENARIO:
`evaluate_condition("len(output, output) > 0", {})` — passes AST validation,
fails at runtime with `TypeError`.

IMPACT:
Slightly confusing error message ("raised an error: len() takes exactly one
argument (2 given)"). No security impact.

FIX DIRECTION:
Add argument count check in the `ast.Call` validator:
```python
if isinstance(node, ast.Call):
    if not (isinstance(node.func, ast.Name) and node.func.id == "len"):
        raise ConditionEvaluationError(...)
    if len(node.args) != 1 or node.keywords:
        raise ConditionEvaluationError("len() requires exactly one argument.")
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
| Test Hostile | NO |
| Top Risk | Python 3.8 incompatibility — `ast.Index` is not in the whitelist, causing all subscript-based condition expressions to be rejected on Python 3.8 with a confusing error |
