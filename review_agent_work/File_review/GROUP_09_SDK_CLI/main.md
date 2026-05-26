# Functional Review — app/cli/main.py

**Group:** 9 — SDK & CLI
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/cli/main.py
FUNCTION:    main
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Entry point: parse args and dispatch to the appropriate subcommand function.

WHAT IT ACTUALLY DOES:
main() calls parser.parse_args() and then args.func(args) with no try/except around either call.
There is no KeyboardInterrupt handler anywhere in the CLI.

THE BUG / RISK:
If the user presses Ctrl+C during a long-running pipeline execution (cmd_run), Python raises
KeyboardInterrupt. Because cmd_run catches only `Exception` (not BaseException), the
KeyboardInterrupt propagates up through args.func(args) and through main() to the Python
runtime, which prints a raw traceback:
    ^CTraceback (most recent call last):
      ...
    KeyboardInterrupt
This is a poor user experience and may leave the run in an indeterminate state in the run
journal (status never set to "cancelled" or "failed").

EVIDENCE:
Lines 1406–1409 (main.py):
    def main():
        parser = build_parser()
        args = parser.parse_args()
        args.func(args)   # ← no KeyboardInterrupt handling

Lines 353–358 (cmd_run, graph+seed path):
    try:
        get_backend().execute(...)
    except Exception as exc:   # ← KeyboardInterrupt is BaseException, not caught here
        print(f"\nPipeline failed: {exc}", file=sys.stderr)
        sys.exit(1)

REPRODUCTION SCENARIO:
    graphyn run --graph my_pipeline.graph.json
    # Press Ctrl+C during execution
    # → raw KeyboardInterrupt traceback printed to terminal

IMPACT:
Poor UX: raw traceback instead of clean "Interrupted." message. Run journal may be left with
status "running" permanently.

FIX DIRECTION:
    def main():
        parser = build_parser()
        args = parser.parse_args()
        try:
            args.func(args)
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            sys.exit(130)

--------------------------------------------------------------------
FILE:        app/cli/main.py
FUNCTION:    cmd_run
CATEGORY:    Contract Mismatch
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Execute a pipeline synchronously and print logs to stdout."
When --seed is provided, rebuilds the IR with the new seed and calls get_backend().execute()
directly.

WHAT IT ACTUALLY DOES:
The seed-override path (lines 325–358 for --graph, lines 390–425 for --config) calls
get_backend().execute() directly, bypassing Pipeline.run() entirely. This means:
1. No RunManager is created — run is not persisted to the run journal.
2. No ArtifactCollection is built — artifacts are not stored.
3. self._last_run_id is never set on the pipeline object (irrelevant for CLI, but the run is
   invisible to `graphyn runs list`).

THE BUG / RISK:
A user who runs `graphyn run --graph foo.json --seed 99` will see no entry in
`graphyn runs list` and no artifacts in `graphyn artifacts list`. The run is completely
invisible to the platform's observability layer. This is a silent behavioral divergence between
the seeded and non-seeded code paths.

EVIDENCE:
Lines 325–358 (main.py, --graph + --seed path):
    get_backend().execute(
        new_graph,
        logger=logger,
        parallel=parallel,
        ...
        # ← no run_manager argument
    )

