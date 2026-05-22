# Requirements Document

## Introduction

This spec defines a deep, structured second-pass code review of the `app/core/` directory of the
Pipeline Engine — a general-purpose AI/workflow execution platform. A first-pass review
(`docs/review/`) identified and fixed 96 of 103 issues across five module groups. This second-pass
review targets the 7 remaining open items, validates that all prior fixes are correctly implemented,
and extends coverage to areas the first pass did not fully address: test coverage gaps, documentation
completeness, security hardening, performance at scale, and adherence to project conventions.

The review is executed by specialized sub-agents, one per module group, each following a
plan-then-execute methodology. Reviews are sequential to avoid token waste and request overloading.
Each review phase produces a structured findings report in a defined format. The review is complete
when all acceptance criteria in this document are satisfied.

---

## Glossary

- **Review_Agent**: A specialized sub-agent responsible for reviewing one module group.
- **Module_Group**: A logical cluster of related files within `app/core/` assigned to one Review_Agent.
- **Finding**: A documented issue or observation produced by a Review_Agent, following the Finding Format.
- **Prior_Review**: The existing review artifacts in `docs/review/` (01–05 + AUDIT.md + INDEX.md).
- **Open_Item**: One of the 7 issues from the Prior_Review that are Partial (🔶) or Not Applied (❌).
- **Correctness_Property**: A verifiable invariant, round-trip, or metamorphic property that can be expressed as a property-based test.
- **EARS**: Easy Approach to Requirements Syntax — the pattern system used for all acceptance criteria.
- **PBT**: Property-Based Testing using the Hypothesis library (already present in `unit_test/core/test_property_based.py`).
- **Convention**: A project-wide rule documented in `.kiro/steering/` steering files.
- **Severity**: One of 🔴 Critical / 🟠 High / 🟡 Medium / 🔵 Low (defined in Requirement 3).
- **Fix_Status**: One of ✅ Fixed / 🔶 Partial / ❌ Not Applied / 🆕 New Finding.

---

## Requirements

---

### Requirement 1: Review Scope and Module Group Assignment

**User Story:** As a developer taking over this codebase, I want the review scope to be precisely
defined with clear module group boundaries, so that no file is missed and no file is reviewed twice.

#### Acceptance Criteria

1. WHEN the review begins, THE Review_Agent SHALL include every Python file in `app/core/` in
   exactly one module group's findings report, with no file assigned to more than one group.

2. THE Review_Agent SHALL use the following module group assignments:

   | Group | ID | Files |
   |---|---|---|
   | Node System | G1 | `nodes/base.py`, `nodes/ports.py`, `nodes/config.py`, `nodes/metadata.py`, `nodes/retry.py`, `nodes/registry.py`, `nodes/discovery.py`, `nodes/catalogue.py`, `nodes/compat.py`, `nodes/errors.py`, `nodes/observers.py`, `nodes/__init__.py` |
   | Pipeline & IR | G2 | `pipeline.py`, `validation.py`, `pipeline_cache.py`, `executor.py`, `conditions.py`, `events.py`, `ir/models.py`, `ir/loader.py`, `ir/yaml_shim.py`, `ir/migrate.py`, `ir/__init__.py` |
   | Backend Services | G3 | `run_manager.py`, `logger.py`, `artifact_store.py`, `provenance.py`, `config.py`, `quality_checker.py`, `webhook.py`, `ingestion.py`, `project_manager.py`, `runtime_backend.py`, `registry_runtime.py` |
   | Plugin Ecosystem | G4 | `plugins/manager.py`, `plugins/loader.py`, `plugins/manifest.py`, `plugins/store.py`, `plugins/installer.py`, `plugins/index.py`, `plugins/dependencies.py`, `plugins/errors.py`, `plugins/__init__.py` |
   | SDK & Utilities | G5 | `sdk.py`, `utils/hash.py`, `utils/__init__.py`, `__init__.py` |

   > **Note:** `artifact_store.py` is assigned to G3 (Backend Services). G5 SHALL cross-reference
   > G3's findings for `artifact_store.py` where relevant but SHALL NOT re-review it.

