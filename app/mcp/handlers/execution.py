# app/mcp/handlers/execution.py
"""
Bounded Context:  MCP Server
Responsibility:   execute_pipeline tool handler. Validates a GraphIR, allocates
                  a RunManager, and submits execution to a background thread.
                  Returns run_id within 500ms.
Owns:             execute_pipeline_handler(), EXECUTE_PIPELINE_SCHEMA/DESCRIPTION,
                  _PIPELINE_EXECUTOR (module-level shared ThreadPoolExecutor).
Public Surface:   execute_pipeline_handler(arguments) -> dict
Must NOT:         Contain execution logic — delegates to get_backend().execute().
                  Must not import from app.domain.
Dependencies:     BC1 (ir.loader), BC5 (runtime_backend — module-level import),
                  BC6 (run_journal), stdlib (concurrent.futures, typing).
Reason To Change: execute_pipeline tool schema changes, or async execution
                  strategy changes (e.g. move to a task queue).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.runtime_backend import get_backend as _get_backend  # module-level — patchable in tests

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
    from app.core.ir.loader import load_ir
    from app.core.run_journal import RunManager

    graph_dict = arguments.get("graph")
    use_cache = arguments.get("use_cache", True)
    streaming = arguments.get("streaming", False)

    # Step 1: Validate graph (Req 4.11)
    # FIX (HIGH): return standard MCP error envelope, not {"valid": False, ...}
    try:
        graph = load_ir(graph_dict)
    except Exception as exc:
        return {
            "error": True,
            "error_type": "ir_validation_error",
            "message": str(exc),
        }

    # Step 2: Allocate RunManager to get run_id immediately (Req 4.12)
    run_manager = RunManager()
    run_id = run_manager.run_id

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
        future.add_done_callback(_on_done)
    except Exception as exc:
        run_manager.mark_failed(str(exc))
        return {
            "error": True,
            "error_type": "execution_error",
            "message": str(exc),
        }

    # Step 4: Return run_id within 500 ms (Req 4.2)
    return {"run_id": run_id, "status": "started"}
