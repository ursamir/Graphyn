# Functional Review — app/core/utils/hash.py

**Group:** 8 — Platform Infra  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/utils/hash.py
FUNCTION:    stable_hash
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return a stable integer hash of the given arguments. Uses JSON encoding to
avoid separator-collision bugs. `None` and `"None"` are correctly
distinguished.

WHAT IT ACTUALLY DOES:
Uses `json.dumps(list(args), sort_keys=True, default=str)`. The `sort_keys=True`
parameter sorts dictionary keys — but it does NOT sort the top-level list.
The list is `list(args)`, which preserves argument order. This is correct for
positional arguments. However, `sort_keys=True` applies recursively to any
dict values inside `args`. This means:

```python
stable_hash({"b": 1, "a": 2})  # → json: [{"a": 2, "b": 1}]
stable_hash({"a": 2, "b": 1})  # → json: [{"a": 2, "b": 1}]  ← same hash
```

Two calls with dicts in different key orders produce the same hash. This is
likely intentional for dict arguments (order-independent). But it also means:

```python
stable_hash({"a": 1}, {"b": 2})  # → [{"a": 1}, {"b": 2}]
stable_hash({"b": 2}, {"a": 1})  # → [{"b": 2}, {"a": 1}]  ← DIFFERENT hash
```

Argument order matters for the outer list but not for dict contents. This
asymmetry is not documented and may surprise callers who pass dicts in
different orders expecting the same hash.

THE BUG / RISK:
The `sort_keys=True` flag is misleading: it only sorts dict keys, not the
argument list. A caller who passes `stable_hash(config_dict)` where
`config_dict` has varying key insertion order (e.g. from different Python
versions or dict merge operations) will get a stable hash. But a caller who
passes `stable_hash(key1, key2)` where `key1` and `key2` are swapped will
get a different hash — which may or may not be the intended behavior. The
docstring does not clarify this.

EVIDENCE:
```python
s = json.dumps(list(args), sort_keys=True, default=str)
```
`list(args)` preserves argument order. `sort_keys=True` only affects nested
dicts.

REPRODUCTION SCENARIO:
```python
h1 = stable_hash("node_a", "node_b")
h2 = stable_hash("node_b", "node_a")
assert h1 != h2  # True — order matters for strings
h3 = stable_hash({"x": 1, "y": 2})
h4 = stable_hash({"y": 2, "x": 1})
assert h3 == h4  # True — order doesn't matter for dict keys
```
The inconsistency between string args (order-sensitive) and dict args
(order-insensitive) is undocumented.

IMPACT:
Silent wrong result if callers assume argument order is irrelevant (e.g.
using `stable_hash` as a set-membership key for unordered node pairs). Cache
misses or incorrect cache hits depending on argument ordering.

FIX DIRECTION:
Document the behavior explicitly:
```python
"""
...
Note: argument ORDER matters — stable_hash("a", "b") != stable_hash("b", "a").
Dict KEY order within a single argument does NOT matter (sort_keys=True).
"""
```
If order-independent hashing of the full argument list is needed, sort
`list(args)` before serializing (only safe if all args are comparable).

--------------------------------------------------------------------
FILE:        app/core/utils/hash.py
FUNCTION:    stable_hash
CATEGORY:    Type Safety
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return a stable integer hash. Uses `default=str` to handle non-JSON-
serializable types.

WHAT IT ACTUALLY DOES:
`default=str` converts non-serializable objects to their `str()` repr. This
means:
- `stable_hash(some_object)` and `stable_hash(str(some_object))` produce the
  same hash if `str(some_object)` happens to equal the JSON repr of the string.
- Two different objects with the same `str()` repr produce the same hash.
- The `str()` repr of many objects includes memory addresses
  (`<MyClass object at 0x7f...>`), making the hash non-stable across runs.

THE BUG / RISK:
If a caller passes a non-JSON-serializable object (e.g. a numpy array, a
custom class, a `Path`), `default=str` silently converts it. For objects
whose `str()` includes a memory address, the hash is NOT stable across
process restarts — contradicting the function's core guarantee.

EVIDENCE:
```python
s = json.dumps(list(args), sort_keys=True, default=str)
```
`default=str` is the fallback for any non-serializable type.

REPRODUCTION SCENARIO:
```python
class Foo:
    pass
h1 = stable_hash(Foo())  # includes memory address in str()
# restart process
h2 = stable_hash(Foo())  # different memory address → different hash
assert h1 != h2  # True — hash is NOT stable across runs
```

IMPACT:
Silent wrong result. Cache keys derived from `stable_hash` of non-primitive
objects are not stable across process restarts, causing cache misses or
incorrect behavior.

FIX DIRECTION:
Remove `default=str` and let `json.dumps` raise `TypeError` for
non-serializable types, forcing callers to pass only JSON-serializable
primitives:
```python
s = json.dumps(list(args), sort_keys=True)  # raises TypeError for bad input
```
Or document that `default=str` is only safe for types with stable `str()`
representations (strings, ints, floats, bools, None, Path).

--------------------------------------------------------------------
FILE:        app/core/utils/hash.py
FUNCTION:    stable_hash
CATEGORY:    Performance
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return a stable integer hash suitable for seeding RNGs and cache key
derivation.

WHAT IT ACTUALLY DOES:
Returns a full 128-bit MD5 integer (up to 39 decimal digits). Many callers
that use this as an RNG seed (e.g. `random.seed(stable_hash(...))`) pass it
to Python's `random.seed()`, which accepts arbitrarily large integers. This
is fine. However, callers that use it as a dict key or array index may
inadvertently create very large integers where a smaller hash would suffice.

THE BUG / RISK:
Not a correctness bug, but the return type is `int` with no documented range.
Callers that do `stable_hash(...) % N` for bucketing get correct results, but
callers that compare the full integer across platforms need to know that MD5
output is 128 bits. The docstring says "stable integer hash" without
specifying the range.

EVIDENCE:
```python
return int(hashlib.md5(s.encode(), usedforsecurity=False).hexdigest(), 16)
```
Returns a 128-bit integer (0 to 2^128 - 1).

REPRODUCTION SCENARIO:
Not a bug — informational only.

IMPACT:
None for correctness. Documentation gap only.

FIX DIRECTION:
Add to docstring: "Returns a non-negative integer in the range [0, 2^128)."

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `default=str` silently converts non-JSON-serializable objects (including those with memory-address-based `str()` reprs) to strings, producing hashes that are NOT stable across process restarts — violating the function's core guarantee. |