3. WHEN a file is found in `app/core/` that is not listed in criterion 2, THE Review_Agent SHALL
   assign it to the group whose directory prefix most closely matches the file's path (e.g., a
   file under `app/core/nodes/` goes to G1; a file under `app/core/plugins/` goes to G4; a
   top-level file with no matching prefix goes to G5) and flag it as an unreviewed file in that
   group's findings report.

---

### Requirement 2: Plan-Then-Execute Methodology

**User Story:** As a developer, I want each review phase to follow a plan-then-execute approach,
so that the review is systematic and does not miss issues through shallow scanning.

#### Acceptance Criteria

1. WHEN a Review_Agent begins a module group, THE Review_Agent SHALL first produce an Exploration
   Plan. The Exploration Plan is a structured list where each entry contains exactly three fields:
   (a) the file path relative to `app/core/`, (b) a one-sentence statement of the file's stated
   purpose, and (c) a numbered list of specific review questions to answer for that file.

2. WHEN the Exploration Plan is complete — defined as every file in the group having all three
   fields populated — THE Review_Agent SHALL begin reading source files. No file reading, finding
   recording, or dimension evaluation SHALL occur before the Exploration Plan is fully complete.

3. WHEN the Exploration Plan is complete, THE Review_Agent SHALL read all lines of each file
   before recording any finding for that file. A file is considered fully read when all lines
   from line 1 to the last line have been processed.

4. WHEN a file has been fully read, THE Review_Agent SHALL evaluate it against all eight review
   dimensions defined in Requirement 3 before moving to the next file.

5. IF a Review_Agent identifies a finding that spans multiple module groups, THEN THE Review_Agent
   SHALL record it in the group where the root cause resides and include a cross-reference field
   listing all affected files outside the current group.

6. WHEN a module group is fully complete — defined as all files read, all dimensions evaluated,
   all findings recorded, and the group report file written — THE Review_Agent SHALL begin the
   next group in sequential order G1 → G2 → G3 → G4 → G5.

7. IF a file in the group cannot be read (e.g., permission error, file not found), THEN THE
   Review_Agent SHALL record a 🟠 High finding for that file with dimension D1, status "Unreadable",
   and the OS error message as evidence, then continue to the next file in the group.

---

### Requirement 3: Review Dimensions

**User Story:** As a developer, I want every file reviewed across a consistent set of quality
dimensions, so that the review is comprehensive and comparable across module groups.

#### Acceptance Criteria

1. THE Review_Agent SHALL evaluate every file against the following eight dimensions:

   | Dim | Name | Description |
   |---|---|---|
   | D1 | Code Quality & Correctness | Logic errors, off-by-one, type mismatches, silent failures, incorrect algorithms |
   | D2 | Architecture & Design Patterns | Separation of concerns, SOLID principles, coupling, cohesion, abstraction leaks |
   | D3 | Error Handling & Edge Cases | Missing guards, swallowed exceptions, undefined behavior on bad input |
   | D4 | Performance | Algorithmic complexity, unnecessary allocations, blocking I/O in async context, unbounded growth |
   | D5 | Test Coverage Gaps | Missing unit tests, missing property tests, missing edge-case tests, untested error paths |
   | D6 | Security | Input validation, path traversal, SSRF, injection, credential exposure, race conditions |
   | D7 | Documentation | Missing/inaccurate docstrings, misleading comments, undocumented public API |
   | D8 | Convention Adherence | Compliance with `.kiro/steering/` rules, project naming conventions, import patterns |

2. WHEN a dimension has no findings for a file, THE Review_Agent SHALL explicitly record
   "No issues found" for that dimension rather than omitting it.

