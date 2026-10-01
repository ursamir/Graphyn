# app/core/artifacts/__init__.py
"""
Bounded Context:  BC6 — Artifacts
Responsibility:   Content-addressed artifact registry, serializers, URIs, and provenance.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "ArtifactNotFoundError": "app.core.artifacts.artifact_store",
    "ArtifactRecord": "app.core.artifacts.artifact_store",
    "ArtifactSerializationError": "app.core.artifacts.artifact_store",
    "ArtifactSerializerRegistry": "app.core.artifacts.artifact_serializer",
    "ArtifactStore": "app.core.artifacts.artifact_store",
    "ArtifactTypeHandler": "app.core.artifacts.artifact_serializer",
    "ArtifactURI": "app.core.artifacts.artifact_uri",
    "ArtifactURIError": "app.core.artifacts.artifact_uri",
    "FileListing": "app.core.artifacts.artifact_serializer",
    "FileListingEntry": "app.core.artifacts.artifact_serializer",
    "FileTreeHandler": "app.core.artifacts.file_tree",
    "ProvenanceRecord": "app.core.artifacts.provenance",
    "ProvenanceStore": "app.core.artifacts.provenance",
    "build_artifact_uri": "app.core.artifacts.artifact_uri",
    "file_tree_payload": "app.core.artifacts.file_tree",
    "get_serializer_registry": "app.core.artifacts.artifact_serializer",
    "local_artifact_uri": "app.core.artifacts.artifact_uri",
    "local_content_key": "app.core.artifacts.artifact_uri",
    "parse_artifact_uri": "app.core.artifacts.artifact_uri",
    "register_file_tree_serializer": "app.core.artifacts.file_tree",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
