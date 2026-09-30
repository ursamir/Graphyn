# app/core/pipelines/__init__.py
"""
Bounded Context:  Saved pipelines
Responsibility:   Project pipelines, environments, and schedules.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "EnvironmentsCorrupt": "app.core.pipelines.pipeline_environments",
    "SchedulesDataError": "app.core.pipelines.schedules",
    "create_schedule": "app.core.pipelines.schedules",
    "delete_pipeline": "app.core.pipelines.project_pipelines",
    "delete_schedule": "app.core.pipelines.schedules",
    "enrich_pipeline_summary": "app.core.pipelines.pipeline_environments",
    "environments_path": "app.core.pipelines.pipeline_environments",
    "get_environment_graph": "app.core.pipelines.pipeline_environments",
    "get_environments": "app.core.pipelines.pipeline_environments",
    "get_pipeline": "app.core.pipelines.project_pipelines",
    "get_version": "app.core.pipelines.pipeline_environments",
    "list_pipelines": "app.core.pipelines.project_pipelines",
    "list_schedules": "app.core.pipelines.schedules",
    "list_versions": "app.core.pipelines.pipeline_environments",
    "pipeline_lock": "app.core.pipelines.project_pipelines",
    "pipeline_resource_version": "app.core.pipelines.project_pipelines",
    "pipelines_dir": "app.core.pipelines.project_pipelines",
    "promote_environment": "app.core.pipelines.pipeline_environments",
    "publish_version": "app.core.pipelines.pipeline_environments",
    "put_pipeline": "app.core.pipelines.project_pipelines",
    "resource_lock": "app.core.pipelines.project_pipelines",
    "rollback_draft_to_version": "app.core.pipelines.pipeline_environments",
    "run_schedule_now": "app.core.pipelines.schedules",
    "schedules_path": "app.core.pipelines.schedules",
    "set_schedule_enabled": "app.core.pipelines.schedules",
    "tick_due_schedules": "app.core.pipelines.schedules",
    "try_tick_due_schedules": "app.core.pipelines.schedules",
    "versions_dir": "app.core.pipelines.pipeline_environments",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
