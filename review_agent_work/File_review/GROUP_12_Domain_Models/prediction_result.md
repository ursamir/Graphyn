# Functional Review — app/models/prediction_result.py

**Group:** 12 — Domain & Models  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/models/prediction_result.py
FUNCTION:    PredictionResult (class-level defaults)
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Provide a typed data contract for inference results from classification and detection nodes.

WHAT IT ACTUALLY DOES:
Two fields use mutable class-level defaults:
- `probabilities: dict = {}`
- `metadata: dict = {}`

Same pattern as `ModelArtifact`. With `model_construct()`, all instances share the same `probabilities` and `metadata` dicts. For `PredictionResult`, this is particularly dangerous because:
1. The `audio_classifier` and `realtime_inference` nodes produce one `PredictionResult` per input sample.
2. If these nodes use `model_construct()` for performance (common in hot paths), all results share the same `probabilities` dict.
3. The last sample's probabilities overwrite all previous results.

EVIDENCE:
Lines ~38–42:
```python
source_path: str = ""
predicted_label: str = ""
probabilities: dict = {}
metadata: dict = {}
```

REPRODUCTION SCENARIO:
```python
results = [PredictionResult.model_construct(predicted_label=str(i)) for i in range(3)]
results[0].probabilities["cat"] = 0.9
print(results[1].probabilities)  # {"cat": 0.9} — shared mutable default
```

IMPACT:
Silent state corruption in batch inference — all `PredictionResult` instances in a batch share the same `probabilities` dict if `model_construct()` is used. The final result's probabilities overwrite all others.

FIX DIRECTION:
```python
probabilities: dict = Field(default_factory=dict)
metadata: dict = Field(default_factory=dict)
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
| Top Risk | `probabilities` and `metadata` use class-level mutable defaults — shared across all instances created with `model_construct()`, causing silent result corruption in batch inference pipelines. |
