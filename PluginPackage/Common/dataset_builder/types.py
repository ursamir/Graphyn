# PluginPackage/Common/dataset_builder/types.py
"""DatasetArtifact — re-export of the platform type.

Defined on the platform as ``app.models.dataset_artifact.DatasetArtifact`` so
isolated workers can unpickle host-produced artifacts. This module re-exports
the same class so existing plugin imports keep working.

Consumed by: dataset_balancer, dataset_versioner, trainer, evaluator.
"""
# NOTE: Do NOT use `from __future__ import annotations` here — it turns all
# annotations into strings (PEP 563), which breaks Pydantic v2 model_rebuild()
# when the module is loaded via importlib.

from app.models.dataset_artifact import DatasetArtifact
