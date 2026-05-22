# Tasks 06 — Property-Based Tests (Hypothesis)

← [Back to tasks.md](tasks.md)

---

All property tests use [Hypothesis](https://hypothesis.readthedocs.io/) and run a minimum of 100 iterations.
File: `tests/test_properties.py`

Tag format: `Feature: enhanced-node-system, Property {N}: {property_text}`

---

## Tasks

- [x] 38. Write Property 1 — `are_compatible` is reflexive for non-`None` types
  - **Property 1: `are_compatible(T, T)` is `True` for any non-`None` type T**
  - Use `@given(st.sampled_from([int, str, float, bool, bytes, list, dict]))` with `@settings(max_examples=100)`
  - Assert `CompatibilityChecker.are_compatible(t, t) is True`
  - **Validates: Requirements R2D.10**
  - _Design: design-04-serialisation.md § 4 Property 1_

- [x] 39. Write Property 2 — `are_compatible` respects `issubclass` for plain classes
  - **Property 2: `are_compatible(A, B) == issubclass(A, B)` for plain (non-generic) class pairs**
  - Use `@given(st.sampled_from([(bool, int), (int, bool), (int, str), (str, str), (float, int), (int, float)]))`
  - Assert `CompatibilityChecker.are_compatible(A, B) == issubclass(A, B)`
  - **Validates: Requirements R2D.10**
  - _Design: design-04-serialisation.md § 4 Property 2_

- [x] 40. Write Property 3 — `TypeCatalogue` round-trip: `resolve(fqn(T)) is T`
  - **Property 3: registering a `PortDataType` subclass and resolving its FQN returns the exact same type object**
  - Use `@given(st.text(alphabet=..., min_size=3, max_size=20).map(str.capitalize))` to generate type names
  - Dynamically create `PortDataType` subclass with `type(name, (PortDataType,), {"__module__": "test_module"})`
  - Register in a fresh `TypeCatalogue`, resolve via `_fqn(T)`, assert `resolved is T`
  - **Validates: Requirements R13A.3**
  - _Design: design-04-serialisation.md § 4 Property 3_

- [x] 41. Write Property 4 — Registry completeness: every registered node is retrievable
  - **Property 4: `get_class(node_type) is cls` and `get_metadata(node_type).node_type == node_type` for any registered node**
  - Use `@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=3, max_size=20))`
  - Create a fresh `NodeRegistry`, build a minimal `NodeMetadata` and `Node` subclass, register, then assert both lookups
  - **Validates: Requirements R3.2, R4.4**
  - _Design: design-04-serialisation.md § 4 Property 4_

- [x] 42. Write Property 5 — SISO wrapper equivalence
  - **Property 5: `node.process({"input": x})["output"]` equals the original unwrapped transform applied to `x`**
  - Use `@given(st.lists(st.integers(), max_size=20))`
  - Dynamically create a SISO `Node` subclass whose `process(self, data)` doubles each element
  - Assert `node.process({"input": data})["output"] == [v * 2 for v in data]`
  - **Validates: Requirements R2B.6**
  - _Design: design-04-serialisation.md § 4 Property 5_

- [x] 43. Write Property 6 — Retry backoff formula
  - **Property 6: `RetryPolicy.wait_before_attempt(i)` equals `backoff_seconds * (backoff_multiplier ** i)`**
  - Use `@given(backoff_seconds=st.floats(min_value=0.0, max_value=60.0, allow_nan=False), backoff_multiplier=st.floats(min_value=1.0, max_value=10.0, allow_nan=False), max_attempts=st.integers(min_value=1, max_value=10), attempt_index=st.integers(min_value=0, max_value=9))` with `@settings(max_examples=200)`
  - Assert `math.isclose(policy.wait_before_attempt(attempt_index), backoff_seconds * (backoff_multiplier ** attempt_index), rel_tol=1e-9)`
  - **Validates: Requirements R6.3**
  - _Design: design-04-serialisation.md § 4 Property 6_

- [x] 44. Write Property 7 — `NodeMetadata` serialisation round-trip
  - **Property 7: `NodeMetadata.model_validate(m.model_dump(mode="json")) == m` for any `NodeMetadata` instance**
  - Use `@given(st.builds(NodeMetadata, node_type=_NONEMPTY_STR, label=_NONEMPTY_STR, description=_NONEMPTY_STR, category=_NONEMPTY_STR, version=st.just("1.0.0"), tags=st.lists(st.text(min_size=1, max_size=10), max_size=5)))` with `@settings(max_examples=100)`
  - Assert `NodeMetadata.model_validate(m.model_dump(mode="json")) == m`
  - **Validates: Requirements R11.2**
  - _Design: design-04-serialisation.md § 4 Property 7_

- [x] 45. Write Property 8 — Config schema idempotence
  - **Property 8: `get_config_schema(t) == get_config_schema(t)` for every registered node type `t`**
  - Iterate over all `registry._classes` keys (exhaustive, not randomised — the set is finite and deterministic)
  - For each `node_type`, call `registry.get_config_schema(node_type)` twice and assert structural equality
  - **Validates: Requirements R12.3**
  - _Design: design-04-serialisation.md § 4 Property 8_

- [x] 46. Checkpoint — all property tests pass
  - Run `venv/bin/pytest tests/test_properties.py -v` and ensure all 8 property tests pass
  - Ensure all tests pass, ask the user if questions arise.