3. WHEN a finding is recorded, THE Review_Agent SHALL assign it one of the following severity
   levels based on the criteria below:

   | Severity | Label | Criteria |
   |---|---|---|
   | 🔴 | Critical | Data loss, incorrect output observable by end users, security vulnerability exploitable without authentication, or crash-class error in a core execution path |
   | 🟠 | High | Incorrect behavior under specific but realistic conditions, security vulnerability requiring authentication to exploit, or architectural boundary bypass |
   | 🟡 | Medium | Untested edge case in core logic, inaccurate documentation for a public API, or convention violation that affects maintainability |
   | 🔵 | Low | Cosmetic issue, trivial getter without docstring, or convention violation with no practical impact |

   Severity rules by dimension:
   - **D1**: 🔴 if data loss or incorrect output; 🟠 if incorrect under specific conditions; 🟡 otherwise.
   - **D2**: 🟠 if architectural boundary bypass; 🟡 if cohesion/coupling issue; 🔵 if cosmetic.
   - **D3**: 🔴 if crash on valid input; 🟠 if swallowed exception hides failure; 🟡 if missing guard on edge case.
   - **D4**: 🟠 if unbounded growth or blocking I/O in async path; 🟡 if unnecessary allocation; 🔵 if minor.
   - **D5**: 🟠 if untested security-sensitive or previously-buggy path; 🟡 if untested edge case; 🔵 if trivial wrapper.
   - **D6**: Per Requirement 9 criterion 2.
   - **D7**: 🟡 if inaccurate or missing docstring for public API; 🔵 if missing for private helper.
   - **D8**: Per Requirement 10 criterion 2.

---

### Requirement 4: Open Item Resolution

**User Story:** As a developer, I want the 7 open items from the Prior_Review to be explicitly
re-evaluated, so that I know whether they should be fixed, deferred further, or closed.

#### Acceptance Criteria

1. WHEN reviewing the file listed in the table below, THE Review_Agent SHALL re-evaluate the
   corresponding open item:

   | ID | File | Issue | Prior Status |
   |---|---|---|---|
   | N-04 | `nodes/base.py` | `setup()` not enforced before `process()` | 🔶 Partial |
   | N-06 | `nodes/ports.py` | `port.name` can drift from dict key | 🔶 Partial |
   | N-10 | `nodes/catalogue.py` | `find_compatible_nodes` O(N×M) | 🔶 Partial |
   | N-11 | `nodes/discovery.py` | Plugin module name collision in `_import_file` | ❌ Not Applied |
   | P-14 | `pipeline_cache.py` | Two cache formats, no migration path | 🔶 Partial |
   | P-23 | `ir/models.py` | `IRNode.config` mutable inside frozen model | 🔶 Partial |
   | B-31 | `ingestion.py` | TOCTOU race in `_save_hf_audio_sample` | ❌ Not Applied |

2. WHEN re-evaluating an open item, THE Review_Agent SHALL produce exactly one of three verdicts:
   - **Fix Now**: The defect pattern is present in the current code AND at least one of the
     following is true: (a) it can cause data loss, (b) it can produce incorrect output, (c) it
     is a security exposure, or (d) it can cause a crash-class error.
   - **Defer with Condition**: The defect pattern is present but none of the Fix Now criteria
     apply; the verdict entry SHALL document the specific condition under which the item must be
     re-evaluated (e.g., "re-evaluate if catalogue size exceeds 500 nodes").
   - **Close**: The defect pattern described in the open item is no longer observable in the
     current code, or the code path containing it has been removed.

3. IF the verdict is "Fix Now", THEN THE Review_Agent SHALL provide a fix proposal containing:
   (a) the file name, (b) the function or method name, (c) the line range or code block to
   change, and (d) the replacement logic or pseudocode.

4. IF the Review_Agent observes that the defect pattern described in a ✅ Prior_Review item is
   present in the current code, THEN THE Review_Agent SHALL record it as a new 🔴 Critical
   finding with the regression details.

5. IF the file for an open item cannot be read, THEN THE Review_Agent SHALL record the item as
   "Blocked" with the reason, and exclude it from the verdict count in the summary.

---

### Requirement 5: Prior Fix Verification

**User Story:** As a developer, I want confirmation that all 96 previously-fixed issues are still
correctly implemented, so that I can trust the codebase state.

#### Acceptance Criteria

