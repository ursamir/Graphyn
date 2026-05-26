# Functional Review — app/core/nodes/compat.py

**Group:** 2 — Node Base
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/nodes/compat.py
FUNCTION:    CompatibilityChecker.are_compatible
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return `True` if a value of `output_type` can flow into `input_type`.
Rule 4 states: "Either is a generic alias → origins must be identical AND
each pair of corresponding `get_args` elements must be recursively compatible."

WHAT IT ACTUALLY DOES:
Rule 3d (`output is object → can flow into anything`) is applied before
Rule 4 (generic alias check). This means `are_compatible(object, list[str])`
returns `True` — a universal source can flow into any typed port. This is
intentional per the comment.

However, Rule 3c (`input is object → accepts anything`) combined with Rule 3d
creates a symmetric universal bypass. More critically: Rule 4 (generic alias
matching) requires `out_origin == in_origin`. For `list[str]` vs `list[int]`,
`out_origin = list` and `in_origin = list` — origins match. Then `get_args`
returns `(str,)` and `(int,)`. The recursive call `are_compatible(str, int)`
hits Rule 3 (both plain classes) and calls `issubclass(str, int)` which
returns `False`. So `list[str]` is correctly incompatible with `list[int]`.

The real silent failure is with **`NoneType`** in Union args. Consider:
`are_compatible(Optional[str], Optional[int])`:
- `out_origin = Union`, `in_origin = Union`
- Rule 4a: for each `oa` in `(str, NoneType)`, check if any `ia` in `(int, NoneType)` is compatible
- `are_compatible(str, int)` → `issubclass(str, int)` → `False`
- `are_compatible(str, NoneType)` → `issubclass(str, NoneType)` → `False`
- `are_compatible(NoneType, int)` → `issubclass(NoneType, int)` → `False`
- `are_compatible(NoneType, NoneType)` → `issubclass(NoneType, NoneType)` → `True`
- So `oa=str` has no compatible `ia` → returns `False`. Correct.

Now consider `are_compatible(str, Optional[str])` (output is plain `str`,
input is `Optional[str]`):
- `out_origin = None`, `in_origin = Union`
- Rule 4c: `any(are_compatible(str, ia) for ia in (str, NoneType))`
- `are_compatible(str, str)` → `True` → returns `True`. Correct.

Now consider `are_compatible(Optional[str], str)` (output is `Optional[str]`,
input is plain `str`):
- `out_origin = Union`, `in_origin = None`
- Rule 4b: `all(are_compatible(oa, str) for oa in (str, NoneType))`
- `are_compatible(str, str)` → `True`
- `are_compatible(NoneType, str)` → `issubclass(NoneType, str)` → `False`
- Returns `False`.

This is **correct behavior** — an `Optional[str]` output cannot safely flow
into a non-optional `str` input because the output might be `None`. However,
this is a **silent rejection** — the pipeline planner will reject the connection
with a `NodeTypeError` saying "incompatible types", but the user may not
understand why `Optional[str]` is incompatible with `str`. The error message
from `check_connection` does not explain the Optional mismatch.

THE BUG / RISK:
The actual silent failure is in Rule 4 for **`typing.ClassVar`** and
**`typing.Final`** types. `get_origin(ClassVar[str])` returns `ClassVar`
(Python 3.9+). If a port is accidentally declared with `ClassVar[str]`,
`are_compatible(ClassVar[str], str)` hits Rule 4 (generic alias), finds
`out_origin = ClassVar != in_origin = None`, and returns `False`. No error
is raised — the connection is silently rejected.

More critically: `are_compatible` calls `issubclass(output_type, input_type)`
in Rule 3. `issubclass` raises `TypeError` for non-class arguments (e.g.
`issubclass(list[str], list)` raises `TypeError` in Python < 3.10). The
`try/except TypeError` catches this and returns `False` — a silent rejection
that may mask a valid connection.

EVIDENCE:
Lines 44-50:
```python
if out_origin is None and in_origin is None:
    try:
        return issubclass(output_type, input_type)
    except TypeError:
        return False
```

REPRODUCTION SCENARIO:
```python
# Python 3.9 — issubclass(list[str], list) raises TypeError
CompatibilityChecker.are_compatible(list[str], list)
# out_origin = list (not None), so Rule 3 is not reached — actually hits Rule 3b
# This specific case is handled by Rule 3b. But:
CompatibilityChecker.are_compatible(tuple[str, int], tuple)
# out_origin = tuple, in_origin = None, input_type = tuple
# None of Rules 3b/3c/3d apply (input is tuple, not list/object)
# Falls through to Rule 4: out_origin (tuple) != in_origin (None) → False
# Silent rejection of a valid connection
```

IMPACT:
Silent wrong result — valid connections between `tuple[X, Y]` and plain
`tuple` are rejected. Pipeline validation fails with a confusing type error.

FIX DIRECTION:
Add a rule for "input is plain generic type (no args) — accept any
parameterized version":
```python
# After Rule 3b (list), generalize:
if in_origin is None and isinstance(input_type, type) and out_origin is not None:
    try:
        if issubclass(out_origin, input_type):
            return True
    except TypeError:
        pass
```

