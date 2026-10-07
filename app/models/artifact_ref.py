# app/models/artifact_ref.py
"""
Bounded Context:  Domain — Data Types
Responsibility:   Content-addressed file/dir reference that crosses Mode B
                  node boundaries without host paths. Carried on ModelArtifact
                  (and peers) as a role-keyed manifest; bytes live in the
                  distributed blob store under ``artifact://…`` URIs.
Owns:             ArtifactRef Pydantic model.
Public Surface:   ArtifactRef, ARTIFACT_ROLES
Must NOT:         Import from orchestrator, transfer, or plugin packages.
                  Must not perform I/O.
Dependencies:     pydantic.
Reason To Change: New roles, media hints, or wire schema for refs.

Wire contract (Mode B)
----------------------
On the wire a ref carries ``logical_id`` + ``role`` + ``sha256`` + ``uri``
(+ optional media / layout hints). ``source_path`` is producer-local only and
MUST be cleared by ``prepare_port_value_for_put`` before pickle — unreclaimed
host paths fail closed.
"""
# NOTE: Do NOT use `from __future__ import annotations` here — it turns all
# annotations into strings (PEP 563), which breaks Pydantic v2 model_rebuild()
# when the module is loaded via importlib.

from typing import Literal, Optional

from pydantic import ConfigDict, Field

from app.core.nodes.ports import PortDataType


# Well-known roles used by trainer / evaluator / edge_optimizer / packagers.
ARTIFACT_ROLES = frozenset(
    {
        "keras_model",
        "saved_model",
        "labels",
        "pytorch_model",
        "tflite",
        "deployment_bundle",
        "calibration_data",
        "checkpoint",
        "other",
    }
)


class ArtifactRef(PortDataType):
    """Content-addressed reference to a file or directory blob.

    Fields:
        logical_id:     Stable id (normally the content sha256 hex).
        role:           Semantic role (``keras_model``, ``saved_model``, …).
        sha256:         Content digest of the packed blob (file bytes or tar.gz).
        uri:            ``artifact://{store}/{key}`` after put; empty before pack.
        media_type:     Optional IANA / vendor media hint.
        filename:       Preferred basename when materializing.
        kind:           ``file`` or ``dir`` (dirs are tar.gz on the wire).
        relative_path:  Layout under ``<node_write_dir>/_inputs/<port>/…``.
        source_path:    Producer-local path used only while packing; cleared
                        before the payload crosses a node boundary.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    logical_id: str = ""
    role: str = "other"
    sha256: str = ""
    uri: str = ""
    media_type: Optional[str] = None
    filename: str = ""
    kind: Literal["file", "dir"] = "file"
    relative_path: str = ""
    source_path: str = Field(
        default="",
        description="Producer-local only; must be empty on the wire (Mode B).",
    )
