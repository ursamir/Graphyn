# app/models/model_artifact.py
"""
Bounded Context:  Domain — Data Types
Responsibility:   Typed data contract for a trained model artifact. Produced
                  by trainer and evaluator nodes.
Owns:             ModelArtifact Pydantic model — model_path, labels, history,
                  metrics, refs (content-addressed ArtifactRef manifest).
Public Surface:   ModelArtifact
Must NOT:         Import from app.core.nodes.registry or app.core.execution.orchestrator.
                  Must not contain training logic.
Dependencies:     pydantic (PortDataType base), app.models.artifact_ref.
Reason To Change: ModelArtifact schema gains new fields, or metrics schema
                  changes.

Registered in TypeCatalogue as 'app.models.model_artifact.ModelArtifact'
by AutoDiscovery. Migrated from examples/06_speech_commands_e2e/.

Mode B note: file bytes travel via ``refs`` (ArtifactRef) + content-addressed
blobs. ``model_path`` and residual path keys in ``metrics`` are local-only
after hydrate; unreclaimed host paths must not cross node boundaries.
"""
# NOTE: Do NOT use `from __future__ import annotations` here — it turns all
# annotations into strings (PEP 563), which breaks Pydantic v2 model_rebuild()
# when the module is loaded via importlib.

from typing import List

from pydantic import ConfigDict, Field

from app.core.nodes.ports import PortDataType
from app.models.artifact_ref import ArtifactRef


class ModelArtifact(PortDataType):
    """Trained Keras / PyTorch model artifact.

    Produced by ModelTrainerNode; enriched by ModelEvaluatorNode.

    Fields:
        model_path: local path for plugin execution (SavedModel dir, .keras,
                    or .pt). Empty on the Mode B wire — filled by hydrate.
        labels:     sorted list of class label strings
        history:    Keras training history dict
                    {"loss": [...], "val_loss": [...], "accuracy": [...], ...}
        metrics:    evaluation / hand-off metrics (non-path values preferred;
                    path keys may be rewritten locally after hydrate)
        refs:       content-addressed ArtifactRef manifest (roles: keras_model,
                    saved_model, labels, pytorch_model, …)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_path: str = ""
    labels: list = Field(default_factory=list)
    history: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    refs: List[ArtifactRef] = Field(default_factory=list)
