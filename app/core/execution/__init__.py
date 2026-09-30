# app/core/execution/__init__.py
"""
Bounded Context:  BC4/BC5 — Execution
Responsibility:   Plan a graph and run it: planner, orchestrator, node and wave executors, cache, validation.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "ConditionEvaluationError": "app.core.execution.conditions",
    "EdgeSpec": "app.core.execution.planner",
    "EventSource": "app.core.execution.events",
    "FileWatcherSource": "app.core.execution.events",
    "GraphPrepareError": "app.core.execution.graph_prepare",
    "LocalPythonBackend": "app.core.execution.runtime_backend",
    "NodeExecutor": "app.core.execution.node_executor",
    "NodeSpec": "app.core.execution.planner",
    "ParallelExecutor": "app.core.execution.executor",
    "PipelineCache": "app.core.execution.pipeline_cache",
    "PipelineConfig": "app.core.execution.planner",
    "PipelineGraph": "app.core.execution.planner",
    "PreparedGraph": "app.core.execution.graph_prepare",
    "QueueSource": "app.core.execution.events",
    "RuntimeBackend": "app.core.execution.runtime_backend",
    "TimerSource": "app.core.execution.events",
    "check_graph_executable": "app.core.execution.graph_prepare",
    "create_event_source": "app.core.execution.events",
    "derive_node_seed": "app.core.execution.planner",
    "evaluate_condition": "app.core.execution.conditions",
    "get_backend": "app.core.execution.runtime_backend",
    "graph_display_name": "app.core.execution.graph_prepare",
    "list_backends": "app.core.execution.runtime_backend",
    "persist_project_fields": "app.core.execution.graph_prepare",
    "prepare_graph": "app.core.execution.graph_prepare",
    "record_run_start": "app.core.execution.graph_prepare",
    "register_backend": "app.core.execution.runtime_backend",
    "rewire_for_execution": "app.core.execution.graph_prepare",
    "run_pipeline_ir": "app.core.execution.orchestrator",
    "run_pipeline_ir_async": "app.core.execution.orchestrator",
    "should_skip_for_unproduced": "app.core.execution.skip_logic",
    "stamp_graph_project": "app.core.execution.graph_prepare",
    "validate_condition_syntax": "app.core.execution.conditions",
    "validate_graph_ir": "app.core.execution.validation",
    "validate_graph_ir_result": "app.core.execution.validation",
    "validate_node_config": "app.core.execution.validation",
    "validate_pipeline": "app.core.execution.validation",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
