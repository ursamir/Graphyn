# Functional Review — app/models/tflite_artifact.py

**Group:** 12 — Domain & Models  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/models/tflite_artifact.py
FUNCTION:    TFLiteArtifact (class-level default)
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Provide a typed data contract for a TFLite model artifact.

WHAT IT ACTUALLY DOES:
`labels: list = []` uses a mutable class-level default. Same pattern as `ModelArtifact`. With `model_construct()`, all instances share the same `labels` list.

EVIDENCE:
Line ~40: `labels: list = []`

REPRODUCTION SCENARIO:
```python
a = TFLiteArtifact.model_construct(tflite_path="a.tflite")
b = TFLiteArtifact.model_construct(tflite_path="b.tflite")
a.labels.append("cat")
print(b.labels)  # ["cat"] — shared mutable default
```

IMPACT:
Silent state corruption if `model_construct()` is used. The `edge_optimizer` node produces `TFLiteArtifact` instances — if it uses `model_construct()` for performance, label lists from different optimization runs are shared.

FIX DIRECTION:
`labels: list = Field(default_factory=list)`

--------------------------------------------------------------------
FILE:        app/models/tflite_artifact.py
FUNCTION:    TFLiteArtifact._validate_quantisation
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate that `quantisation` is one of `{"float32", "float16", "int8"}`.

WHAT IT ACTUALLY DOES:
The validator is correct and raises `ValueError` for invalid values. However, the field name uses British spelling (`quantisation`) while `DeploymentArtifact` uses American spelling (`quantization`). This inconsistency means code that handles both types must use different field names, and any generic serialization/deserialization code that maps `quantization` → `quantisation` will silently fail.

EVIDENCE:
`tflite_artifact.py` line ~40: `quantisation: str = "float32"`  
`deployment_artifact.py` line ~45: `quantization: str = "none"`

REPRODUCTION SCENARIO:
Generic code: `artifact.quantization` → `AttributeError` on `TFLiteArtifact` (field is `quantisation`).

IMPACT:
Low — API inconsistency, not a runtime crash in normal usage. But any code that accesses `quantization` on a `TFLiteArtifact` will get `AttributeError`.

FIX DIRECTION:
Standardize on one spelling across all models. Add a `quantization` alias or rename the field.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 1 |
| Error Handling | COMPLETE |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `labels: list = []` is a mutable class-level default — shared across all instances created with `model_construct()`, causing silent label list corruption between edge optimization runs. |
