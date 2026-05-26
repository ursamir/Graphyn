# Functional Review — app/models/model_artifact.py

**Group:** 12 — Domain & Models  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/models/model_artifact.py
FUNCTION:    ModelArtifact (class-level defaults)
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Provide a typed data contract for a trained model artifact.

WHAT IT ACTUALLY DOES:
Three fields use mutable class-level defaults:
- `labels: list = []`
- `history: dict = {}`
- `metrics: dict = {}`

In Pydantic v2, mutable defaults for model fields are copied per-instance during normal `__init__`. However, `model_construct()` bypasses `__init__` and uses the class-level default directly — meaning all instances created with `model_construct()` share the same `labels`, `history`, and `metrics` objects. Mutating one instance's `labels` list would mutate all others.

This is particularly dangerous for `ModelArtifact` because:
1. The `trainer` node appends to `history` during training.
2. The `evaluator` node populates `metrics` after evaluation.
3. If either node uses `model_construct()` (e.g., for performance), shared state corruption occurs.

EVIDENCE:
Lines ~40–44:
```python
model_path: str = ""
labels: list = []
history: dict = {}
metrics: dict = {}
```
No `Field(default_factory=...)` for any mutable field.

REPRODUCTION SCENARIO:
```python
a = ModelArtifact.model_construct(model_path="model_a")
b = ModelArtifact.model_construct(model_path="model_b")
a.labels.append("cat")
print(b.labels)  # ["cat"] — shared mutable default
```

IMPACT:
Silent state corruption — if `model_construct()` is used anywhere in the pipeline (e.g., in checkpoint deserialization or artifact store), all `ModelArtifact` instances share the same `labels`, `history`, and `metrics` lists/dicts. Training history from one run contaminates another.

FIX DIRECTION:
```python
labels: list = Field(default_factory=list)
history: dict = Field(default_factory=dict)
metrics: dict = Field(default_factory=dict)
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | COMPLETE |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | All three mutable fields (`labels`, `history`, `metrics`) use class-level mutable defaults — shared across all instances created with `model_construct()`, causing silent state corruption between training runs. |
