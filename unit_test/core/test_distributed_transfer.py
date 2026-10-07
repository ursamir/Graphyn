"""Distributed transfer: pickle port values + blob put/get."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _tmp_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    yield


def test_dump_load_port_value_round_trip():
    from app.core.distributed.transfer import dump_port_value, load_port_value

    payload = {"items": [1, 2, 3], "label": "ok", "nested": {"a": True}}
    raw = dump_port_value(payload)
    assert isinstance(raw, bytes)
    assert load_port_value(raw) == payload


def test_put_get_blob_round_trip():
    from app.core.distributed.transfer import get_blob, put_blob, put_port_value, get_port_value

    uri = put_blob(b"hello-distributed")
    assert uri.startswith("artifact://local/")
    assert get_blob(uri) == b"hello-distributed"

    uri2 = put_blob(b"hello-distributed")
    assert uri2 == uri

    port_uri = put_port_value({"x": 42})
    assert get_port_value(port_uri) == {"x": 42}


def test_put_blob_rejects_empty():
    from app.core.distributed.transfer import put_blob

    with pytest.raises(ValueError):
        put_blob(b"")


def test_safe_path_rejects_escape(tmp_path, monkeypatch):
    from app.core.distributed import transfer as tr

    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    with pytest.raises(ValueError):
        tr._safe_path("../etc/passwd")
    with pytest.raises(ValueError):
        tr._safe_path("sha256/../../etc/passwd")


def test_put_get_nested_content_addressed_key(tmp_path, monkeypatch):
    """Nested sha256/ab/cd/... keys round-trip via put_blob/get_blob."""
    from app.core.artifacts.artifact_uri import local_content_key
    from app.core.distributed.transfer import get_blob, http_get_blob, put_blob
    from urllib.parse import quote as url_quote

    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    body = b"nested-key-payload-xyz"
    import hashlib

    digest = hashlib.sha256(body).hexdigest()
    key = local_content_key(digest)
    assert key.startswith("sha256/")
    assert "/" in key
    uri = put_blob(body, key=key)
    assert key in uri
    assert get_blob(uri) == body

    # http_get_blob must URL-encode the key (safe="/") so nested paths survive.
    # We only assert the URL construction contract here (no live HTTP server).
    from app.core.distributed import transfer as tr

    captured = {}

    class _Resp:
        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=60.0):
        captured["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(tr.urllib.request, "urlopen", fake_urlopen)
    got = http_get_blob("http://control.example/api/v1", uri)
    assert got == body
    assert "sha256/" in captured["url"]
    # Encoded form should match quote(key, safe="/")
    assert url_quote(key, safe="/") in captured["url"]


def test_get_blob_rejects_sha256_mismatch(tmp_path, monkeypatch):
    from app.core.artifacts.artifact_uri import local_content_key
    from app.core.distributed import transfer as tr

    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    key = local_content_key("a" * 64)
    path = tr._safe_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"wrong-bytes")
    uri = f"artifact://local/{key}"
    with pytest.raises(ValueError, match="hash mismatch"):
        tr.get_blob(uri)


def test_load_port_value_rejects_disallowed_globals():
    """Host RestrictedUnpickler must refuse attacker-style pickle globals."""
    import os
    import pickle

    from app.core.distributed.transfer import load_port_value

    class Evil:
        def __reduce__(self):
            return (os.system, ("true",))

    raw = pickle.dumps({"x": Evil()}, protocol=pickle.HIGHEST_PROTOCOL)
    with pytest.raises(pickle.UnpicklingError):
        load_port_value(raw)



def test_model_artifact_artifactref_round_trip_keras_and_saved_model(tmp_path, monkeypatch):
    """Mode B A+C: keras + saved_model tree pack by role; hydrate under second root."""
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))

    from app.core.distributed.transfer import (
        dump_port_value,
        get_port_value,
        prepare_port_value_for_put,
        put_port_value,
    )
    from app.models.artifact_ref import ArtifactRef
    from app.models.model_artifact import ModelArtifact

    control = tmp_path / "control_out"
    control.mkdir()
    keras_path = control / "model.keras"
    keras_bytes = b"KerasModel\x00" + bytes(range(256)) + b"_END"
    keras_path.write_bytes(keras_bytes)
    saved = control / "saved_model"
    (saved / "variables").mkdir(parents=True)
    (saved / "saved_model.pb").write_bytes(b"pb-bytes")
    (saved / "variables" / "variables.data").write_bytes(b"var-bytes")
    labels_path = control / "labels.txt"
    labels_path.write_text("yes\nno\n", encoding="utf-8")

    art = ModelArtifact(
        model_path=str(saved),
        labels=["yes", "no"],
        metrics={
            "architecture": "ds_cnn",
            "keras_model_path": str(keras_path),
            "labels_path": str(labels_path),
        },
        refs=[
            ArtifactRef(
                role="keras_model",
                kind="file",
                filename="model.keras",
                relative_path="model.keras",
                source_path=str(keras_path),
                media_type="application/x-keras",
            ),
            ArtifactRef(
                role="saved_model",
                kind="dir",
                filename="saved_model",
                relative_path="saved_model",
                source_path=str(saved),
                media_type="application/x-savedmodel",
            ),
            ArtifactRef(
                role="labels",
                kind="file",
                filename="labels.txt",
                relative_path="labels.txt",
                source_path=str(labels_path),
                media_type="text/plain",
            ),
        ],
    )

    prepared = prepare_port_value_for_put(art)
    assert isinstance(prepared, ModelArtifact)
    assert prepared.model_path == ""
    assert not (prepared.metrics or {}).get("keras_model_path")
    assert all(not r.source_path for r in prepared.refs)
    assert {r.role for r in prepared.refs} >= {"keras_model", "saved_model", "labels"}
    assert all(r.uri.startswith("artifact://") and r.sha256 for r in prepared.refs)

    raw = dump_port_value(prepared)
    assert str(keras_path).encode() not in raw
    assert str(saved).encode() not in raw

    uri = put_port_value(art)
    remote_root = tmp_path / "worker_write" / "_inputs" / "model_artifact"
    got = get_port_value(uri, materialize_dir=remote_root)
    assert isinstance(got, ModelArtifact)
    assert got.labels == ["yes", "no"]
    assert got.metrics.get("architecture") == "ds_cnn"
    assert Path(got.model_path).is_dir()
    assert (Path(got.model_path) / "saved_model.pb").read_bytes() == b"pb-bytes"
    assert (Path(got.model_path) / "variables" / "variables.data").read_bytes() == b"var-bytes"
    keras_local = Path(got.metrics["keras_model_path"])
    assert keras_local.is_file()
    assert keras_local.read_bytes() == keras_bytes
    assert remote_root.resolve() in keras_local.resolve().parents
    assert remote_root.resolve() in Path(got.model_path).resolve().parents
    assert str(keras_path) != got.metrics["keras_model_path"]
    assert str(saved) != got.model_path


def test_model_artifact_fail_closed_unreclaimed_host_path(tmp_path, monkeypatch):
    """Fail-closed: host path that cannot be packed must not cross Mode B."""
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))

    from app.core.distributed.transfer import (
        UnreclaimedHostPathError,
        prepare_port_value_for_put,
    )
    from app.models.model_artifact import ModelArtifact

    missing = tmp_path / "control" / "nope.keras"
    art = ModelArtifact(
        model_path=str(missing),
        labels=["a"],
        metrics={"keras_model_path": str(missing)},
    )
    with pytest.raises(UnreclaimedHostPathError):
        prepare_port_value_for_put(art)


def test_raw_host_path_must_not_survive_put_get_without_materialize(tmp_path, monkeypatch):
    """put→get without materialize must not revive producer host paths."""
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))

    import io

    from app.core.distributed.transfer import get_blob, load_port_value, put_port_value
    from app.core.plugins.isolated_executor import RestrictedUnpickler
    from app.models.model_artifact import ModelArtifact

    control = tmp_path / "prod"
    control.mkdir()
    keras = control / "model.keras"
    keras.write_bytes(b"ABC123")
    art = ModelArtifact(
        model_path=str(keras),
        labels=["x"],
        metrics={"keras_model_path": str(keras)},
    )
    uri = put_port_value(art)
    data = get_blob(uri)
    bare = RestrictedUnpickler(io.BytesIO(data)).load()
    assert isinstance(bare, ModelArtifact)
    assert bare.model_path == ""
    assert not (bare.metrics or {}).get("keras_model_path")
    assert all(not getattr(r, "source_path", "") for r in (bare.refs or []))
    foreign = tmp_path / "foreign"
    got = load_port_value(data, materialize_dir=foreign)
    assert str(keras) not in (got.model_path, (got.metrics or {}).get("keras_model_path", ""))
    assert Path(got.metrics["keras_model_path"]).is_file()


def test_deployment_artifact_directory_sideload_round_trip(tmp_path, monkeypatch):
    """Deployment directories are packed as ArtifactRef dirs and extracted on get."""
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))

    from app.core.distributed.transfer import get_port_value, put_port_value
    from app.models.deployment_artifact import DeploymentArtifact

    saved = tmp_path / "control" / "saved_model"
    (saved / "variables").mkdir(parents=True)
    (saved / "saved_model.pb").write_bytes(b"pb-bytes")
    (saved / "variables" / "variables.data").write_bytes(b"var-bytes")

    art = DeploymentArtifact(
        artifact_path=str(saved),
        model_format="saved_model",
        labels=["a", "b"],
    )
    uri = put_port_value(art)
    remote = tmp_path / "worker_mat"
    got = get_port_value(uri, materialize_dir=remote)
    assert isinstance(got, DeploymentArtifact)
    dest = Path(got.artifact_path)
    assert dest.is_dir()
    assert (dest / "saved_model.pb").read_bytes() == b"pb-bytes"
    assert (dest / "variables" / "variables.data").read_bytes() == b"var-bytes"
    assert remote.resolve() in dest.resolve().parents


def test_tflite_artifact_path_sideload_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))

    from app.core.distributed.transfer import get_port_value, put_port_value
    from app.models.tflite_artifact import TFLiteArtifact

    f = tmp_path / "model.tflite"
    f.write_bytes(b"TFL3" + (b"\x00" * 64))
    art = TFLiteArtifact(tflite_path=str(f), labels=["x"], quantisation="float32", file_size_bytes=68)
    uri = put_port_value(art)
    got = get_port_value(uri, materialize_dir=tmp_path / "mat")
    assert Path(got.tflite_path).read_bytes().startswith(b"TFL3")
    assert got.quantisation == "float32"


def test_plain_port_value_unaffected_by_sideload(tmp_path, monkeypatch):
    """Non-path-bearing values still round-trip as plain pickle."""
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    from app.core.distributed.transfer import (
        PATH_SIDELOAD_MARK,
        dump_port_value,
        load_port_value,
        prepare_port_value_for_put,
        put_port_value,
        get_port_value,
    )

    prepared = prepare_port_value_for_put({"x": 1, "y": [2, 3]})
    assert PATH_SIDELOAD_MARK not in (prepared if isinstance(prepared, dict) else {})
    raw = dump_port_value(prepared)
    assert load_port_value(raw) == {"x": 1, "y": [2, 3]}
    assert get_port_value(put_port_value({"a": True})) == {"a": True}


def test_deployment_artifact_labels_and_bundle_round_trip(tmp_path, monkeypatch):
    """DeploymentArtifact packs model + labels roles; hydrates under remote root."""
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))

    from app.core.distributed.transfer import (
        dump_port_value,
        get_port_value,
        prepare_port_value_for_put,
        put_port_value,
    )
    from app.models.artifact_ref import ArtifactRef
    from app.models.deployment_artifact import DeploymentArtifact

    control = tmp_path / "control_out"
    control.mkdir()
    model = control / "model.tflite"
    model.write_bytes(b"TFL3" + (b"\x00" * 64))
    labels = control / "labels.txt"
    labels.write_text("yes\nno\n", encoding="utf-8")

    art = DeploymentArtifact(
        artifact_path=str(model),
        model_format="tflite",
        labels=["yes", "no"],
        file_size_bytes=68,
        metadata={
            "labels_path": str(labels),
            "source_model_path": "/host/prod/saved_model",
            "source": "/host/prod/model.keras",
            "display_name": "demo",
        },
        refs=[
            ArtifactRef(
                role="deployment_bundle",
                kind="file",
                filename="model.tflite",
                relative_path="model.tflite",
                source_path=str(model),
                media_type="application/x-tflite",
            ),
            ArtifactRef(
                role="labels",
                kind="file",
                filename="labels.txt",
                relative_path="labels.txt",
                source_path=str(labels),
                media_type="text/plain",
            ),
        ],
    )
    prepared = prepare_port_value_for_put(art)
    assert prepared.artifact_path == ""
    assert not (prepared.metadata or {}).get("labels_path")
    assert not (prepared.metadata or {}).get("source_model_path")
    assert not (prepared.metadata or {}).get("source")
    assert {r.role for r in prepared.refs} >= {"deployment_bundle", "labels"}
    raw = dump_port_value(prepared)
    assert str(model).encode() not in raw
    assert b"/host/prod" not in raw

    uri = put_port_value(art)
    remote = tmp_path / "worker_write" / "_inputs" / "deployment"
    got = get_port_value(uri, materialize_dir=remote)
    assert Path(got.artifact_path).read_bytes().startswith(b"TFL3")
    assert Path(got.metadata["labels_path"]).read_text(encoding="utf-8") == "yes\nno\n"
    assert remote.resolve() in Path(got.artifact_path).resolve().parents
    assert got.metadata.get("display_name") == "demo"


def test_deployment_artifact_fail_closed_missing_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    from app.core.distributed.transfer import UnreclaimedHostPathError, prepare_port_value_for_put
    from app.models.deployment_artifact import DeploymentArtifact

    missing = tmp_path / "nope" / "model.tflite"
    art = DeploymentArtifact(
        artifact_path=str(missing),
        model_format="tflite",
        metadata={"source_model_path": "/abs/missing/saved_model"},
    )
    with pytest.raises(UnreclaimedHostPathError):
        prepare_port_value_for_put(art)


def test_csv_table_result_path_round_trip(tmp_path, monkeypatch):
    """CsvTableResult duck-type: pack path role and hydrate under materialize root."""
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    from typing import Any, List

    from pydantic import Field

    from app.core.artifacts.artifact_pack import (
        apply_packed_refs,
        collect_path_bearing_roles,
        materialize_refs_onto,
    )
    from app.core.nodes.ports import PortDataType
    from app.models.artifact_ref import ArtifactRef

    class CsvTableResult(PortDataType):
        path: str = ""
        operation: str = ""
        rows: list = Field(default_factory=list)
        row_count: int = 0
        metadata: dict[str, Any] = Field(default_factory=dict)
        refs: List[ArtifactRef] = Field(default_factory=list)

    csv_path = tmp_path / "table.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    art = CsvTableResult(
        path=str(csv_path),
        operation="read",
        rows=[{"a": "1", "b": "2"}],
        row_count=1,
        refs=[
            ArtifactRef(
                role="other",
                kind="file",
                filename="table.csv",
                relative_path="table.csv",
                source_path=str(csv_path),
                media_type="text/csv",
            )
        ],
    )
    blobs: dict[str, bytes] = {}

    def put(data: bytes):
        import hashlib

        digest = hashlib.sha256(data).hexdigest()
        uri = f"artifact://test/{digest}"
        blobs[uri] = data
        return uri, digest

    packed = apply_packed_refs(art, collect_path_bearing_roles(art), put_companion=put)
    assert packed.path == ""
    assert all(not r.source_path for r in packed.refs)

    def get(uri: str, expected_sha256=None):
        return blobs[uri]

    got = materialize_refs_onto(packed, dest_root=tmp_path / "mat", get_companion=get)
    assert Path(got.path).read_text(encoding="utf-8").startswith("a,b")
    assert got.rows == [{"a": "1", "b": "2"}]
    assert str(csv_path) != got.path
