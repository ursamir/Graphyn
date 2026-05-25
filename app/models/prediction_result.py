# app/models/prediction_result.py
"""
Bounded Context:  Domain — Data Types
Responsibility:   Typed data contract for inference results from classification
                  and detection nodes.
Owns:             PredictionResult Pydantic model — source_path,
                  predicted_label, probabilities, metadata.
Public Surface:   PredictionResult
Must NOT:         Import from app.core.nodes.registry or app.core.orchestrator.
                  Must not contain inference logic.
Dependencies:     pydantic (PortDataType base).
Reason To Change: PredictionResult schema gains new fields, or probability
                  representation changes.

Registered in TypeCatalogue as 'app.models.prediction_result.PredictionResult'
by AutoDiscovery. Migrated from examples/06_speech_commands_e2e/.
"""
# NOTE: Do NOT use `from __future__ import annotations` here — it turns all
# annotations into strings (PEP 563), which breaks Pydantic v2 model_rebuild()
# when the module is loaded via importlib.

from pydantic import ConfigDict

from app.core.nodes.ports import PortDataType


class PredictionResult(PortDataType):
    """Inference result for one audio clip.

    Produced by InferenceNode.

    Fields:
        source_path:     original audio file path
        predicted_label: top-1 predicted class label
        probabilities:   dict mapping each label to its softmax probability
                         (values sum to ~1.0 within 1e-5)
        metadata:        propagated from FeatureArray.metadata
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source_path: str = ""
    predicted_label: str = ""
    probabilities: dict = {}
    metadata: dict = {}