1. THE Review_Agent SHALL verify the fix for every ✅ issue in the Prior_Review that belongs to
   the module group being reviewed.

2. WHEN verifying a fix, THE Review_Agent SHALL locate the specific code evidence cited in
   `docs/review/AUDIT.md` for that fix ID and confirm it is present in the current source file.

3. WHEN verifying a fix, THE Review_Agent SHALL confirm both conditions independently:
   (a) the fix code is present in the current source, AND (b) the exact text of the evidence
   cited in `docs/review/AUDIT.md` matches the actual code at the cited location. A fix SHALL
   NOT be recorded as verified unless both (a) and (b) hold.

4. IF both conditions in criterion 3 hold, THE Review_Agent SHALL record the fix as
   "Verified ✅" in the findings report, including the fix ID and the matched evidence text.

5. IF either condition in criterion 3 does not hold, THE Review_Agent SHALL record a new
   🔴 Critical finding containing: (a) the fix ID, (b) which condition failed, (c) the expected
   evidence text from AUDIT.md, and (d) the actual code found (or "not found").

6. THE Review_Agent SHALL produce a verification summary table at the end of each module group
   report with columns: Fix ID | File | Verified | Evidence Matched.

---

### Requirement 6: Findings Report Format

**User Story:** As a developer, I want all findings to follow a consistent format, so that I can
triage, track, and act on them without reformatting.

#### Acceptance Criteria

1. THE Review_Agent SHALL record every new finding using the following Finding Format:

   ```
   ### [GROUP-NN] Short title

   **File:** `path/to/file.py`
   **Severity:** 🔴/🟠/🟡/🔵
   **Dimension:** D1–D8
   **Status:** 🆕 New Finding

   **Description:**
   [What the problem is and why it matters]

   **Evidence:**
   [Specific line numbers, function names, or code snippets]

   **Proposed Fix:**
   [Concrete code change or design recommendation]
   ```

2. THE Review_Agent SHALL produce one findings report file per module group, saved to
   `docs/review/second-pass/NN-GROUP-NAME.md` where NN is the group number (01–05).

3. THE Review_Agent SHALL produce a consolidated summary report at
   `docs/review/second-pass/SUMMARY.md` after all five groups are complete.

4. THE SUMMARY.md SHALL contain:
   - Total new findings by severity (🔴 / 🟠 / 🟡 / 🔵 counts)
   - Total open items by verdict (Fix Now / Defer with Condition / Close / Blocked)
   - Total prior fixes verified vs. regressed
   - A prioritized fix roadmap for all "Fix Now" items, ordered 🔴 first then 🟠
   - A list of correctness properties identified for PBT

5. WHEN a module group has zero new findings, THE Review_Agent SHALL still produce an individual
   report file for that group containing an explicit "No new findings" section and the
   verification summary table from Requirement 5 criterion 6. Zero-finding groups SHALL NOT be
   merged into the summary only.

6. IF the report file for any module group cannot be written due to file system errors or
   permission issues, THE Review_Agent SHALL halt the entire review process and record the
   failure reason (file path, OS error) before stopping.

---

### Requirement 7: Correctness Properties

**User Story:** As a developer, I want the review to identify correctness properties that can be
expressed as property-based tests, so that the test suite catches regressions automatically.

#### Acceptance Criteria

1. THE Review_Agent SHALL identify at least one Correctness_Property per module group.

2. THE Review_Agent SHALL classify each Correctness_Property using the following taxonomy:

   | Type | Description |
   |---|---|
   | Invariant | A condition that must hold before and after an operation |
   | Round-Trip | `f(g(x)) == x` or `g(f(x)) == x` |
   | Idempotence | `f(f(x)) == f(x)` |
   | Metamorphic | A relationship between two related inputs/outputs |
   | Error Condition | Bad inputs must produce specific error types, not silent failures |

3. THE Review_Agent SHALL express each Correctness_Property as a testable statement in the form:
   `FOR ALL [input description], [operation] SHALL [expected outcome]`.

