# tasks-06 — Property-Based Tests

## Overview

Write property-based tests using Hypothesis for all 9 correctness properties defined in `design.md`. These tests validate universal invariants across randomly generated inputs. Each test runs a minimum of 100 iterations.

## Tasks

- [x] 21. Write property-based tests (`tests/test_plugin_properties.py`)
  - [x]* 21.1 Write Property 1: Manifest Round-Trip
    - **Property 1: Manifest round-trip**
    - `@given(st.fixed_dictionaries({...}))` — generate valid manifest dicts with valid slugs, PEP 440 versions, PEP 440 specifiers, PEP 508 deps
    - Serialize `PluginManifest` to a TOML string (using `tomli_w` or manual formatting), parse back with `load_manifest()`
    - Assert all fields equal the original
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 1: Manifest round-trip`
    - **Validates: Requirements 1.1, 1.3**

  - [x]* 21.2 Write Property 2: Invalid Manifest Always Rejected
    - **Property 2: Invalid manifest always rejected**
    - `@given(st.one_of(...))`  — generate dicts with at least one invalid field: missing required field, non-slug name, invalid version string, invalid specifier, invalid PEP 508 dep, empty entry_points
    - Assert `load_manifest()` raises `PluginManifestError` for every generated invalid manifest
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 2: Invalid manifest always rejected`
    - **Validates: Requirements 1.4, 1.5, 1.7, 1.8, 1.9, 3.8**

  - [x]* 21.3 Write Property 3: Platform Version Compatibility Correctness
    - **Property 3: Platform version compatibility correctness**
    - `@given(st.from_regex(r"\d+\.\d+\.\d+"), st.from_regex(r"[><=!~]+\d+\.\d+"))`  — generate version strings and specifier strings
    - Filter to valid PEP 440 versions and specifiers using `assume()`
    - Assert `PluginLoader._check_platform_compat()` accepts iff `Version(v) in SpecifierSet(c)`
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 3: Platform version compatibility correctness`
    - **Validates: Requirements 2.2**

  - [x]* 21.4 Write Property 4: Dependency Reporting Completeness
    - **Property 4: Dependency reporting completeness**
    - `@given(st.lists(st.text(min_size=1, max_size=20).filter(str.isidentifier), min_size=1, max_size=5))`  — generate package names
    - Mock `importlib.metadata.version` to raise `PackageNotFoundError` for a random subset
    - Assert `DependencyChecker.check()` raises `PluginDependencyError` whose message contains exactly the unsatisfied package names
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 4: Dependency reporting completeness`
    - **Validates: Requirements 3.1, 3.2**

  - [x]* 21.5 Write Property 5: PluginStore Round-Trip
    - **Property 5: PluginStore round-trip**
    - `@given(st.fixed_dictionaries({...}))` — generate valid `PluginRecord` field values (name as slug, version as PEP 440, etc.)
    - Save `PluginRecord` to `PluginStore`, load it back with `store.get(name)`
    - Assert all fields equal the original
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 5: PluginStore round-trip`
    - **Validates: Requirements 4.1, 4.2**

  - [x]* 21.6 Write Property 6: Enable/Disable Toggles State Correctly
    - **Property 6: Enable/disable toggles state correctly**
    - `@given(st.booleans())` — generate initial enabled state
    - Install a minimal plugin, set initial state, then apply a sequence of enable/disable operations
    - Assert the final `enabled` field in `PluginStore` matches the last operation
    - Assert disable → enable results in `enabled=True`; enable → disable results in `enabled=False`
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 6: Enable/disable toggles state correctly`
    - **Validates: Requirements 4.4, 4.5**

  - [x]* 21.7 Write Property 7: Search Results Are a Subset Matching the Query
    - **Property 7: Search results are a subset matching the query**
    - `@given(st.lists(st.fixed_dictionaries({...}), min_size=0, max_size=10), st.text(min_size=1, max_size=10))`  — generate index entries and query strings
    - Inject entries into `PluginIndexClient` (mock `fetch()`)
    - Assert every result contains the query in `name`, `description`, or `tags` (case-insensitive)
    - Assert no matching entry from the index is absent from the results
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 7: Search results are a subset matching the query`
    - **Validates: Requirements 6.5**

  - [x]* 21.8 Write Property 8: Checksum Verification Correctness
    - **Property 8: Checksum verification correctness**
    - `@given(st.binary(min_size=1, max_size=1024))`  — generate arbitrary byte sequences
    - Compute correct checksum: `"sha256:" + hashlib.sha256(data).hexdigest()`
    - Assert `PluginInstaller._verify_checksum(data, correct_checksum, "test")` does not raise
    - Assert `PluginInstaller._verify_checksum(data, "sha256:" + "0" * 64, "test")` raises `PluginInstallError` (unless data happens to hash to all zeros)
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 8: Checksum verification correctness`
    - **Validates: Requirements 6.6**

  - [x]* 21.9 Write Property 9: Installed Plugins API Round-Trip
    - **Property 9: Installed plugins API round-trip**
    - `@given(st.lists(st.fixed_dictionaries({...}), min_size=0, max_size=5))`  — generate sets of plugin records
    - Mock `PluginManager.list_installed()` to return the generated records
    - Call `GET /api/v1/plugins` via `TestClient`
    - Assert response length equals number of records
    - Assert each record's `name` and `version` appear in the response
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 9: Installed plugins API round-trip`
    - **Validates: Requirements 8.2**

- [x] 22. Final Checkpoint — all tests pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm all existing + new Phase 5 tests pass.
  - Verify `audiobuilder plugin list` runs without error.
  - Verify `GET /api/v1/plugins` returns 200.
  - Ask the user if questions arise.
