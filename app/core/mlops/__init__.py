# app/core/mlops/__init__.py
"""
Bounded Context:  Model lifecycle
Responsibility:   Model registry, ship packages, dataset versions, and experiments.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "DatasetVersionInUse": "app.core.mlops.dataset_versions",
    "InvalidPackageTransition": "app.core.mlops.ship_packages",
    "ModelRegistryError": "app.core.mlops.model_registry",
    "ModelRunNotFound": "app.core.mlops.model_registry",
    "ModelRunNotSucceeded": "app.core.mlops.model_registry",
    "ProdRequiresApproval": "app.core.mlops.model_registry",
    "approve_prod": "app.core.mlops.model_registry",
    "can_transition": "app.core.mlops.ship_packages",
    "collect_run_rows": "app.core.mlops.experiments",
    "compare_runs": "app.core.mlops.experiments",
    "compute_manifest": "app.core.mlops.dataset_versions",
    "create_package": "app.core.mlops.ship_packages",
    "download_package_path": "app.core.mlops.ship_packages",
    "find_references": "app.core.mlops.dataset_versions",
    "get_experiment": "app.core.mlops.experiments",
    "get_model": "app.core.mlops.model_registry",
    "get_package": "app.core.mlops.ship_packages",
    "list_experiments": "app.core.mlops.experiments",
    "list_models": "app.core.mlops.model_registry",
    "list_packages": "app.core.mlops.ship_packages",
    "next_status": "app.core.mlops.ship_packages",
    "normalize_status": "app.core.mlops.ship_packages",
    "package_dir": "app.core.mlops.ship_packages",
    "packages_root": "app.core.mlops.ship_packages",
    "preferred_metric_columns": "app.core.mlops.experiments",
    "promote_package": "app.core.mlops.ship_packages",
    "read_manifest": "app.core.mlops.dataset_versions",
    "register_model": "app.core.mlops.model_registry",
    "registry_path": "app.core.mlops.model_registry",
    "request_prod": "app.core.mlops.model_registry",
    "transition_package": "app.core.mlops.ship_packages",
    "wire_status": "app.core.mlops.ship_packages",
    "write_manifest": "app.core.mlops.dataset_versions",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