4. WHERE a Correctness_Property meets both of the following criteria, THE Review_Agent SHALL
   provide a skeleton Hypothesis test function: (a) the property type is Invariant, Round-Trip,
   Idempotence, or Metamorphic, AND (b) the input space can be described by a Hypothesis
   strategy (e.g., `st.text()`, `st.integers()`, `st.builds()`). The skeleton SHALL include the
   `@given` decorator, strategy arguments, and at least one `assert` statement.

5. THE Review_Agent SHALL flag the following as mandatory Correctness_Properties to verify:

   | Property | Type | Rationale |
   |---|---|---|
   | `stable_hash(a, b) != stable_hash(a_b_concat)` | Invariant | Separator collision fix (S-07) must hold |
   | `load_ir(dump_ir(ir)) == ir` | Round-Trip | IR serialization must be lossless |
   | `NodeRegistry.register` then `lookup` returns same class | Round-Trip | Registry correctness |
   | `PipelineCache.get(key)` after `put(key, val)` returns `val` | Round-Trip | Cache correctness |
   | `validate_node_config(valid_config)` does not raise | Invariant | Validation must accept valid input |
   | `conditions.evaluate(expr, ctx)` is deterministic | Idempotence | Same expr + ctx → same result |
   | `PluginManifest.from_toml(to_toml(manifest)) == manifest` | Round-Trip | Manifest serialization |
   | Bad archive member paths raise `ValueError` in installer | Error Condition | Zip-slip guard (PL-10) |

6. WHEN a mandatory Correctness_Property is already covered by an existing test in
   `unit_test/core/test_property_based.py`, THE Review_Agent SHALL verify the existing test is
   correct by confirming: (a) the `@given` strategy generates inputs that exercise the property,
   and (b) the assertion directly tests the stated outcome. If both hold, the property is marked
   "Covered ✅". If either fails, the property is marked "Insufficient ⚠️" and a corrected
   skeleton is proposed.

---

### Requirement 8: Test Coverage Gap Analysis

**User Story:** As a developer, I want to know which code paths in `app/core/` have no test
coverage, so that I can prioritize writing tests for the highest-risk gaps.

#### Acceptance Criteria

1. THE Review_Agent SHALL identify test coverage gaps by cross-referencing each source file
   `app/core/<name>.py` against `unit_test/core/test_<name>.py` (and any additional test files
   that import the source module). A gap exists when a public function, method, or error path
   in the source file has no corresponding test with an assertion targeting that specific behavior.

2. THE Review_Agent SHALL classify each gap by risk level:
   - **High Risk**: Untested error paths, concurrency code, security-sensitive code, or code
     that was previously buggy (per Prior_Review).
   - **Medium Risk**: Untested edge cases in core logic.
   - **Low Risk**: Untested convenience wrappers or trivial getters.

3. THE Review_Agent SHALL propose a specific test for every High Risk gap, including: (a) the
   test function signature, (b) the setup required, and (c) the assertion it should make.

4. THE Review_Agent SHALL complete the full gap analysis for the module group before verifying
   the previously-buggy code paths listed below. WHEN the full gap analysis is complete, THE
   Review_Agent SHALL verify that each path below is covered by a test in the corresponding
   `unit_test/core/test_<name>.py` file:

   | Code Path | Prior Bug | Expected Test |
   |---|---|---|
   | `nodes/discovery.py` `_import_file` | N-11 module collision | Test two plugins with same `nodes.py` filename |
   | `pipeline.py` cache key lookup | Prior fix #4 | Test DAG with non-sequential node IDs |
   | `utils/hash.py` `stable_hash` | S-07 separator collision | PBT: `stable_hash(a,b) != stable_hash(a+"\|"+b, c)` |
   | `plugins/installer.py` zip-slip | PL-10 | Test archive with `../` member path |
   | `provenance.py` `record()` | B-13 thread safety | Concurrent `record()` calls for same artifact |
   | `run_manager.py` `_artifacts` | B-01 lock | Concurrent `register_artifact()` calls |

---

### Requirement 9: Security Review

**User Story:** As a developer, I want a dedicated security pass over `app/core/`, so that
vulnerabilities introduced since the Prior_Review are caught before they reach production.

