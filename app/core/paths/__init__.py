# app/core/paths/__init__.py
"""
Bounded Context:  Platform paths
Responsibility:   Workspace and jailed write-path resolution.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "apply_output_rewire": "app.core.paths.workspace_paths",
    "artifact_fs_path": "app.core.paths.workspace_paths",
    "artifact_layout": "app.core.paths.workspace_paths",
    "artifact_slug": "app.core.paths.workspace_paths",
    "ensure_node_write_dirs": "app.core.paths.write_paths",
    "ensure_write_destination": "app.core.paths.write_paths",
    "ingest_dir_candidates": "app.core.paths.workspace_paths",
    "latest_run_id": "app.core.paths.workspace_paths",
    "publish_alias": "app.core.paths.workspace_paths",
    "publish_latest": "app.core.paths.workspace_paths",
    "read_metrics_json": "app.core.paths.workspace_paths",
    "read_run_metrics": "app.core.paths.workspace_paths",
    "resolve_ingest_dir": "app.core.paths.workspace_paths",
    "rewire_graph_outputs": "app.core.paths.workspace_paths",
    "scope_outputs_to_run": "app.core.paths.workspace_paths",
    "slug_from_artifacts_posix": "app.core.paths.workspace_paths",
    "strip_legacy_absolute_prefix": "app.core.paths.workspace_paths",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
