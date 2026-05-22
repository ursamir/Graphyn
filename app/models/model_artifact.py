# app/models/model_artifact.py
"""ModelArtifact — trained Keras model artifact.

Migrated from examples/06_speech_commands_e2e/plugins/data_types.py.
Registered in TypeCatalogue as 'app.models.model_artifact.ModelArtifact'
by AutoDiscovery.
"""
# NOTE: Do NOT use `from __future__ import annotations` here — it turns all
# annotations into strings (PEP 563), which breaks Pydantic v2 model_rebuild()
# when the module is loaded via importlib.

from pydantic import ConfigDict

from app.core.nodes.ports import PortDataType


class ModelArtifact(PortDataType):
    """Trained Keras model artifact.

    Produced by ModelTrainerNode; enriched by ModelEvaluatorNode.

    Fields:
        model_path: path to a TensorFlow SavedModel directory
        labels:     sorted list of class label strings
        history:    Keras training history dict
                    {"loss": [...], "val_loss": [...], "accuracy": [...], ...}
        metrics:    evaluation metrics dict populated by ModelEvaluatorNode
                    {"test_accuracy": float, "per_class": {...},
                     "confusion_matrix": [[int, ...]]}
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_path: str = ""
    labels: list = []
    history: dict = {}
    metrics: dict = {}