#### Acceptance Criteria

1. THE Review_Agent SHALL check every file in each module group for the following security
   concerns:

   | Concern | Description |
   |---|---|
   | Path Traversal | User-controlled paths used in file operations without sanitization |
   | SSRF | User-controlled URLs used in outbound HTTP requests |
   | Injection | User-controlled strings used in `eval`, `exec`, `subprocess`, or `ast.literal_eval` |
   | Credential Exposure | Secrets logged, printed, or included in error messages |
   | Race Conditions | TOCTOU patterns, unsynchronized shared state |
   | Dependency Confusion | Plugin install from untrusted index without integrity check |

2. WHEN a security concern is found, THE Review_Agent SHALL assign severity as follows:
   - 🔴 Critical: Path traversal, SSRF, or injection that is exploitable without authentication.
   - 🟠 High: Credential exposure, unguarded race condition, or security issue requiring
     authentication to exploit.
   - 🟡 Medium: Security concern that requires multiple prerequisites to exploit (e.g., attacker
     must control both the plugin index URL and a network position).
   - 🔵 Low: Informational finding with no realistic exploitation path.

3. THE Review_Agent SHALL verify that the following previously-fixed security issues remain fixed
   by confirming the specific guard code is present in the current source:

   | ID | Issue | Guard to Verify |
   |---|---|---|
   | B-26 | Webhook URL validation (SSRF) | URL scheme/host allowlist in `webhook.py` |
   | PL-07 | Temp dir cleanup (disk exhaustion) | `finally` block or context manager in `plugins/installer.py` |
   | PL-09 | Download size limit (resource exhaustion) | Byte-count check in `plugins/installer.py` |
   | PL-10 | Zip-slip / tar-slip path traversal | Member path sanitization in `plugins/installer.py` |
   | S-07 | `stable_hash` separator collision | Separator character in `utils/hash.py` |

4. THE Review_Agent SHALL check `conditions.py` for expression injection by verifying two
   independently testable properties:
   (a) Any expression string longer than 500 characters is rejected before evaluation, producing
       a defined error; if this guard is absent or bypassable, record a 🔴 Critical finding.
   (b) Any AST node type not in `_ALLOWED_NODE_TYPES` causes evaluation to be rejected; if the
       whitelist is absent or incomplete, record a 🔴 Critical finding.

---

### Requirement 10: Convention Adherence

**User Story:** As a developer, I want to know where `app/core/` deviates from the project's
documented conventions, so that the codebase stays consistent as it grows.

#### Acceptance Criteria

1. THE Review_Agent SHALL check every file against the following conventions from `.kiro/steering/`:

   | Convention | Source | Rule |
   |---|---|---|
   | Path resolution | `project-overview.md` | All paths go through `app/core/config.py` functions |
   | Plugin install target | `project-overview.md` | `plugins/` is managed by PluginManager; never edited directly |
   | Node base | `node-base.md` | All nodes extend `app.core.nodes.base.Node` |
   | Registry population | `node-registry.md` | Registry populated only by `AutoDiscovery` or `PluginManager` |
   | IR format | `pipeline-execution.md` | Canonical format is IR JSON; YAML is deprecated |
   | Env var access | `project-overview.md` | Env vars accessed via `app/core/config.py`, not `os.environ` directly |
   | Python venv | `python-venv.md` | All Python execution uses `venv/bin/python` |
   | Update protocol | `update-protocol.md` | Steering files and docs updated after every code change |

2. WHEN a convention violation is found, THE Review_Agent SHALL assign severity as follows:
   - 🔴 Critical: Violation creates a security vulnerability or causes incorrect runtime behavior.
   - 🟠 High: Violation bypasses an architectural boundary (e.g., direct `os.environ` access,
     direct `plugins/` directory write) without immediate incorrectness.
   - 🟡 Medium: Violation affects maintainability or consistency but has no runtime impact.
   - 🔵 Low: Cosmetic or minor violation with no practical impact.

