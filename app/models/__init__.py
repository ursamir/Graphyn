# app/models/__init__.py
"""
Bounded Context:  Domain — Data Types
Responsibility:   Public API surface for platform-core data models. Re-exports
                  all PortDataType subclasses so callers use a single import
                  path (``from app.models import AudioSample``).
Owns:             Re-export declarations for all platform-core types.
Public Surface:   AudioSample, DataSample, DeploymentArtifact, FeatureArray,
                  ModelArtifact, PredictionResult, TensorBatch, TFLiteArtifact.
Must NOT:         Define plugin-specific types here — those belong in the
                  plugin's types.py and are registered by AutoDiscovery.
                  Must not import from app.core.nodes.registry at module level.
Dependencies:     app.models.{audio_sample, data_sample, deployment_artifact,
                  feature_array, model_artifact, prediction_result,
                  tensor_batch, tflite_artifact}.
Reason To Change: New platform-core data type is added, or an existing type
                  is renamed or removed.
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
