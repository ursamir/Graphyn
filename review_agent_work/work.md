## Plan

**What the architectural review already covered (skip in functional review):**
- Bounded context ownership
- Import direction / RULE 1
- Coupling level / extraction readiness
- File identity / responsibility clarity
- Already-resolved issues in `MASTER_ISSUE_REGISTRY.md`

**What the functional review must cover per file:**
1. Does the implementation actually do what the docstring/contract says?
2. Are all code paths reachable and correct?
3. Are error conditions handled, surfaced, and recoverable?
4. Are there silent failures (swallowed exceptions, wrong return values, wrong types)?
5. Are config validators actually enforced at runtime?
6. Are edge cases handled (empty inputs, None, zero-length audio, missing files, concurrent access)?
7. Do async/sync boundaries work correctly?
8. Are there race conditions or shared mutable state bugs?
9. Does the node's `process()` honor its declared port types at runtime?
10. Are there performance traps (blocking I/O in async, unbounded memory, N+1 patterns)?

**File groupings** (run one prompt per group — keeps context tight):

| # | Group | Files |
|---|---|---|
| 1 | IR Core | `ir/models.py`, `ir/loader.py`, `ir/yaml_shim.py`, `ir/migrate.py` |
| 2 | Node Base | `nodes/base.py`, `nodes/ports.py`, `nodes/config.py`, `nodes/retry.py`, `nodes/metadata.py`, `nodes/observers.py`, `nodes/compat.py`, `nodes/errors.py` |
| 3 | Registry & Discovery | `nodes/registry.py`, `nodes/discovery.py`, `nodes/catalogue.py`, `registry_runtime.py` |
| 4 | Plugin Ecosystem | `plugins/manager.py`, `plugins/loader.py`, `plugins/installer.py`, `plugins/store.py`, `plugins/manifest.py`, `plugins/dependencies.py`, `plugins/errors.py`, `plugins/index.py` |
| 5 | Planner | `planner.py` |
| 6 | Execution Runtime | `orchestrator.py`, `node_executor.py`, `executor.py`, `conditions.py`, `events.py`, `runtime_backend.py` |
| 7 | Observability & Storage | `checkpoint.py`, `pipeline_cache.py`, `artifact_store.py`, `artifact_serializer.py`, `run_journal.py`, `run_control.py`, `provenance.py`, `logger.py` |
| 8 | Platform Infra | `config.py`, `validation.py`, `webhook.py`, `errors.py`, `utils/hash.py` |
| 9 | SDK & CLI | `sdk.py`, `cli/main.py` |
| 10 | API | `api/main.py`, `api/routers/pipelines.py`, `api/routers/runs.py`, `api/routers/artifacts.py`, `api/routers/run_control.py`, `api/routers/nodes.py`, `api/routers/plugins.py` |
| 11 | MCP | `mcp/server.py`, `mcp/tool_registry.py`, `mcp/auth.py`, `mcp/handlers/*.py` |
| 12 | Domain & Models | `domain/ingestion.py`, `domain/project_manager.py`, `domain/quality_checker.py`, `models/*.py` |
| 13 | Audio Plugins (batch 1) | `audio_classifier`, `audio_conditioner`, `audio_event_detector`, `audio_exporter`, `audio_generator`, `audio_quality_gate` |
| 14 | Audio Plugins (batch 2) | `alignment_node`, `audio_annotator`, `augmentation_pipeline`, `dataset_ingest`, `feature_frontend`, `input`, `output` |
| 15 | Audio Plugins (batch 3) | `segmenter`, `speaker_separator`, `speech_enhancer`, `speech_synthesizer`, `stream_ingest`, `stream_processor`, `voice_converter`, `environment_simulator` |
| 16 | Common Plugins | All 11 `PluginPackage/Common/` nodes |

---

## The Prompt

This is the single prompt template. Replace `{GROUP_NAME}` and `{FILE_LIST}` for each run. Everything else stays identical — it carries full context and builds on the architectural review.

