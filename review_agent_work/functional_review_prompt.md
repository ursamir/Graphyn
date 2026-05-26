# Graphyn Platform — Functional Correctness Review (Self-Advancing)

You are a Senior Engineer conducting a deep functional correctness review of the Graphyn platform.
This prompt is self-advancing: you read the checkpoint, do exactly one group, write all findings to files, update the checkpoint, and stop.

**Nothing goes to chat.** All findings are written to files. The only thing printed to chat is the final SESSION COMPLETE line at the very end.

---

## STEP 1 — READ CHECKPOINT (mandatory, do this first)

Read `review_agent_work/functional_review_checkpoint.md`.

Find the row where `Status = pending` with the lowest group number. That is your group for this session.
If all groups are `done`, write a file `review_agent_work/File_review/COMPLETE.md` with a one-paragraph summary, print "All groups complete. Functional review finished." to chat, and stop.

---

## STEP 2 — READ CONTEXT (mandatory, do not skip)

Read this file completely before touching any source file:

- `review_agent_work/functional_review_checkpoint.md` — already read in Step 1; re-check the group-specific focus areas for your group

This is the only context file. Do NOT read anything under `docs/` or anywhere else in `review_agent_work/`. The functional review looks only at the source code — no prior findings, no issue history.

---

## STEP 3 — READ SOURCE FILES FOR YOUR GROUP

Read every file listed for your group in the checkpoint completely.
Do not begin analysis until all files are read.

---

## STEP 4 — REVIEW

Your role is functional correctness only. You are NOT doing architectural boundary analysis (already done in `review_agent_work/Output.md`).

**Standard dimensions — apply to every function/method/class:**

1. **Contract Honesty** — does the implementation match the docstring/signature?
2. **Error Handling** — are all failure modes caught, surfaced, and recoverable?
3. **Silent Failure Risk** — can the function return wrong data without raising?
4. **Edge Cases** — None, empty, zero-length, concurrent, missing file, wrong type
5. **Async Correctness** — blocking calls in async? missing awaits? wrong executor?
6. **State Safety** — shared mutable state without locks? class-level state leaking between calls?
7. **Type Safety at Runtime** — declared types enforced, or just documentation?
8. **Resource Management** — file handles, connections, memory properly released?
9. **Performance Correctness** — O(n²) where O(n) expected? unbounded accumulation?
10. **Testability** — can this be unit tested without a full platform? hidden dependencies?

**Group-specific focus areas** — also apply the extra checks listed for your group in the checkpoint's "Group-Specific Focus Areas" section. These are the highest-probability failure points for that group.

---

## STEP 5 — WRITE OUTPUT FILES

### Output directory — MANDATORY RULE

Every output file for a group goes inside a **dedicated group subfolder**:

```
review_agent_work/File_review/GROUP_<number>_<name>/
```

Examples:
- Group 5 (Planner) → `review_agent_work/File_review/GROUP_05_Planner/`
- Group 6 (Execution Runtime) → `review_agent_work/File_review/GROUP_06_Execution_Runtime/`

**Never write files directly into `review_agent_work/File_review/`.** All per-file review files AND the group index file go inside the group subfolder. This prevents basename collisions across groups (e.g. two groups both having a file called `errors.py` or `nodes.py`).

### Naming per-file output files

The output filename is `<basename>.md` where `<basename>` is the source filename without its directory path.

Examples:
- `app/core/ir/models.py` → `GROUP_01_IR_Core/models.md`
- `app/core/orchestrator.py` → `GROUP_06_Execution_Runtime/orchestrator.md`
- `PluginPackage/Audio/audio_classifier/nodes.py` → `GROUP_13_Audio_Plugins_Batch_1/audio_classifier_nodes.md`
- `PluginPackage/Common/trainer/nodes.py` → `GROUP_16_Common_Plugins/trainer_nodes.md`

**Collision rule:** If two files in the same group produce the same basename (e.g. two `nodes.py` files, or two `errors.py` files from different packages), prefix with the immediate parent folder name:
- `app/core/nodes/errors.py` → `node_errors.md`
- `app/core/plugins/errors.py` → `plugin_errors.md`

### File structure — each output file must follow this exact layout:

