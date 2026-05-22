# app/models/__init__.py
"""Data models for the pipeline engine.

Re-exports all PortDataType subclasses so that
``from app.models import FeatureArray`` works.

V1.md §5.3 — standardized typed data contracts.

Note: Plugin-specific types (DatasetArtifact, EmbeddingVector,
ExperimentArtifact, etc.) are defined inside their respective plugins
and registered automatically by AutoDiscovery when the plugin is installed.
Only platform-core types that the platform infrastructure itself depends on
belong here.
"""
from app.models.audio_sample import AudioSample
from app.models.data_sample import DataSample
from app.models.deployment_artifact import DeploymentArtifact
from app.models.feature_array import FeatureArray
from app.models.model_artifact import ModelArtifact
from app.models.prediction_result import PredictionResult
from app.models.tensor_batch import TensorBatch
from app.models.tflite_artifact import TFLiteArtifact

__all__ = [
    "AudioSample",
    "DataSample",
    "DeploymentArtifact",
    "FeatureArray",
    "ModelArtifact",
    "PredictionResult",
    "TensorBatch",
    "TFLiteArtifact",
]