```
## Graphyn Platform — Functional Correctness Review

You are a Senior Engineer conducting a **deep functional correctness review** of the Graphyn platform.

A prior **architectural review** has already been completed. Its findings are in `review_agent_work/Output.md`.
You must read that file first. Do NOT re-report architectural findings already documented there.
Your job is orthogonal: you are verifying that the code **works correctly**, not that it is structured correctly.

---

## MANDATORY FIRST STEP — READ BEFORE WRITING A SINGLE FINDING

Read these files completely before beginning analysis:

**Context (read once, carry forward):**
- `review_agent_work/Output.md` — prior architectural findings; do not re-report
- `docs/MASTER_ISSUE_REGISTRY.md` — resolved issues; do not re-report
- `docs/ARCHITECTURE.md` — platform intent
- `docs/PIPELINE_EXECUTION.md` — execution contract
- `docs/NODE_SYSTEM.md` — node contract

**Files under review for this session — {GROUP_NAME}:**
{FILE_LIST}

Read every file in the list completely. Do not begin analysis until all are read.

---

## YOUR ROLE

You are NOT doing:
- Architectural boundary analysis (already done)
- Style or formatting review
- Re-reporting resolved issues

You ARE doing:
- Verifying every function does what its docstring/contract claims
- Finding silent failures, wrong return values, swallowed exceptions
- Finding edge cases that crash or produce wrong output
- Finding async/sync boundary bugs
- Finding race conditions and shared mutable state bugs
- Finding config validators that don't actually validate
- Finding port type contracts that are declared but not enforced at runtime
- Finding performance traps (blocking I/O in async, unbounded memory, N+1)
- Finding error paths that are unreachable, incomplete, or misleading
- Finding test-hostile patterns (hidden global state, untestable side effects)

---

## FUNCTIONAL REVIEW DIMENSIONS

For every function/method/class evaluate:

1. **Contract Honesty** — does the implementation match the docstring?
2. **Error Handling Completeness** — are all failure modes caught, surfaced, and recoverable?
3. **Silent Failure Risk** — can the function return wrong data without raising?
4. **Edge Case Coverage** — None, empty, zero-length, concurrent, missing file, wrong type
5. **Async Correctness** — blocking calls in async context? missing awaits? wrong executor?
6. **State Safety** — shared mutable state accessed without locks? class-level state leaking between calls?
7. **Type Safety at Runtime** — declared types enforced? or just documentation?
8. **Resource Management** — file handles, connections, memory — properly closed/released?
9. **Performance Correctness** — O(n²) where O(n) expected? unbounded accumulation?
10. **Testability** — can this be unit tested without a full platform? hidden dependencies?

---

## OUTPUT FORMAT

For every finding use this exact structure:

--------------------------------------------------------------------
FILE:        <path>
FUNCTION:    <class.method or function name>
CATEGORY:    <one of: Silent Failure | Error Handling | Edge Case | Async Bug |
              State Bug | Type Safety | Resource Leak | Performance | Contract Mismatch |
              Testability>
SEVERITY:    [CRITICAL | HIGH | MEDIUM | LOW]
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
One sentence from the docstring or function signature.

WHAT IT ACTUALLY DOES:
What the implementation actually does, including the specific lines.

THE BUG / RISK:
Precise description of the failure mode, wrong behavior, or risk.

EVIDENCE:
Specific line numbers, variable names, or code snippets.

REPRODUCTION SCENARIO:
Concrete input or sequence of calls that triggers the issue.

IMPACT:
What breaks at runtime. Data loss? Silent wrong result? Crash? Hang?

FIX DIRECTION:
Minimal, concrete fix. Code snippet if short enough.
--------------------------------------------------------------------

For each file also provide a **FUNCTIONAL HEALTH SUMMARY**:

FUNCTIONAL HEALTH SUMMARY — <filename>
Overall Risk:      [LOW | MEDIUM | HIGH | CRITICAL]
Silent Failures:   <count>
Error Handling:    [COMPLETE | PARTIAL | MISSING]
Async Safety:      [SAFE | UNSAFE | N/A]
State Safety:      [SAFE | UNSAFE | N/A]
Resource Safety:   [SAFE | UNSAFE | N/A]
Test Hostile:      [YES | NO | PARTIAL]
Top Risk:          <one sentence>

---

## REVIEW PRINCIPLES

1. The code is the source of truth. Comments and docstrings may lie.
2. Assume the worst-case caller: None inputs, empty collections, concurrent calls, missing env vars.
3. A function that returns wrong data silently is worse than one that raises.
4. Async bugs are often invisible in tests but catastrophic in production.
5. Shared mutable state at class or module level is a concurrency bug waiting to happen.
6. If a config validator accepts invalid values, the error will surface deep in process() with a confusing traceback.
7. Do not re-report architectural issues. Focus on runtime behavior.
8. Be precise: cite line numbers and variable names.
9. If a finding is already in `review_agent_work/Output.md` or `docs/MASTER_ISSUE_REGISTRY.md`, skip it.
10. After completing all findings, append new issues to `docs/MASTER_ISSUE_REGISTRY.md` and `docs/KNOWN_ISSUES.md` following the update protocol in `.kiro/steering/update-protocol.md`.

---

## FINAL OBJECTIVE

Determine whether the code in this group **actually works correctly** under realistic conditions, not just under the happy path. Produce a prioritized list of functional bugs and risks that a developer can act on immediately.
```

---

**How to use it:** For each run, substitute the group name and file list. For example, Group 5 (Planner) becomes:

```
**Files under review for this session — Planner:**
- `app/core/planner.py`
```

And Group 13 (Audio Plugins batch 1) becomes:

```
**Files under review for this session — Audio Plugins Batch 1:**
- `PluginPackage/Audio/audio_classifier/nodes.py`
- `PluginPackage/Audio/audio_conditioner/nodes.py`
- `PluginPackage/Audio/audio_event_detector/nodes.py`
- `PluginPackage/Audio/audio_exporter/nodes.py`
- `PluginPackage/Audio/audio_generator/nodes.py`
- `PluginPackage/Audio/audio_quality_gate/nodes.py`
```

The context files (Output.md, MASTER_ISSUE_REGISTRY.md, ARCHITECTURE.md, etc.) stay in every prompt so each session knows what's already been found and doesn't repeat it. The findings from each session get written back to `MASTER_ISSUE_REGISTRY.md` and `KNOWN_ISSUES.md` per the update protocol, so by session 16 the agent has a running log of everything found across all sessions.