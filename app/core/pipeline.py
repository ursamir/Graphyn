# app/core/pipeline.py
"""
Bounded Context:  BC5 — Execution Runtime (re-export shim)
Responsibility:   Backward-compatibility shim. Re-exports all public names
                  from the focused modules that replaced the original god module.
Owns:             Re-export declarations only — no implementation.
Public Surface:   All names previously importable from app.core.pipeline
                  (NodeSpec, EdgeSpec, PipelineConfig, NodeExecutor,
                  run_pipeline_ir, run_pipeline_ir_async, RunManager, etc.)
Must NOT:         Contain any implementation logic. Must not be the canonical
                  import path for new code — import from the focused modules.
Dependencies:     app.core.planner, app.core.node_executor, app.core.checkpoint,
                  app.core.orchestrator, app.core.run_journal, app.core.utils.
Reason To Change: A re-exported name is removed or renamed in its source module.

All implementation has been extracted into focused modules:
  - app.core.planner       — PipelineGraph, NodeSpec, EdgeSpec, PipelineConfig
  - app.core.node_executor — NodeExecutor, _count_port_items
  - app.core.checkpoint    — _write_checkpoint, _load_checkpoint_outputs
  - app.core.orchestrator  — run_pipeline_ir_async, run_pipeline_ir
  - app.core.utils         — collect_stream (re-exported as _collect_stream)
"""
from __future__ import annotations

# ── Re-exports from planner ────────────────────────────────────────────────────
from app.core.planner import (
    NodeSpec,
    EdgeSpec,
    PipelineConfig,
    PipelineGraph,
    _ir_to_pipeline_config,
    _parse_pipeline_config,
)

# ── Re-exports from node_executor ─────────────────────────────────────────────
from app.core.node_executor import (
    NodeExecutor,
    _count_port_items,
)

# ── Re-exports from checkpoint ────────────────────────────────────────────────
from app.core.checkpoint import (
    _write_checkpoint,
    _load_checkpoint_outputs,
)

# ── Re-exports from orchestrator ──────────────────────────────────────────────
from app.core.orchestrator import (
    run_pipeline_ir_async,
    run_pipeline_ir,
    _resolve_capability,
)

# SA-O5: _collect_stream was extracted to app.core.utils.collect_stream.
# Re-export under the old private name for any legacy callers.
from app.core.utils import collect_stream as _collect_stream

# ── ResumeError (lives in errors.py, re-exported here for legacy imports) ─────
from app.core.nodes.errors import ResumeError


# ── Deprecated run_pipeline (YAML path) ───────────────────────────────────────

def run_pipeline(
    config_path: str,
    logger=None,
    use_cache: bool = True,
    checkpoint: bool = False,
    streaming: bool = False,
    observer=None,
    run_manager=None,
):
    """Execute a pipeline from a YAML config file.

    Deprecated: use run_pipeline_ir() with a GraphIR object, or Pipeline.run() via the SDK.
    """
    import warnings
    from app.core.ir.yaml_shim import load_yaml_with_deprecation
    from app.core.run_manager import RunManager

    warnings.warn(
        "run_pipeline() with a YAML config path is deprecated. "
        "Use run_pipeline_ir() with a GraphIR object, or Pipeline.run() via the SDK.",
        DeprecationWarning,
        stacklevel=2,
    )

    if run_manager is None:
        run_manager = RunManager()

    with open(config_path, "r", encoding="utf-8") as f:
        config_yaml = f.read()
    run_manager.save_config(config_yaml)

    graph = load_yaml_with_deprecation(config_path)

    return run_pipeline_ir(
        graph,
        logger=logger,
        use_cache=use_cache,
        checkpoint=checkpoint,
        streaming=streaming,
        observer=observer,
        run_manager=run_manager,
    )


__all__ = [
    # planner
    "NodeSpec", "EdgeSpec", "PipelineConfig", "PipelineGraph",
    "_ir_to_pipeline_config", "_parse_pipeline_config",
    # node_executor
    "NodeExecutor", "_count_port_items",
    # checkpoint
    "_write_checkpoint", "_load_checkpoint_outputs",
    # orchestrator
    "run_pipeline_ir_async", "run_pipeline_ir",
    "_resolve_capability", "_collect_stream",
    # errors
    "ResumeError",
    # deprecated
    "run_pipeline",
]
