"""ExperimentArtifact — experiment run record with parameters, metrics, and artifact paths.

Defined here (inside the plugin) so it is registered in TypeCatalogue
only when the experiment_tracker plugin is installed.
"""
# NOTE: Do NOT use `from __future__ import annotations` here — breaks Pydantic v2.

from typing import Any

from pydantic import Field

from app.core.nodes.ports import PortDataType


class ExperimentArtifact(PortDataType):
    """Experiment run record produced by ExperimentTrackerNode.

    Fields:
        run_id:           unique run identifier (timestamp-based)
        experiment_name:  name of the experiment
        parameters:       dict of hyperparameters logged
        metrics:          dict of metric name → value (or list of values per epoch)
        artifact_paths:   dict of artifact name → file path
        backend:          "json" | "mlflow"
        metadata:         arbitrary annotations (git hash, platform, etc.)
    """

    run_id: str = ""
    experiment_name: str = "default"
    parameters: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    backend: str = "json"
    metadata: dict[str, Any] = Field(default_factory=dict)
