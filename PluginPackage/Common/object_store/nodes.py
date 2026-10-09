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
    """Existing file paths carried by *value* (F19 / F-11).

    Uses the canonical payload contract (:func:`app.core.nodes.payload.payload_paths`):
    plain strings / ``Path``, dicts with ``path``/``file``/``paths``/``files``,
    objects with ``.path`` / ``.source_path`` (CsvTableResult, ArtifactRef …),
    ``refs`` lists, wrapper ``data`` and nested lists.
    """
    from app.core.nodes.payload import payload_paths

    out: list[Path] = []
    seen: set[str] = set()
    for raw in payload_paths(value):
        p = Path(raw)
        if not p.is_absolute():
            try:
                p = _jail(raw, "input path")
            except RuntimeError:
                p = Path(raw)
        if p.exists() and p.is_file() and str(p) not in seen:
            seen.add(str(p))
            out.append(p)
    return out


def _looks_like_chunks(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if isinstance(item, dict):
            if "text" not in item:
                return False
        elif not hasattr(item, "text"):
            return False
    return True


def _inline_bytes(value: Any) -> tuple[bytes, str, str] | None:
    """Serialise an inline payload → (bytes, extension, media type); None if empty."""
    import csv
    import io
    import json

    from app.core.nodes.payload import unwrap_payload

    data = unwrap_payload(value)
    if data is None:
        return None
    if isinstance(data, bytes):
        return (data, ".bin", "application/octet-stream") if data else None
    if isinstance(data, str):
        return (data.encode("utf-8"), ".txt", "text/plain") if data else None
    if isinstance(data, (int, float, bool)):
        return json.dumps(data).encode("utf-8"), ".json", "application/json"
    if isinstance(data, list) and data and all(isinstance(r, dict) for r in data):
        cols: list[str] = []
        for r in data:
            for k in r:
                if str(k) not in cols:
                    cols.append(str(k))
        flat = all(not isinstance(v, (dict, list)) for r in data for v in r.values())
        if flat:
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in data:
                w.writerow({str(k): v for k, v in r.items()})
            return buf.getvalue().encode("utf-8"), ".csv", "text/csv"
    if isinstance(data, (dict, list)):
        if not data:
            return None
        return (
            json.dumps(data, indent=2, sort_keys=True, default=str).encode("utf-8"),
            ".json",
            "application/json",
        )
    return str(data).encode("utf-8"), ".txt", "text/plain"


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
        version="1.1.0",
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
            description="put: files (paths, {path}, objects with .path, CsvTableResult) or inline data (dict, rows, text, CodeResult) — inline data is saved as JSON/CSV/text; unused for list/get",
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
        if _looks_like_chunks(value) and not _paths_from(value):
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
        if not files and key_cfg and value is None:
            # A configured key that names an existing workspace file is a source.
            try:
                cand = _jail(key_cfg, "config.key")
            except RuntimeError:
                cand = None
            if cand is not None and cand.is_file():
                files.append(cand)
                key_cfg = ""
        prefix = (self.config.prefix or "").rstrip("/")
        if not files:
            # F19 (F-11): inline payloads (dict, rows, CodeResult.data, text) are
            # serialised and stored — never a silent no-op.
            blob = _inline_bytes(value)
            if blob is None:
                raise RuntimeError(
                    "ObjectStoreNode: put received nothing to store — the input has no "
                    "existing file path and no inline data (got "
                    f"{type(value).__name__}). Connect a node that outputs files or data."
                )
            content, ext, media = blob
            key = key_cfg or self._inline_key(prefix, content, ext)
            dest = _key_path(root, key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            self._publish(root, [dest])
            return _object_ref_with_refs(
                key=key, uri=str(dest), backend="local", size=dest.stat().st_size,
                metadata={"source": "inline", "media_type": media},
            )
        for src in files:
            name = src.name
            key = f"{prefix}/{name}" if prefix else name
            if len(files) == 1 and key_cfg and not key_cfg.endswith("/"):
                key = key_cfg
            elif key_cfg.endswith("/"):
                key = f"{key_cfg.rstrip('/')}/{name}"
            dest = _key_path(root, key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            written.append(dest)
            refs.append(_object_ref_with_refs(
                key=key, uri=str(dest), backend="local", size=dest.stat().st_size,
                metadata={"source": "file", "source_path": str(src)},
            ))
        self._publish(root, written)
        return refs[0] if len(refs) == 1 else refs

    def _inline_key(self, prefix: str, content: bytes, ext: str) -> str:
        import hashlib

        node = (getattr(self, "node_id", "") or "object").replace("/", "-") or "object"
        digest = hashlib.sha256(content).hexdigest()[:12]
        name = f"{node}-{digest}{ext}"
        return f"{prefix}/{name}" if prefix else name

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
        # F19 (F-02): the S3 endpoint (AWS default or AWS_ENDPOINT_URL[_S3]) is
        # network egress — validate it against the egress policy before any call.
        from app.core.trust.egress import HttpEgressError, validate_http_egress_url

        endpoint = str(getattr(getattr(client, "meta", None), "endpoint_url", "") or "")
        if endpoint:
            try:
                validate_http_egress_url(endpoint)
            except HttpEgressError as exc:
                raise RuntimeError(f"ObjectStoreNode: S3 endpoint refused: {exc}") from exc
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
        prefix = (self.config.prefix or "").rstrip("/")
        if not files:
            blob = _inline_bytes(value)
            if blob is None:
                raise RuntimeError(
                    "ObjectStoreNode: s3 put received nothing to store (no file path and "
                    "no inline data)."
                )
            content, ext, media = blob
            key = (self.config.key or "").strip() or self._inline_key(prefix, content, ext)
            client.put_object(Bucket=bucket, Key=key, Body=content, ContentType=media)
            return _object_ref_with_refs(
                key=key, uri=f"s3://{bucket}/{key}", backend="s3", size=len(content),
                metadata={"source": "inline", "media_type": media},
            )
        refs = []
        for src in files:
            key = f"{prefix}/{src.name}" if prefix else (self.config.key or src.name)
            client.upload_file(str(src), bucket, key)
            refs.append(_object_ref_with_refs(key=key, uri=f"s3://{bucket}/{key}", backend="s3", size=src.stat().st_size))
        return refs[0] if len(refs) == 1 else refs
