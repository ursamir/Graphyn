# app/core/pipeline.py
"""Backward-compatibility shim for the pipeline module.

All implementation has been extracted into focused modules:
  - app.core.planner       — PipelineGraph, NodeSpec, EdgeSpec, PipelineConfig,
                             _ir_to_pipeline_config, _parse_pipeline_config
  - app.core.node_executor — NodeExecutor, _count_port_items
  - app.core.checkpoint    — _write_checkpoint, _load_checkpoint_outputs
  - app.core.orchestrator  — run_pipeline_ir_async, run_pipeline_ir,
                             _resolve_capability, _collect_stream

All public names are re-exported here so existing imports continue to work.
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
    _collect_stream,
)

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
