"""ObjectStoreNode — get / put / list for local filesystem or S3."""
from __future__ import annotations

import importlib
import logging
import shutil
from pathlib import Path
from typing import Any, ClassVar

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

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


class ObjectStoreNode(Node):
    """Put, get, or list objects in a local directory or an S3 bucket."""

    node_type: ClassVar[str] = "object_store"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="object_store",
        label="Object Store",
        description=(
            "Get/put/list objects. backend=local copies files under a root; "
            "backend=s3 uses boto3 when installed."
        ),
        category="Output",
        version="1.0.0",
        tags=["storage", "s3", "export", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
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
        backend: str = "local"  # local | s3
        operation: str = "put"  # get | put | list
        root: str = "output/object_store"
        key: str = ""
        prefix: str = ""
        bucket: str = ""
        dest: str = ""  # local dest for get

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
        root = Path(self.config.root or "output/object_store")
        root.mkdir(parents=True, exist_ok=True)
        return root

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
            key = (self.config.key or "").lstrip("/")
            if not key:
                raise RuntimeError("ObjectStoreNode: get requires config.key")
            src = root / key
            if not src.is_file():
                raise RuntimeError(f"ObjectStoreNode: local key not found: {key}")
            dest = Path(self.config.dest or str(src))
            if dest.resolve() != src.resolve():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            return ObjectRef(key=key, uri=str(dest), backend="local", size=src.stat().st_size)
        if op != "put":
            raise RuntimeError(f"ObjectStoreNode: unknown operation {op!r}. Use get, put, or list.")

        refs: list = []
        # Chunks → write text files then store
        if isinstance(value, list) and value and not _paths_from(value):
            prefix = (self.config.prefix or self.config.key or "chunks").rstrip("/")
            for item in value:
                cid, text = _chunk_text(item)
                safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in cid) or "chunk"
                key = f"{prefix}/{safe}.md"
                dest = root / key
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
                refs.append(ObjectRef(key=key, uri=str(dest), backend="local", size=dest.stat().st_size))
            return refs

        files = _paths_from(value)
        if self.config.key and Path(self.config.key).exists() and Path(self.config.key).is_file():
            files.append(Path(self.config.key))
        # Allow putting a single configured source path via dest/key
        if not files and (self.config.key or ""):
            # treat input as raw text
            if isinstance(value, str) and not Path(value).exists():
                key = self.config.key
                dest = root / key
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(value, encoding="utf-8")
                return ObjectRef(key=key, uri=str(dest), backend="local", size=dest.stat().st_size)
        if not files:
            return []
        prefix = (self.config.prefix or "").rstrip("/")
        for src in files:
            name = src.name
            key = f"{prefix}/{name}" if prefix else name
            if len(files) == 1 and self.config.key and not self.config.key.endswith("/"):
                key = self.config.key
            dest = root / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            refs.append(ObjectRef(key=key, uri=str(dest), backend="local", size=dest.stat().st_size))
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
            dest = Path(self.config.dest or Path(self.config.root) / key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(bucket, key, str(dest))
            return ObjectRef(key=key, uri=f"s3://{bucket}/{key}", backend="s3", size=dest.stat().st_size)
        files = _paths_from(value)
        if not files:
            raise RuntimeError("ObjectStoreNode: s3 put requires file input")
        refs = []
        prefix = (self.config.prefix or "").rstrip("/")
        for src in files:
            key = f"{prefix}/{src.name}" if prefix else (self.config.key or src.name)
            client.upload_file(str(src), bucket, key)
            refs.append(ObjectRef(key=key, uri=f"s3://{bucket}/{key}", backend="s3", size=src.stat().st_size))
        return refs[0] if len(refs) == 1 else refs
