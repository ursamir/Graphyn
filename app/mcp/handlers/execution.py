# app/mcp/handlers/execution.py
"""execute_pipeline tool handler.

Delegates to run_pipeline_ir() (V1.md §3.1).
Req 4.1–4.14
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.orchestrator import run_pipeline_ir  # module-level import — patchable in tests

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
    try:
        graph = load_ir(graph_dict)
    except Exception as exc:
        return {"valid": False, "errors": [str(exc)]}

    # Step 2: Allocate RunManager to get run_id immediately (Req 4.12)
    run_manager = RunManager()
    run_id = run_manager.run_id

    # Step 3: Submit execution to shared background executor (NEW-7 fix — avoids
    # per-call ThreadPoolExecutor leak; NEW-16 fix — removes redundant thread layer).
    _PIPELINE_EXECUTOR.submit(
        run_pipeline_ir,
        graph,
        use_cache=use_cache,
        streaming=streaming,
        run_manager=run_manager,
    )

    # Step 4: Return run_id within 500 ms (Req 4.2)
    return {"run_id": run_id, "status": "started"}
