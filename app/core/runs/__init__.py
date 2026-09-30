# app/core/runs/__init__.py
"""
Bounded Context:  BC6 — Run lifecycle
Responsibility:   Persist a run, list it, checkpoint it, and record its trace.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "ArtifactCommitForbidden": "app.core.runs.run_journal",
    "InvalidTransition": "app.core.runs.run_status",
    "OutputPathError": "app.core.runs.run_outputs",
    "ProveCaptureRecord": "app.core.runs.prove",
    "RunInProgressError": "app.core.runs.run_cleanup",
    "RunListPage": "app.core.runs.run_listing",
    "RunManager": "app.core.runs.run_journal",
    "RunProtectedError": "app.core.runs.run_cleanup",
    "assemble_trace": "app.core.runs.trace",
    "backfill_project_meta": "app.core.runs.run_project",
    "build_prove_capture": "app.core.runs.prove",
    "can_transition": "app.core.runs.run_status",
    "cleanup_workspace": "app.core.runs.run_cleanup",
    "clear_run_listing_cache": "app.core.runs.run_listing",
    "delete_run": "app.core.runs.run_cleanup",
    "deregister_active_run": "app.core.runs.run_control",
    "extract_project_fields_from_graph": "app.core.runs.run_project",
    "extract_project_fields_from_payload": "app.core.runs.run_project",
    "file_entry": "app.core.runs.run_outputs",
    "get_active_run": "app.core.runs.run_control",
    "infer_project_from_graph_file": "app.core.runs.run_project",
    "is_active_on_another_worker": "app.core.runs.run_control",
    "is_under_jail": "app.core.runs.run_outputs",
    "jail_roots": "app.core.runs.run_outputs",
    "list_run_output_files": "app.core.runs.run_outputs",
    "list_runs": "app.core.runs.run_listing",
    "load_durable_status": "app.core.runs.run_status",
    "load_prove_capture": "app.core.runs.prove",
    "next_status": "app.core.runs.run_status",
    "normalize_project_name": "app.core.runs.run_project",
    "normalize_status": "app.core.runs.run_status",
    "normalize_version_tag": "app.core.runs.run_project",
    "notify_run_terminal": "app.core.runs.run_notify",
    "pack_outputs_zip": "app.core.runs.run_outputs",
    "project_matches": "app.core.runs.run_project",
    "protected_run_ids": "app.core.runs.run_cleanup",
    "reconcile_abandoned_runs": "app.core.runs.run_cleanup",
    "register_active_run": "app.core.runs.run_control",
    "required_fields_present": "app.core.runs.prove",
    "resolve_download_path": "app.core.runs.run_outputs",
    "resolve_run_project": "app.core.runs.run_project",
    "retarget_latest": "app.core.runs.run_cleanup",
    "run_sort_key": "app.core.runs.run_listing",
    "sorted_run_dirs": "app.core.runs.run_listing",
    "write_cancel_marker": "app.core.runs.run_journal",
    "write_prove_capture": "app.core.runs.prove",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
