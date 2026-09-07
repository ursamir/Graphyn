"""artifact:// URI helper tests."""
from __future__ import annotations

import pytest

from app.core.artifact_uri import (
    LOCAL_STORE_ID,
    ArtifactURIError,
    build_artifact_uri,
    local_artifact_uri,
    local_content_key,
    parse_artifact_uri,
)


def test_build_and_parse_round_trip():
    uri = build_artifact_uri("local", "sha256/ab/cd/abcd")
    assert uri == "artifact://local/sha256/ab/cd/abcd"
    parsed = parse_artifact_uri(uri)
    assert parsed.store == "local"
    assert parsed.key == "sha256/ab/cd/abcd"
    assert str(parsed) == uri


def test_local_content_key_sharding():
    key = local_content_key("abcdef012345")
    assert key == "sha256/ab/cd/abcdef012345"
    assert local_artifact_uri("abcdef012345").startswith("artifact://local/")


def test_parse_rejects_malformed():
    with pytest.raises(ArtifactURIError):
        parse_artifact_uri("http://example/x")
    with pytest.raises(ArtifactURIError):
        parse_artifact_uri("artifact://")
    with pytest.raises(ArtifactURIError):
        build_artifact_uri("", "key")
    with pytest.raises(ArtifactURIError):
        local_content_key("not-hex!")


def test_local_store_id_constant():
    assert LOCAL_STORE_ID == "local"
