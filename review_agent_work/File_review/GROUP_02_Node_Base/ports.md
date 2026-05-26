# Functional Review — app/core/nodes/ports.py

**Group:** 2 — Node Base
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/nodes/ports.py
FUNCTION:    InputPort._must_be_type_or_none / OutputPort._must_be_type_or_none
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Reject non-type values early so errors surface at port declaration time.
Accepts `type`, generic alias, or `None`.

WHAT IT ACTUALLY DOES:
The validator checks `isinstance(v, type)` OR `get_origin(v) is not None`.
`get_origin` returns non-None for generic aliases like `list[str]`, `dict[str, int]`,
`Optional[X]`, etc. However, `get_origin` also returns non-None for
`typing.Annotated[X, ...]` — which is a valid annotation but not a usable
port data type for schema generation or compatibility checking. The validator
silently accepts `Annotated` types.

Additionally, `get_origin` returns non-None for `typing.Literal["a", "b"]`,
which is also not a meaningful port data type. These pass validation silently
and will cause `_type_to_schema` and `CompatibilityChecker.are_compatible` to
produce incorrect or unexpected results downstream.

THE BUG / RISK:
`Annotated[AudioSample, some_metadata]` passes the validator but
`CompatibilityChecker.are_compatible` will compare `get_origin(Annotated[...])` 
(which is `Annotated`) against the input port's origin, likely returning `False`
for a valid connection. Silent type mismatch at pipeline validation time.

EVIDENCE:
Lines 52-56 (InputPort), lines 74-78 (OutputPort):
```python
if v is not None and not isinstance(v, type) and get_origin(v) is None:
    raise ValueError(...)
return v
```

REPRODUCTION SCENARIO:
```python
port = InputPort(name="input", data_type=Annotated[AudioSample, "some_meta"])
# Passes validation silently; CompatibilityChecker will fail to match it
# against a plain AudioSample output port.
```

IMPACT:
Silent wrong result — a valid connection is rejected at pipeline validation
time with a confusing "incompatible types" error, or an invalid connection
is accepted.

FIX DIRECTION:
Add explicit rejection of `Annotated` and `Literal` origins:
```python
from typing import Annotated, Literal, get_origin
REJECTED_ORIGINS = {Annotated}
if get_origin(v) in REJECTED_ORIGINS:
    raise ValueError(f"data_type must not use Annotated or Literal, got {v!r}")
```

--------------------------------------------------------------------
FILE:        app/core/nodes/ports.py
FUNCTION:    InputPort (model)
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Descriptor for a node's input port. `required=False` means the port does not
need to be connected; the runtime passes `None` for unconnected optional ports.

WHAT IT ACTUALLY DOES:
The `required` field is declared but there is no validator enforcing that
`required=False` ports have `data_type` that accepts `None` (i.e. is
`Optional[X]` or `X | None`). A node can declare `required=False` with
`data_type=AudioSample` (non-nullable), and the runtime will pass `None`
into a port that expects `AudioSample`. The node's `process()` will then
receive `None` where it expects an `AudioSample`, likely causing an
`AttributeError` deep in the node's logic.

THE BUG / RISK:
Silent contract violation — `required=False` implies the node must handle
`None`, but the port type does not enforce this. The error surfaces deep
in `process()` with a confusing traceback.

EVIDENCE:
Lines 37-56 — no cross-field validator between `required` and `data_type`.

REPRODUCTION SCENARIO:
```python
port = InputPort(name="audio", data_type=AudioSample, required=False)
# Runtime passes None; node does node.audio.sample_rate → AttributeError
```

IMPACT:
Runtime crash deep in node logic with a confusing traceback.

FIX DIRECTION:
Add a model validator that warns (or raises) when `required=False` and
`data_type` is not `Optional`/`None`-accepting:
```python
@model_validator(mode="after")
def _optional_port_must_accept_none(self):
    if not self.required and self.data_type is not None:
        origin = get_origin(self.data_type)
        if origin is Union:
            args = get_args(self.data_type)
            if type(None) not in args:
                raise ValueError("required=False port data_type must accept None")
    return self
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
| Top Risk | `Annotated` and `Literal` types pass the data_type validator silently and cause incorrect compatibility checks downstream. |
