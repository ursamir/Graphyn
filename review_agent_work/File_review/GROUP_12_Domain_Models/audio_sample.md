# Functional Review — app/models/audio_sample.py

**Group:** 12 — Domain & Models  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/models/audio_sample.py
FUNCTION:    AudioSample (class-level default)
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Provide a Pydantic model for a single audio clip with waveform, sample rate, label, and metadata.

WHAT IT ACTUALLY DOES:
The `metadata` field is declared as `metadata: dict[str, Any] = {}` — a mutable default dict at the class level. In Pydantic v2, class-level mutable defaults for model fields are shared across instances unless `Field(default_factory=dict)` is used. Pydantic v2 does copy mutable defaults for each instance during `__init__`, so this is safe for normal construction. However, if any code mutates `AudioSample.model_fields["metadata"].default` directly (unlikely but possible), all subsequently constructed instances would share the mutated default.

THE BUG / RISK:
The more immediate risk is that `metadata: dict[str, Any] = {}` is a pattern that Pydantic v2 handles correctly (it copies the default), but it is inconsistent with the other models in this group that use `Field(default_factory=dict)`. If this model is ever subclassed or used with `model_construct()` (which bypasses validators), the shared mutable default could leak between instances.

EVIDENCE:
Line ~45:
```python
metadata: dict[str, Any] = {}
```
Compare with `TensorBatch` which uses `Field(default_factory=dict)`.

REPRODUCTION SCENARIO:
```python
s = AudioSample.model_construct(path="", sample_rate=16000)
s.metadata["key"] = "value"
s2 = AudioSample.model_construct(path="", sample_rate=16000)
# s2.metadata may be {} (safe with Pydantic v2 model_construct) or shared
```

IMPACT:
Low in practice with Pydantic v2 normal construction, but a latent bug if `model_construct` is used or if the class is subclassed. Inconsistency with other models in the same package.

FIX DIRECTION:
Change to `metadata: dict[str, Any] = Field(default_factory=dict)` for consistency and safety.

--------------------------------------------------------------------
FILE:        app/models/audio_sample.py
FUNCTION:    AudioSample.model_post_init
CATEGORY:    Type Safety
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Ensure data is always a float32 ndarray after construction.

WHAT IT ACTUALLY DOES:
`_coerce_data` validator runs `mode="before"` and converts `None` to an empty float32 array. `model_post_init` then checks `if not isinstance(self.data, np.ndarray)` and converts again. Since `_coerce_data` already handles `None`, `model_post_init` only fires for non-ndarray values that somehow passed the validator (e.g., if Pydantic skips the validator for some reason). In practice, `model_post_init` is redundant but harmless.

The real issue: `data: Optional[Any] = None` — the type annotation says `Optional[Any]`, which means Pydantic will not enforce that `data` is a numpy array at the type level. Any value can be passed and will be stored as-is if it passes the validator. The validator converts to ndarray, but the type annotation provides no IDE or static analysis support.

EVIDENCE:
Line ~40: `data: Optional[Any] = None`

REPRODUCTION SCENARIO:
`AudioSample(path="", sample_rate=16000, data="not_an_array")` → `_coerce_data` calls `np.asarray("not_an_array", dtype=np.float32)` → raises `ValueError`. This is correct behavior but the error message is not user-friendly.

IMPACT:
Low — type annotation is misleading but behavior is correct.

FIX DIRECTION:
Consider annotating as `data: Any = None` with a comment explaining the numpy constraint, or use a custom Pydantic type for numpy arrays.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 0 |
| Error Handling | COMPLETE |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | Mutable class-level default `metadata: dict = {}` is safe with Pydantic v2 normal construction but is a latent shared-state bug if `model_construct()` is used or the class is subclassed. |
