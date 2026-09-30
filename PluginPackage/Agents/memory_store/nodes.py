"""MemoryStoreNode — Short/long-term agent memory

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading

try:
    import fcntl
except ImportError:  # pragma: no cover — non-POSIX: thread lock only
    fcntl = None  # type: ignore[assignment]

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("memory_store.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

MemoryOp = _types.MemoryOp
MemoryRecord = _types.MemoryRecord

log = logging.getLogger(__name__)

def _T(types: Any, name: str, **kwargs: Any) -> Any:
    cls = getattr(types, name, None) if types is not None else None
    if cls is None:
        return kwargs
    fields = getattr(cls, "model_fields", None)
    if isinstance(fields, dict) and fields:
        kwargs = {k: v for k, v in kwargs.items() if k in fields}
    return cls(**kwargs)

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj

def _text(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, list):
        return "\n".join(_text(x) for x in obj)
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("text", "query", "content", "answer", "user", "path", "value", "final"):
            if data.get(key):
                return str(data[key])
        return json.dumps(data, default=str)
    return str(obj)


SET_OPS = ("set", "put", "upsert")
GET_OPS = ("get",)
DELETE_OPS = ("delete",)

# Process-local store for backend="memory" (not persisted).
_MEMORY: dict[str, dict[str, Any]] = {}
_MEMORY_LOCK = threading.Lock()
_FILE_LOCKS: dict[str, threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def store_path(persist_path: str) -> Path:
    """``*.json`` → that file; anything else is a directory holding ``memory.json``."""
    p = Path(str(persist_path or "workspace/artifacts/agent_memory"))
    return p if p.suffix.lower() == ".json" else p / "memory.json"


def _parse_op(raw: Any) -> tuple[str, str, Any]:
    """Return ``(op, key, value)``. A write without ``op`` is inferred as ``set``."""
    explicit_op = None
    if hasattr(raw, "model_dump"):
        fields_set = getattr(raw, "model_fields_set", set())
        data = raw.model_dump()
        if "op" in fields_set:
            explicit_op = data.get("op")
        has_value = "value" in fields_set or data.get("value") is not None
    else:
        data = raw
        has_value = isinstance(data, dict) and "value" in data
        if isinstance(data, dict) and data.get("op"):
            explicit_op = data.get("op")
    if not isinstance(data, dict):
        return "get", _text(raw), None
    op = str(explicit_op or ("set" if has_value else "get")).lower()
    return op, str(data.get("key") or ""), data.get("value")


@contextlib.contextmanager
def _locked(path: Path, exclusive: bool):
    """Inter-process (fcntl) + intra-process lock on ``<path>.lock``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with _FILE_LOCKS_GUARD:
        tlock = _FILE_LOCKS.setdefault(str(lock_path.resolve()), threading.Lock())
    with tlock:
        fh = open(lock_path, "a+")
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()


def _read_store(path: Path) -> dict:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"memory_store: {path} does not contain a JSON object")
    return data


def _write_store(path: Path, store: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(store, fh, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _apply(bucket: dict, op: str, key: str, value: Any) -> tuple[Any, bool]:
    """Apply *op* to *bucket*; return ``(record_value, mutated)``."""
    if op in SET_OPS:
        bucket[key] = value
        return value, True
    if op in DELETE_OPS:
        bucket.pop(key, None)
        return None, True
    return bucket.get(key), False


def _memory(config, inputs, types):
    op, key, value = _parse_op(inputs.get("input"))
    if op not in SET_OPS + GET_OPS + DELETE_OPS:
        raise ValueError(f"memory_store: unknown op {op!r} (use set/put/upsert, get, delete)")
    if not key:
        raise ValueError("memory_store: key is required")
    ns = str(config.namespace or "default")
    backend = str(config.backend)
    meta = {"namespace": ns, "op": op, "backend": backend}

    if backend == "memory":
        with _MEMORY_LOCK:
            result, _ = _apply(_MEMORY.setdefault(ns, {}), op, key, value)
        return _T(types, "MemoryRecord", key=key, value=result, metadata=meta)

    if backend != "json":
        raise ValueError(f"memory_store: unknown backend {backend!r}")
    path = store_path(config.persist_path)
    meta["path"] = str(path)
    mutating = op not in GET_OPS
    with _locked(path, exclusive=mutating):
        store = _read_store(path)
        bucket = store.setdefault(ns, {})
        result, mutated = _apply(bucket, op, key, value)
        if mutated:
            _write_store(path, store)
    return _T(types, "MemoryRecord", key=key, value=result, metadata=meta)



class MemoryStoreNode(Node):
    """Short/long-term agent memory"""

    node_type: ClassVar[str] = "memory_store"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="memory_store",
        label="Memory Store",
        description="Short/long-term agent memory",
        category="Agents",
        version="0.1.0",
        tags=["agents"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="MemoryOp {op?, key, value?} — op inferred as set when value is present"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="MemoryRecord NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        backend: Literal["json", "memory"] = Field(default="json", title="Backend", description="json: locked, atomically-written JSON file; memory: process-local (not persisted).")
        persist_path: str = Field(default="workspace/artifacts/agent_memory", title="Persist path", description="*.json file, or a directory that will hold memory.json.")
        namespace: str = Field(default="default", title="Namespace", description="Key namespace inside the store.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'agents' / 'memory_store'
        if stub:
            log.warning(
                "%s: stub mode (config.stub=True) returned a placeholder, not a real result",
                getattr(self, "node_type", type(self).__name__),
            )
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            _out = out_dir / 'stub'
            result = MemoryRecord()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"memory_store: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _memory(self.config, inputs, _types)}