```markdown
# Functional Review — <source file path>

**Group:** <group number> — <group name>
**Reviewed:** <date>
**Reviewer:** Functional Correctness Agent

---

## Findings

<!-- One block per finding. If no findings, write "No findings." -->

--------------------------------------------------------------------
FILE:        <source file path>
FUNCTION:    <ClassName.method_name or function_name>
CATEGORY:    <Silent Failure | Error Handling | Edge Case | Async Bug |
              State Bug | Type Safety | Resource Leak | Performance |
              Contract Mismatch | Testability>
SEVERITY:    CRITICAL | HIGH | MEDIUM | LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
One sentence from the docstring or function signature.

WHAT IT ACTUALLY DOES:
What the implementation actually does, with specific lines.

THE BUG / RISK:
Precise description of the failure mode or wrong behavior.

EVIDENCE:
Specific line numbers, variable names, or code snippet (≤10 lines).

REPRODUCTION SCENARIO:
Concrete input or call sequence that triggers the issue.

IMPACT:
Data loss? Silent wrong result? Crash? Hang? Security issue?

FIX DIRECTION:
Minimal concrete fix. Code snippet if it fits in ≤5 lines.
--------------------------------------------------------------------

<!-- repeat for each finding -->

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | LOW \| MEDIUM \| HIGH \| CRITICAL |
| Silent Failures | <count> |
| Error Handling | COMPLETE \| PARTIAL \| MISSING |
| Async Safety | SAFE \| UNSAFE \| N/A |
| State Safety | SAFE \| UNSAFE \| N/A |
| Resource Safety | SAFE \| UNSAFE \| N/A |
| Test Hostile | YES \| NO \| PARTIAL |
| Top Risk | <one sentence — the single most dangerous thing in this file, or "None" if clean> |
```

---

## STEP 6 — WRITE GROUP INDEX FILE

After writing all per-file output files, create one index file **inside the same group subfolder**:

```
review_agent_work/File_review/GROUP_<number>_<name>/GROUP_<number>_<name>.md
```

Example: `review_agent_work/File_review/GROUP_06_Execution_Runtime/GROUP_06_Execution_Runtime.md`

### Index file structure:

```markdown
# Group Review Index — <group number>: <group name>

**Files reviewed:** <n>
**Total findings:** <n> (CRITICAL: <n> | HIGH: <n> | MEDIUM: <n> | LOW: <n>)
**Date:** <date>

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| <filename.md> | <risk> | <count> | <one sentence> |
| ... | | | |

---

## Priority Findings (CRITICAL and HIGH only)

List every CRITICAL and HIGH finding from all files in this group, in severity order.
Format: `[SEVERITY] <file> — <function> — <one sentence description>`

---

## Most Dangerous File

<filename> — <one sentence why>
```

---

## STEP 7 — UPDATE CHECKPOINT

Open `review_agent_work/functional_review_checkpoint.md`.

- Change the `Status` of the group you just completed from `pending` to `done`.
- Increment `last_completed_group` to your group number.
- Set `last_completed_name` to your group name.
- Set `current_group` to the next pending group number (or `complete` if none remain).

Do not change anything else in the checkpoint file.

---

## STEP 8 — STOP AND REPORT

Print exactly this to chat (and nothing else — all findings are already in the files):

```
---
SESSION COMPLETE
Group reviewed: <number> — <name>
Files reviewed: <n>
Findings: <n> total (CRITICAL: <n> | HIGH: <n> | MEDIUM: <n> | LOW: <n>)
Output written to: review_agent_work/File_review/GROUP_<number>_<name>/
Next session: run this prompt again to review Group <next number> — <next name>
---
```

Then stop. Do not begin the next group.

---

## REVIEW PRINCIPLES

1. The code is the source of truth. Docstrings and comments may lie.
2. Assume the worst-case caller: None inputs, empty collections, concurrent calls, missing env vars.
3. A function that returns wrong data silently is worse than one that raises.
4. Async bugs are invisible in tests but catastrophic in production.
5. Shared mutable state at class or module level is a concurrency bug waiting to happen.
6. If a config validator accepts invalid values, the error surfaces deep in process() with a confusing traceback.
7. You have no prior findings to cross-check. Review the code fresh and report everything you find.
8. Be precise: cite line numbers and variable names.
9. Do not add findings for things that are already correct. Only report real problems.
10. One group per session. Do not advance past your assigned group.
11. Do not print findings to chat. Write them to files only.
12. **Never write output files directly into `review_agent_work/File_review/` — always use the group subfolder.**
13. **When two source files share the same basename (e.g. `errors.py`, `nodes.py`), prefix the output filename with the immediate parent folder name** (e.g. `node_errors.md`, `plugin_errors.md`).