--------------------------------------------------------------------
FILE:        app/core/nodes/compat.py
FUNCTION:    CompatibilityChecker.are_compatible
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Handle Union types with Rule 4a (Union vs Union covariant subset check).

WHAT IT ACTUALLY DOES:
Rule 4a checks: "every output arg is compatible with at least one input arg."
This is a covariant subset check. However, it does not handle the case where
`get_args` returns an empty tuple. `get_args(Union)` without type parameters
is not normally possible, but `get_args(Union[str])` (single-arg Union, which
Python simplifies to `str`) would not reach this branch. The edge case is
`Union[()]` which is invalid Python but could theoretically be constructed
programmatically.

More practically: `get_args` on a bare `Union` (without parameters) returns
`()`. `all(... for oa in ())` returns `True` (vacuous truth). So
`are_compatible(Union, Union)` would return `True` — but bare `Union` is not
a valid type annotation and would not normally appear.

THE BUG / RISK:
`all(... for oa in ())` returns `True` vacuously. If `get_args` returns an
empty tuple for some edge case Union, `are_compatible` returns `True` for
any input type. This is a silent wrong result.

EVIDENCE:
Lines 68-73:
```python
if out_origin is Union and in_origin is Union:
    out_args = get_args(output_type)
    in_args = get_args(input_type)
    return all(
        any(CompatibilityChecker.are_compatible(oa, ia) for ia in in_args)
        for oa in out_args
    )
```
No guard for empty `out_args` or `in_args`.

REPRODUCTION SCENARIO:
Constructing a bare `Union` programmatically (unusual but possible in
metaprogramming contexts).

IMPACT:
Low probability but silent wrong result — a connection is accepted when it
should be rejected.

FIX DIRECTION:
Add a guard:
```python
if not out_args or not in_args:
    return False
```

--------------------------------------------------------------------
FILE:        app/core/nodes/compat.py
FUNCTION:    _type_to_schema
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Convert a port `data_type` to a minimal JSON Schema dict. Returns `None`
if `t` is `None`.

WHAT IT ACTUALLY DOES:
The fallback at the end of the function:
```python
type_name = getattr(t, "__name__", str(t))
return {"type": "object", "title": type_name}
```
This returns `{"type": "object", ...}` for any type that doesn't match
the known patterns. This includes `numpy.ndarray`, `torch.Tensor`, and
other common ML types. The schema says "type: object" which is technically
incorrect (these are not JSON objects) but will not raise.

More critically: for `typing.Any`, `get_origin(Any)` returns `None` and
`Any` is not a `type` instance in Python 3.11+ (`isinstance(Any, type)`
returns `False`). So `_type_to_schema(Any)` hits the fallback and returns
`{"type": "object", "title": "Any"}`. This is a silent wrong result — the
correct JSON Schema for `Any` is `{}` (no constraints).

EVIDENCE:
Lines 175-177 (fallback):
```python
type_name = getattr(t, "__name__", str(t))
return {"type": "object", "title": type_name}
```

REPRODUCTION SCENARIO:
```python
from typing import Any
_type_to_schema(Any)
# Returns {"type": "object", "title": "Any"} instead of {}
```

IMPACT:
Silent wrong result — API responses show incorrect JSON Schema for ports
typed as `Any`. Schema validation tools may reject valid data.

FIX DIRECTION:
Add an explicit check for `Any` before the fallback:
```python
from typing import Any as TypingAny
if t is TypingAny:
    return {}
```

--------------------------------------------------------------------
FILE:        app/core/nodes/compat.py
FUNCTION:    CompatibilityChecker.check_connection
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate a port-to-port connection, raising `NodeTypeError` if invalid.
Checks port existence and type compatibility.

WHAT IT ACTUALLY DOES:
Accesses `src_node.output_ports` and `dst_node.input_ports` directly.
If `src_node` or `dst_node` does not have these attributes (e.g. a non-Node
object is passed), `AttributeError` is raised instead of `NodeTypeError`.
The docstring does not mention `AttributeError`.

THE BUG / RISK:
Callers expecting only `NodeTypeError` will not catch `AttributeError`.
The exception propagates uncaught.

EVIDENCE:
Lines 107-108:
```python
if src_port not in src_node.output_ports:
if dst_port not in dst_node.input_ports:
```
No guard for missing `output_ports`/`input_ports` attributes.

REPRODUCTION SCENARIO:
```python
CompatibilityChecker.check_connection(object(), "out", some_node, "in")
# AttributeError: 'object' object has no attribute 'output_ports'
```

IMPACT:
Unexpected `AttributeError` propagates to callers expecting `NodeTypeError`.

FIX DIRECTION:
Add attribute existence checks:
```python
if not hasattr(src_node, "output_ports"):
    raise NodeTypeError(f"src_node {src_node!r} has no output_ports attribute")
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 3 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `are_compatible` silently rejects valid connections between parameterized generic types (e.g. `tuple[str, int]`) and their plain base types (e.g. `tuple`) due to missing generalization of Rule 3b beyond `list`. |