Lines 353–358 (non-seeded path):
    pipeline.run(
        logger=logger,
        ...
        # ← Pipeline.run() creates RunManager internally

REPRODUCTION SCENARIO:
    graphyn run --graph foo.json --seed 42
    graphyn runs list
    # → no entry for the seeded run

IMPACT:
Seeded runs are invisible to the run journal and artifact store. Users cannot replay, inspect
logs, or retrieve artifacts from seeded runs.

FIX DIRECTION:
Replace the direct get_backend().execute() call with a Pipeline.run() call after mutating the
pipeline's IR seed, or use run_with_manager() with a pre-built RunManager:
    pipeline._graph_ir = new_graph
    pipeline.run(logger=logger, parallel=parallel, ...)

--------------------------------------------------------------------
FILE:        app/cli/main.py
FUNCTION:    cmd_artifacts_replay
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Re-execute a pipeline using the graph.json stored for a run."

WHAT IT ACTUALLY DOES:
Constructs graph_path as os.path.join(_runs_dir(), args.run_id, "graph.json") and checks
os.path.isfile(graph_path). If the run_id directory does not exist at all (invalid run ID),
os.path.isfile() returns False and the error message says "graph.json not found for run
{args.run_id!r}: {graph_path}". This is correct but the error message does not distinguish
between "run ID does not exist" and "run exists but graph.json was not saved".

More critically: there is no prefix-matching logic (unlike cmd_runs_logs which supports partial
run ID matching). A user who provides a partial run ID gets a confusing "graph.json not found"
error instead of "run not found".

THE BUG / RISK:
Inconsistent UX: cmd_runs_logs supports partial run ID matching, cmd_artifacts_replay does not.
A user who uses a partial run ID with replay gets a misleading error message.

EVIDENCE:
Lines 840–852 (main.py):
    graph_path = os.path.join(str(_runs_dir()), args.run_id, "graph.json")
    if not os.path.isfile(graph_path):
        print(
            f"Error: graph.json not found for run {args.run_id!r}: {graph_path}",
            ...
        )
        sys.exit(1)

Compare cmd_runs_logs lines 693–703 which has prefix-matching logic.

REPRODUCTION SCENARIO:
    graphyn artifacts replay abc123   # partial prefix of a valid run ID
    # → "Error: graph.json not found for run 'abc123': ..." (misleading)

IMPACT:
Confusing error message. User cannot use partial run IDs with replay even though logs supports
it.

FIX DIRECTION:
Apply the same prefix-matching logic from cmd_runs_logs before constructing graph_path, or
factor the prefix resolution into a shared helper.

--------------------------------------------------------------------
FILE:        app/cli/main.py
FUNCTION:    _load_logs
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Return the log entries for a run, or None if not found."

WHAT IT ACTUALLY DOES:
Opens logs_path with `open(logs_path, "r")` (no encoding specified, line 84) and calls
json.load(). If the file exists but contains invalid JSON (e.g. truncated due to a crash), the
json.JSONDecodeError propagates uncaught to cmd_runs_logs, which has no handler for it.

THE BUG / RISK:
A corrupted logs.json file causes an unhandled json.JSONDecodeError traceback in the CLI instead
of a clean error message. The file handle is closed by the `with` block, so no resource leak,
but the user sees a raw Python traceback.

EVIDENCE:
Lines 84–86 (main.py):
    with open(logs_path, "r") as f:
        return json.load(f)   # ← no try/except for JSONDecodeError

REPRODUCTION SCENARIO:
    # Truncate a logs.json file to simulate a crash mid-write
    echo '{"incomplete":' > ~/.graphyn/workspace/runs/run-001/logs.json
    graphyn runs logs run-001
    # → json.JSONDecodeError traceback

IMPACT:
Raw traceback instead of clean error message. No data loss.

FIX DIRECTION:
    try:
        with open(logs_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None   # caller already handles None gracefully

--------------------------------------------------------------------
FILE:        app/cli/main.py
FUNCTION:    cmd_validate (YAML path)
CATEGORY:    Contract Mismatch
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate a pipeline YAML file or IR JSON graph file. The docstring lists 7 validation steps for
IR JSON graphs.

WHAT IT ACTUALLY DOES:
The YAML validation path (lines 599–634) performs only steps 1–4 (parse, schema, node type
resolution, config validation). It does NOT perform:
- Step 5: edge port existence check
- Step 6: edge port type compatibility check
- Step 7: cycle detection

THE BUG / RISK:
`graphyn validate --config foo.yaml` reports "✓ Valid pipeline" for a YAML file that has
invalid port connections or cycles. The IR JSON path (`--graph`) performs all 7 checks. This
inconsistency means YAML pipelines can pass validation but fail at runtime with confusing errors.

EVIDENCE:
Lines 599–634 (main.py): YAML path only calls load_yaml_with_deprecation(), registry.get_class(),
and Config.model_validate(). No port or cycle checks.

Lines 429–596 (main.py): IR path performs all 7 steps including port and cycle checks.

REPRODUCTION SCENARIO:
    # YAML pipeline with a cycle: node_a → node_b → node_a
    graphyn validate --config cyclic.yaml
    # → "✓ Valid pipeline — 2 node(s)" (cycle not detected)
    graphyn run --config cyclic.yaml
    # → runtime error: cycle detected

IMPACT:
False positive validation for YAML pipelines with cycles or invalid port connections. Users
trust the validation result and are surprised by runtime failures.

FIX DIRECTION:
After loading the GraphIR from YAML, apply the same steps 5–7 as the IR path, or call
Pipeline._from_ir(graph).validate() which already performs structural + topology checks.

--------------------------------------------------------------------
FILE:        app/cli/main.py
FUNCTION:    cmd_validate (IR path) — node instantiation
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Step 5 & 6: port existence + type compatibility checks.

WHAT IT ACTUALLY DOES:
Node instantiation (lines 502–510) uses stable_hash(graph.metadata.seed, node.node_type, 0)
with a hardcoded third argument of 0 for all nodes. This means all nodes in the graph get the
same seed offset (0), which may cause issues if nodes use the seed for initialization that
requires uniqueness. More importantly, if node instantiation fails for any node, that node is
added to errors but execution continues — edges referencing that node are silently skipped
(lines 514–516: `if src_inst is None or dst_inst is None: continue`).

THE BUG / RISK:
If a node fails to instantiate, all edges connected to it are silently skipped without any error
message. The validation report says "N error(s)" for the instantiation failure but does not
mention that port/type checks for those edges were skipped. A user may fix the instantiation
error and discover new port errors that were previously hidden.

EVIDENCE:
Lines 502–510 (main.py):
    node_seed = stable_hash(graph.metadata.seed, node.node_type, 0) % (2 ** 32)
    instance = node_class(config=..., seed=node_seed)
    node_instances[node.id] = instance

Lines 514–516 (main.py):
    if src_inst is None or dst_inst is None:
        continue   # ← silent skip, no error appended for the skipped edge

REPRODUCTION SCENARIO:
    # Graph: node_a (fails to instantiate) → node_b (valid)
    # Edge: node_a.output → node_b.input (wrong port name)
    graphyn validate --graph foo.graph.json
    # → reports "Failed to instantiate node_a" but NOT the port error on the edge

IMPACT:
Incomplete validation report. Port errors on edges connected to failed nodes are silently
omitted.

FIX DIRECTION:
When skipping an edge due to missing instance, append a note:
    errors.append(
        f"  ⚠ Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
        f"skipped (node instantiation failed)"
    )

--------------------------------------------------------------------
FILE:        app/cli/main.py
FUNCTION:    cmd_run (seed override path — code duplication)
CATEGORY:    Testability
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Execute a pipeline synchronously.

WHAT IT ACTUALLY DOES:
The seed-override logic (build new GraphIR, call get_backend().execute()) is duplicated
verbatim for both the --graph path (lines 325–358) and the --config path (lines 390–425).
The two blocks are identical except for the pipeline loading step. This is ~60 lines of
duplicated code.

THE BUG / RISK:
Any fix to the seed-override path (e.g. the HIGH finding above about missing RunManager) must
be applied in two places. The duplication has already caused the RunManager omission to appear
in both paths.

EVIDENCE:
Lines 325–358 (--graph + seed) and lines 390–425 (--config + seed): identical logic.

REPRODUCTION SCENARIO:
Fix the RunManager bug in the --graph path but forget the --config path → inconsistent behavior.

IMPACT:
Maintenance hazard. Not a runtime bug today, but increases the probability of future divergence.

FIX DIRECTION:
Extract a helper:
    def _run_with_seed(graph, seed, logger, **kwargs):
        new_graph = GraphIR(...)
        pipeline = Pipeline._from_ir(new_graph)
        pipeline.run(logger=logger, **kwargs)

--------------------------------------------------------------------
FILE:        app/cli/main.py
FUNCTION:    _list_runs
CATEGORY:    Performance
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Return a list of run metadata dicts sorted by created_at descending."

WHAT IT ACTUALLY DOES:
Calls os.listdir() on the runs directory and opens meta.json for every entry. For a workspace
with thousands of runs, this reads thousands of files synchronously on every `graphyn runs list`
invocation.

THE BUG / RISK:
O(n) file reads where n = number of runs. With 10,000 runs, this could take several seconds.
No pagination or limit is applied.

EVIDENCE:
Lines 64–75 (main.py):
    for run_id in os.listdir(runs_dir_path):
        meta_path = os.path.join(runs_dir_path, run_id, "meta.json")
        ...
        with open(meta_path, "r") as f:
            meta = json.load(f)

REPRODUCTION SCENARIO:
    # Workspace with 10,000 runs
    graphyn runs list
    # → reads 10,000 meta.json files before printing anything

IMPACT:
Slow CLI for large workspaces. No crash, but poor UX.

FIX DIRECTION:
Add a --limit N argument (default 50) and stop reading after N entries, or read only the most
recently modified directories using os.scandir() with stat().

--------------------------------------------------------------------
FILE:        app/cli/main.py
FUNCTION:    cmd_runs_logs
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Print log entries for a specific run, with partial run ID prefix matching.

WHAT IT ACTUALLY DOES:
The prefix-matching logic (lines 694–703) only runs if the exact run_id directory does NOT
exist. If the exact directory exists, it skips prefix matching and proceeds directly to
_load_logs(). This is correct. However, if the runs directory itself does not exist (first run
ever, or GRAPHYN_PROJECT_DIR misconfigured), the code falls through to _load_logs() with the
original run_id, which returns None, and the error message says "No logs found for run: X"
instead of "runs directory does not exist".

EVIDENCE:
Lines 693–706 (main.py):
    if not os.path.isdir(os.path.join(runs_dir_path, run_id)):
        if os.path.isdir(runs_dir_path):   # ← only enters prefix logic if runs_dir exists
            ...
        # ← if runs_dir does NOT exist, falls through silently to _load_logs()

REPRODUCTION SCENARIO:
    GRAPHYN_PROJECT_DIR=/nonexistent graphyn runs logs some-run-id
    # → "No logs found for run: some-run-id" (misleading — directory doesn't exist)

IMPACT:
Misleading error message. No data loss.

FIX DIRECTION:
    if not os.path.isdir(runs_dir_path):
        print(f"Error: runs directory not found: {runs_dir_path}", file=sys.stderr)
        sys.exit(1)

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
| Test Hostile | PARTIAL |
| Top Risk | cmd_run seed-override path bypasses RunManager entirely, making seeded runs invisible to the run journal and artifact store. |