3. IF the Prior_Review produced a ✅ fix for an issue, THEN THE Review_Agent SHALL verify that
   the matching steering file contains an updated row, section, or example traceable to that fix,
   AND the matching docs file contains an updated row, section, or example traceable to that fix.
   If either is absent, record a 🟡 Medium finding.

---

### Requirement 11: Documentation Completeness

**User Story:** As a developer, I want every public API in `app/core/` to have accurate
documentation, so that I can use the platform without reading implementation details.

#### Acceptance Criteria

1. THE Review_Agent SHALL verify that every public class and public method (those not prefixed
   with `_`) in each module group has a docstring.

2. WHEN verifying docstring accuracy, THE Review_Agent SHALL confirm all three of the following:
   (a) parameter names and types in the docstring match the current function signature,
   (b) the documented return value and exceptions match the current implementation,
   (c) the docstring does not describe behavior that was changed by a Prior_Review fix (i.e.,
       it does not reference the old, incorrect behavior).

3. THE Review_Agent SHALL check that the following documentation files are consistent with the
   current source code:

   | Doc File | Module Group |
   |---|---|
   | `docs/NODE_SYSTEM.md` | G1 — Node System |
   | `docs/PIPELINE_EXECUTION.md` | G2 — Pipeline & IR |
   | `docs/BACKEND_CORE.md` | G3 — Backend Services |
   | `docs/PLUGIN_GUIDE.md` | G4 — Plugin Ecosystem |
   | `docs/SDK_AND_CLI.md` | G5 — SDK & Utilities |

4. WHEN a doc file is inconsistent with the source (doc says X, code does Y), THE Review_Agent
   SHALL record the specific discrepancy as a 🟡 Medium finding. IF the Review_Agent is unable
   to write the finding to the output report file (e.g., permission error, disk full), THE
   Review_Agent SHALL halt the entire review process and record the OS error before stopping.

5. THE Review_Agent SHALL verify that `docs/KNOWN_ISSUES.md` accurately reflects the current
   state: all Resolved items must be confirmed fixed in the current source, and all Active items
   must still be present as described.

---

### Requirement 12: Review Completion Criteria

**User Story:** As a developer, I want a clear definition of "done" for this review, so that I
know when the review is complete and the codebase is in a known state.

#### Acceptance Criteria

1. THE Review SHALL be considered complete only when all five module group reports exist at
   `docs/review/second-pass/01-NODE-SYSTEM.md`, `02-PIPELINE-IR.md`, `03-BACKEND-SERVICES.md`,
   `04-PLUGIN-ECOSYSTEM.md`, and `05-SDK-UTILITIES.md`.

2. THE Review SHALL be considered complete only when `docs/review/second-pass/SUMMARY.md` exists
   and contains all required sections from Requirement 6 criterion 4.

3. THE Review SHALL be considered complete only when every Open_Item from Requirement 4 has a
   recorded verdict of Fix Now, Defer with Condition, Close, or Blocked.

4. THE Review SHALL be considered complete only when every mandatory Correctness_Property from
   Requirement 7 criterion 5 has been evaluated and marked Covered ✅, Insufficient ⚠️, or
   proposed as a new skeleton test.

5. THE Review SHALL be considered complete only when `docs/review/second-pass/INDEX.md` exists
   and lists: (a) all five report file paths, (b) total new findings by severity, and (c) overall
   fix status (verified count vs. regressed count).

6. IF a 🔴 Critical finding is discovered during the review of a module group, THEN THE
   Review_Agent SHALL immediately append the finding to the current module group report AND add
   a "CRITICAL HALT" entry to `docs/review/second-pass/INDEX.md` containing the finding ID,
   file, and one-line description. THE Review_Agent SHALL then continue to the next module group
   rather than stopping the entire review.

7. THE Review_Agent SHALL update `docs/KNOWN_ISSUES.md` with any new Active issues discovered
   during the review. Each new entry SHALL contain exactly four fields: (a) a unique ID following
   the existing ID scheme, (b) a one-sentence description of the issue, (c) the file path and
   line number where the issue originates, and (d) the severity level.
