# Functional Review — app/models/feature_array.py

**Group:** 12 — Domain & Models  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/models/feature_array.py
FUNCTION:    FeatureArray (class-level default)
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Provide a typed data contract for acoustic feature arrays.

WHAT IT ACTUALLY DOES:
`metadata: dict = {}` uses a mutable class-level default. Same pattern as `AudioSample.metadata`. Pydantic v2 copies mutable defaults during normal `__init__`, so this is safe for standard construction. However, `model_construct()` bypasses validators and may share the default dict across instances.

Additionally, `data: np.ndarray = Field(default=None)` — the type annotation says `np.ndarray` but the default is `None`. Pydantic v2 will accept `None` at construction time (before the validator runs), but the type annotation is misleading. The `_coerce_float32` validator converts `None` to `np.zeros((0, 0), dtype=np.float32)`, so the stored value is always an ndarray. However, if Pydantic's type checking is strict (e.g., with `model_config = ConfigDict(strict=True)`), this would fail.

EVIDENCE:
Line ~38: `metadata: dict = {}`  
Line ~33: `data: np.ndarray = Field(default=None)` — type says ndarray, default is None.

REPRODUCTION SCENARIO:
```python
f1 = FeatureArray.model_construct()
f1.metadata["key"] = "val"
f2 = FeatureArray.model_construct()
# With model_construct, Pydantic v2 does NOT copy the default_factory
# but for plain `= {}` it uses the class-level dict directly
```

IMPACT:
Low in practice. Latent shared-state bug with `model_construct()`.

FIX DIRECTION:
Change `metadata: dict = {}` to `metadata: dict = Field(default_factory=dict)`. Change `data: np.ndarray = Field(default=None)` to `data: Optional[Any] = Field(default=None)` with a comment, consistent with `AudioSample`.

--------------------------------------------------------------------
FILE:        app/models/feature_array.py
FUNCTION:    FeatureArray.model_post_init
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Ensure data is always a float32 array even when using default.

WHAT IT ACTUALLY DOES:
`model_post_init` checks `if self.data is None` and sets it to `np.zeros((0, 0))`. But `_coerce_float32` already converts `None` to `np.zeros((0, 0))` in `mode="before"`. So `model_post_init` can only fire if `self.data` is `None` after the validator — which should never happen. The check is dead code.

EVIDENCE:
Lines ~55–57:
```python
def model_post_init(self, __context):
    if self.data is None:
        object.__setattr__(self, 'data', np.zeros((0, 0), dtype=np.float32))
```

REPRODUCTION SCENARIO:
Cannot be triggered through normal Pydantic construction. Dead code.

IMPACT:
None — dead code. Minor maintenance confusion.

FIX DIRECTION:
Remove `model_post_init` or add a comment explaining it is a safety net for `model_construct()` usage.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | LOW |
| Silent Failures | 0 |
| Error Handling | COMPLETE |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | Mutable class-level default `metadata: dict = {}` is a latent shared-state bug when `model_construct()` is used. |
