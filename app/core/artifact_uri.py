# app/core/artifact_uri.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Parse and build ``artifact://{store}/{key}`` URIs that
                  cross machine boundaries in distributed execution.
Owns:             parse_artifact_uri(), build_artifact_uri(),
                  local_content_key(), LOCAL_STORE_ID.
Public Surface:   ArtifactURI, parse_artifact_uri, build_artifact_uri,
                  local_content_key, LOCAL_STORE_ID, ArtifactURIError.
Must NOT:         Import from app.domain, app.api, or orchestrator.
                  Must not perform network I/O or touch storage backends.
Dependencies:     stdlib (dataclasses, re).
Reason To Change: New store schemes, URI format evolution, or keying rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

LOCAL_STORE_ID = "local"
"""Default in-process / single-host content-addressed store id."""

_URI_RE = re.compile(
    r"^artifact://(?P<store>[A-Za-z0-9_-]+)/(?P<key>.+)$"
)


class ArtifactURIError(ValueError):
    """Raised when an artifact URI is malformed."""


@dataclass(frozen=True)
class ArtifactURI:
    """Parsed ``artifact://{store}/{key}`` reference."""

    store: str
    key: str

    def __str__(self) -> str:
        return build_artifact_uri(self.store, self.key)


def build_artifact_uri(store: str, key: str) -> str:
    """Build an ``artifact://{store}/{key}`` URI.

    ``key`` may contain path separators; they are preserved literally
    (not percent-encoded) so content-addressed paths stay readable.
    Leading slashes on ``key`` are stripped.
    """
    store = (store or "").strip()
    if not store or not re.fullmatch(r"[A-Za-z0-9_-]+", store):
        raise ArtifactURIError(
            f"Invalid artifact store id {store!r}; "
            "expected alphanumeric / underscore / hyphen."
        )
    key = (key or "").lstrip("/")
    if not key:
        raise ArtifactURIError("Artifact key must be non-empty")
    # Reject scheme injection / absolute URLs inside the key.
    if "://" in key or key.startswith("artifact:"):
        raise ArtifactURIError(f"Invalid artifact key {key!r}")
    return f"artifact://{store}/{key}"


def parse_artifact_uri(uri: str) -> ArtifactURI:
    """Parse ``artifact://{store}/{key}`` into an :class:`ArtifactURI`.

    Raises:
        ArtifactURIError: if the URI does not match the expected form.
    """
    if not isinstance(uri, str) or not uri:
        raise ArtifactURIError(f"Expected artifact URI string, got {uri!r}")
    m = _URI_RE.match(uri.strip())
    if not m:
        raise ArtifactURIError(
            f"Malformed artifact URI {uri!r}; "
            "expected artifact://{{store}}/{{key}}"
        )
    store = m.group("store")
    key = m.group("key").lstrip("/")
    if not key:
        raise ArtifactURIError(f"Artifact URI {uri!r} has an empty key")
    return ArtifactURI(store=store, key=key)


def local_content_key(content_hash: str, *, prefix: str = "sha256") -> str:
    """Map a content hash to a local store key path.

    Example: ``sha256/ab/cd/abcd…`` (first two hex pairs as directory shards).
    """
    h = (content_hash or "").strip().lower()
    if not h or not re.fullmatch(r"[0-9a-f]+", h):
        raise ArtifactURIError(
            f"content_hash must be a non-empty hex string, got {content_hash!r}"
        )
    if len(h) < 4:
        return f"{prefix}/{h}"
    return f"{prefix}/{h[0:2]}/{h[2:4]}/{h}"


def local_artifact_uri(content_hash: str) -> str:
    """Convenience: ``artifact://local/sha256/ab/cd/…`` from a content hash."""
    return build_artifact_uri(LOCAL_STORE_ID, local_content_key(content_hash))
