# app/mcp/handlers/execution.py
"""
Bounded Context:  MCP Server
Responsibility:   execute_pipeline tool handler. Prepares a GraphIR through the
                  shared app.core.execution.graph_prepare pipeline (workspace rewire,
                  project stamping, secret refusal, VAL-003 validation — same
                  as REST / SDK / CLI), allocates a RunManager, records the
                  run.start audit, and submits execution to a background
                  thread. Returns run_id (status ``pending``) within 500ms.
Owns:             execute_pipeline_handler(), EXECUTE_PIPELINE_SCHEMA/DESCRIPTION,
                  _PIPELINE_EXECUTOR (module-level shared ThreadPoolExecutor).
Public Surface:   execute_pipeline_handler(arguments) -> dict
Must NOT:         Contain execution logic — delegates to get_backend().execute().
                  Must not import from app.domain.
Dependencies:     BC1 (graph_prepare), BC5 (runtime_backend — module-level import),
                  BC6 (run_journal), stdlib (concurrent.futures, typing).
Reason To Change: execute_pipeline tool schema changes, or async execution
                  strategy changes (e.g. move to a task queue).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.execution.runtime_backend import get_backend as _get_backend  # module-level — patchable in tests

log = logging.getLogger(__name__)

# NEW-7 fix: module-level shared executor — avoids creating a new ThreadPoolExecutor
# per call (which leaks OS threads under load when shutdown(wait=False) is used).
_PIPELINE_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# ── Tool schema constants ─────────────────────────────────────────────────────

EXECUTE_PIPELINE_DESCRIPTION = (
    "Execute a pipeline from a GraphIR JSON document. Returns run_id within 500ms. "
    "Execution proceeds asynchronously in a background thread. Use inspect_run to "
    "retrieve artifacts and logs after completion."
)

EXECUTE_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "graph": {
            "type": "object",
            "description": "A validated GraphIR JSON document.",
        },
        "use_cache": {
            "type": "boolean",
            "description": "Whether to use PipelineCache for node outputs (default true).",
            "default": True,
        },
        "streaming": {
            "type": "boolean",
            "description": "Whether to use streaming execution mode (default false).",
            "default": False,
        },
        "project": {
            "type": "string",
            "description": "Optional project scope stamped on the run (same as REST payload.project).",
        },
        "version_tag": {
            "type": "string",
            "description": "Optional version tag stamped on the run.",
        },
        "actor": {
            "type": "string",
            "description": "Optional actor recorded on the run.start audit event (default 'mcp').",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["graph"],
    "additionalProperties": False,
}


# ── Handler ───────────────────────────────────────────────────────────────────


def execute_pipeline_handler(arguments: dict[str, Any]) -> Any:
    """Execute a pipeline asynchronously (Req 4.1–4.14).

    Returns run_id within 500 ms (Req 4.2).
    Delegates to run_pipeline_ir() (V1.md §3.1).
    """
    from app.core.runs.run_journal import RunManager

    graph_dict = arguments.get("graph")
    use_cache = arguments.get("use_cache", True)
    streaming = arguments.get("streaming", False)

    # Step 1: Validate graph (Req 4.11) — same checks as REST /run-async.
    from app.core.host.shutdown import is_draining

    if is_draining():
        return {
            "error": True,
            "error_type": "draining",
            "message": "Control plane is shutting down; refusing new runs",
        }

    from app.core.execution.graph_prepare import (
        GraphPrepareError,
        persist_project_fields,
        prepare_graph,
        record_run_start,
    )

    if not isinstance(graph_dict, dict):
        return {
            "valid": False,
            "errors": ["graph (a GraphIR JSON object) is required"],
            "error": True,
            "error_type": "ir_validation_error",
            "message": "graph (a GraphIR JSON object) is required",
        }
    try:
        prepared = prepare_graph(
            graph_dict,
            payload={
                "project": arguments.get("project"),
                "version_tag": arguments.get("version_tag"),
            },
        )
    except GraphPrepareError as exc:
        if exc.code == "secret_in_ir":
            return {
                "error": True,
                "error_type": "inline_secret_error",
                "message": exc.message,
            }
        if exc.code == "validation_failed":
            return {
                "valid": False,
                "errors": exc.errors,
                "warnings": exc.warnings,
                "error": True,
                "error_type": "ir_validation_error",
                "message": exc.message,
            }
        return {
            "valid": False,
            "errors": [exc.message],
            "error": True,
            "error_type": "ir_validation_error",
            "message": exc.message,
        }
    except Exception as exc:
        return {
            "valid": False,
            "errors": [str(exc)],
            "error": True,
            "error_type": "ir_validation_error",
            "message": str(exc),
        }
    graph = prepared.graph

    # Step 2: Allocate RunManager to get run_id immediately (Req 4.12)
    run_manager = RunManager()
    run_id = run_manager.run_id
    persist_project_fields(run_manager, prepared.project_fields)
    from app.core.execution.graph_prepare import persist_run_identity

    _mcp_actor = str(arguments.get("actor") or "mcp").strip()[:128] or "mcp"
    persist_run_identity(run_manager, actor=_mcp_actor, trigger="mcp", payload=arguments)

    # FIX (CRITICAL): done callback surfaces unhandled background exceptions and
    # marks the run failed so inspect_run never returns "running" indefinitely.
    def _on_done(fut):  # type: ignore[type-arg]
        exc = fut.exception()
        if exc:
            log.error(
                "Background pipeline execution failed for run %s: %s",
                run_id,
                exc,
                exc_info=exc,
            )
            try:
                run_manager.mark_failed(str(exc))
            except Exception:
                pass

    # Step 3: Submit execution to shared background executor (NEW-7 fix — avoids
    # per-call ThreadPoolExecutor leak; NEW-16 fix — removes redundant thread layer).
    # FIX (MEDIUM): wrap submit() so an executor-shutdown RuntimeError marks the
    # run failed rather than leaving it orphaned with "running" status.
    try:
        future = _PIPELINE_EXECUTOR.submit(
            _get_backend().execute,
            graph,
            use_cache=use_cache,
            streaming=streaming,
            run_manager=run_manager,
        )
        if future is not None and hasattr(future, "add_done_callback"):
            future.add_done_callback(_on_done)
    except Exception as exc:
        run_manager.mark_failed(str(exc))
        return {
            "error": True,
            "error_type": "execution_error",
            "message": str(exc),
        }

    record_run_start(
        run_id,
        graph,
        actor=_mcp_actor,
        mode="mcp",
    )

    # Step 4: Return run_id within 500 ms (Req 4.2). Status vocabulary matches
    # REST /pipelines/run-async (durable ``pending`` until the orchestrator
    # starts). ``accepted`` is a compat flag for clients that keyed on the
    # legacy ``status == "started"`` ack.
    return {"run_id": run_id, "status": "pending", "accepted": True}
