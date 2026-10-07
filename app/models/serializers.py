# app/models/serializers.py
"""
Bounded Context:  BC6 — Artifacts (domain data-type registration)
Responsibility:   Register every built-in ArtifactSerializerRegistry handler
                  in one call so API, CLI, MCP and SDK persist / cache the same
                  artifact types identically.
Owns:             register_builtin_serializers().
Public Surface:   register_builtin_serializers()
Must NOT:         Import app.api / app.cli / app.mcp; perform I/O beyond
                  handler registration.
Dependencies:     app.models.*_serializer, app.core.artifacts.file_tree.
Reason To Change: A built-in artifact serializer is added or removed.
"""
from __future__ import annotations


def register_builtin_serializers() -> None:
    """Idempotently register audio, dataset, features, file_tree, model and deployment handlers."""
    from app.core.artifacts.file_tree import register_file_tree_serializer
    from app.models.audio_artifact_serializer import register_audio_serializer
    from app.models.dataset_artifact_serializer import register_dataset_serializer
    from app.models.deployment_artifact_serializer import register_deployment_artifact_serializer
    from app.models.feature_array_serializer import register_feature_array_serializer
    from app.models.model_artifact_serializer import register_model_artifact_serializer

    register_audio_serializer()
    register_dataset_serializer()
    register_feature_array_serializer()
    register_file_tree_serializer()
    register_model_artifact_serializer()
    register_deployment_artifact_serializer()
