"""ObjectStoreNode — get / put / list for local filesystem or S3."""
from __future__ import annotations

import importlib
import logging
import shutil
from pathlib import Path
from typing import Any, ClassVar, Literal
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.artifact_ref import ArtifactRef

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("object_store.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ObjectRef = _types.ObjectRef
ObjectList = _types.ObjectList

log = logging.getLogger(__name__)


DEFAULT_ROOT = "workspace/artifacts/object_store"


def _jail(raw: str, what: str) -> Path:
    """Workspace-relative path → absolute path inside project_dir (no abs / ``..``)."""
    from app.core.paths.write_paths import jail_relative_path

    try:
        return jail_relative_path(raw, what=f"ObjectStoreNode: {what}")
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def _project_root() -> Path:
    from app.core.config import project_dir

    return project_dir().resolve()


def _jail_input(p: Path) -> Path:
    """Input file paths from upstream nodes: relative → jailed; absolute → must be inside the workspace."""
    if not p.is_absolute():
        return _jail(str(p), "input path")
    resolved = p.resolve()
    if not resolved.is_relative_to(_project_root()):
        raise RuntimeError("ObjectStoreNode: input path resolves outside the workspace")
    return resolved


def _key_path(root: Path, key: str) -> Path:
    """``root/key`` with the key confined to *root* (no absolute key, no ``..``)."""
    text = str(key or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        raise RuntimeError(f"ObjectStoreNode: invalid object key {key!r}")
    if any(part == ".." for part in text.split("/")):
        raise RuntimeError("ObjectStoreNode: object key must not contain '..'")
    dest = (root / text).resolve()
    if not dest.is_relative_to(root.resolve()):
        raise RuntimeError("ObjectStoreNode: object key escapes the store root")
    return dest


def _chunk_text(item: Any) -> tuple[str, str]:
    if isinstance(item, dict):
        return str(item.get("chunk_id") or "chunk"), str(item.get("text") or "")
    cid = str(getattr(item, "chunk_id", "") or "chunk")
    text = str(getattr(item, "text", "") or "")
    return cid, text


def _paths_from(value: Any) -> list[Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        p = Path(value)
        return [p] if p.exists() else []
    if isinstance(value, dict) and value.get("path"):
        p = Path(str(value["path"]))
        return [p] if p.exists() else []
    if hasattr(value, "paths"):
        out = []
        for p in value.paths or []:
            pp = Path(str(p))
            if pp.exists():
                out.append(pp)
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, (str, Path)):
                p = Path(item)
                if p.exists() and p.is_file():
                    out.append(p)
        return out
    return []



def _object_ref_with_refs(*, key: str, uri: str, backend: str, size: int = 0, metadata: dict | None = None) -> "ObjectRef":
    from .types import ObjectRef
    refs = []
    backend_l = (backend or "").lower()
    if backend_l in {"", "local", "file"} and uri and not str(uri).startswith(("s3://", "artifact://", "http://", "https://")):
        src = Path(uri)
        if src.exists():
            kind = "dir" if src.is_dir() else "file"
            refs.append(
                ArtifactRef(
                    role="other",
                    kind=kind,  # type: ignore[arg-type]
                    filename=src.name or key or "object",
                    relative_path=src.name or key or "object",
                    source_path=str(src),
                )
            )
    return ObjectRef(key=key, uri=uri, backend=backend, size=size, metadata=dict(metadata or {}), refs=refs)


class ObjectStoreNode(Node):
    """Put, get, or list objects in a local directory or an S3 bucket."""

    node_type: ClassVar[str] = "object_store"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="object_store",
        label="Object Store",
        description=(
            "Get/put/list objects. backend=local copies files under a workspace-jailed root "
            "(default workspace/artifacts/object_store); backend=s3 uses boto3 when installed."
        ),
        category="Output",
        version="1.0.0",
        tags=["storage", "s3", "export", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=False,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object | None,
            cardinality="single",
            required=False,
            description="Files, caption paths, or Chunk list to put; unused for list",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=object,
            description="ObjectRef, list[ObjectRef], or ObjectList",
        )
    }

    class Config(NodeConfig):
        backend: Literal["local", "s3"] = Field(default='local', title="Backend", description="Implementation backend. One of: local, s3.")
        operation: Literal["get", "put", "list"] = Field(default='put', title="Operation", description="Operation to perform. One of: get, put, list.")
        root: str = Field(default=DEFAULT_ROOT, title="Root", description="Local store root, relative to the Graphyn workspace (absolute paths and '..' are rejected).")
        key: str = Field(default='', title="Object key", description="Object key within the bucket (path-like).")
        prefix: str = Field(default='', title="Prefix", description="Key prefix within the bucket / namespace.")
        bucket: str = Field(default='', title="Bucket", description="Object-store bucket name.")
        dest: str = Field(default='', title="Dest", description="Destination file for get, relative to the Graphyn workspace (absolute paths and '..' are rejected).")

    def process(self, value):
        backend = (self.config.backend or "local").lower()
        op = (self.config.operation or "put").lower()
        if backend == "s3":
            return self._s3(op, value)
        if backend != "local":
            raise RuntimeError(
                f"ObjectStoreNode: unknown backend {backend!r}. Use local or s3."
            )
        return self._local(op, value)

    def _local_root(self) -> Path:
        root = _jail(self.config.root or DEFAULT_ROOT, "config.root")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _publish(self, root: Path, written: list[Path]) -> None:
        files = []
        for p in written:
            try:
                files.append({"path": p.relative_to(root).as_posix(), "size": p.stat().st_size})
            except (ValueError, OSError):
                continue
        if files:
            self.publish_files(root, files)

    def _local(self, op: str, value: Any):
        root = self._local_root()
        if op == "list":
            prefix = self.config.prefix or self.config.key or ""
            keys = []
            for p in sorted(root.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(root).as_posix()
                if prefix and not rel.startswith(prefix):
                    continue
                keys.append(rel)
            return ObjectList(keys=keys, backend="local", prefix=prefix, metadata={"root": str(root)})
        if op == "get":
            key = (self.config.key or "").strip()
            if not key:
                raise RuntimeError("ObjectStoreNode: get requires config.key")
            src = _key_path(root, key)
            if not src.is_file():
                raise RuntimeError(f"ObjectStoreNode: local key not found: {key}")
            dest = _jail(self.config.dest, "config.dest") if self.config.dest else src
            if dest.resolve() != src.resolve():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                self._publish(dest.parent, [dest])
            return _object_ref_with_refs(key=key, uri=str(dest), backend="local", size=src.stat().st_size)
        if op != "put":
            raise RuntimeError(f"ObjectStoreNode: unknown operation {op!r}. Use get, put, or list.")

        refs: list = []
        written: list[Path] = []
        # Chunks → write text files then store
        if isinstance(value, list) and value and not _paths_from(value):
            prefix = (self.config.prefix or self.config.key or "chunks").rstrip("/")
            for item in value:
                cid, text = _chunk_text(item)
                safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in cid) or "chunk"
                key = f"{prefix}/{safe}.md"
                dest = _key_path(root, key)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
                written.append(dest)
                refs.append(_object_ref_with_refs(key=key, uri=str(dest), backend="local", size=dest.stat().st_size))
            self._publish(root, written)
            return refs

        files = [_jail_input(p) for p in _paths_from(value)]
        key_cfg = (self.config.key or "").strip()
        if key_cfg and not key_cfg.startswith("/") and ".." not in key_cfg.split("/"):
            # A configured key that names an existing workspace file is a source.
            try:
                cand = _jail(key_cfg, "config.key")
            except RuntimeError:
                cand = None
            if cand is not None and cand.is_file():
                files.append(cand)
        # Allow putting a single configured source path via dest/key
        if not files and key_cfg:
            # treat input as raw text
            if isinstance(value, str) and not Path(value).exists():
                dest = _key_path(root, key_cfg)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(value, encoding="utf-8")
                self._publish(root, [dest])
                return _object_ref_with_refs(key=key_cfg, uri=str(dest), backend="local", size=dest.stat().st_size)
        if not files:
            return []
        prefix = (self.config.prefix or "").rstrip("/")
        for src in files:
            name = src.name
            key = f"{prefix}/{name}" if prefix else name
            if len(files) == 1 and key_cfg and not key_cfg.endswith("/"):
                key = key_cfg
            dest = _key_path(root, key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            written.append(dest)
            refs.append(_object_ref_with_refs(key=key, uri=str(dest), backend="local", size=dest.stat().st_size))
        self._publish(root, written)
        return refs[0] if len(refs) == 1 else refs

    def _s3(self, op: str, value: Any):
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "ObjectStoreNode: backend='s3' requires boto3. "
                "Install boto3 or use backend='local'."
            ) from exc
        bucket = (self.config.bucket or "").strip()
        if not bucket:
            raise RuntimeError("ObjectStoreNode: s3 backend requires config.bucket")
        client = boto3.client("s3")
        if op == "list":
            prefix = self.config.prefix or self.config.key or ""
            keys = []
            token = None
            while True:
                kwargs = {"Bucket": bucket, "Prefix": prefix}
                if token:
                    kwargs["ContinuationToken"] = token
                resp = client.list_objects_v2(**kwargs)
                for obj in resp.get("Contents") or []:
                    keys.append(obj.get("Key"))
                if not resp.get("IsTruncated"):
                    break
                token = resp.get("NextContinuationToken")
            return ObjectList(keys=keys, backend="s3", prefix=prefix, metadata={"bucket": bucket})
        if op == "get":
            key = self.config.key
            if not key:
                raise RuntimeError("ObjectStoreNode: get requires config.key")
            if self.config.dest:
                dest = _jail(self.config.dest, "config.dest")
            else:
                dest = _key_path(_jail(self.config.root or DEFAULT_ROOT, "config.root"), key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(bucket, key, str(dest))
            self._publish(dest.parent, [dest])
            return _object_ref_with_refs(key=key, uri=f"s3://{bucket}/{key}", backend="s3", size=dest.stat().st_size)
        files = [_jail_input(p) for p in _paths_from(value)]
        if not files:
            raise RuntimeError("ObjectStoreNode: s3 put requires file input")
        refs = []
        prefix = (self.config.prefix or "").rstrip("/")
        for src in files:
            key = f"{prefix}/{src.name}" if prefix else (self.config.key or src.name)
            client.upload_file(str(src), bucket, key)
            refs.append(_object_ref_with_refs(key=key, uri=f"s3://{bucket}/{key}", backend="s3", size=src.stat().st_size))
        return refs[0] if len(refs) == 1 else refs
