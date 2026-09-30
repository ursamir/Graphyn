"""FeatureStoreWriteNode — Light feature store write

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import hashlib
import json

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.feature_array import FeatureArray

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("feature_store_write.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

EmbeddingVector = _types.EmbeddingVector
FeatureStoreRef = _types.FeatureStoreRef

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

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

STORE_FORMAT = 2


def _jsonable(obj: Any) -> Any:
    """JSON default hook: keep numpy arrays/scalars lossless (never str()-truncated)."""
    try:
        import numpy as np  # type: ignore

        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.generic):
            return obj.item()
    except ImportError:
        pass
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, (set, tuple)):
        return list(obj)
    if isinstance(obj, (bytes, bytearray)):
        return bytes(obj).hex()
    raise TypeError(f"feature_store_write: value of type {type(obj).__name__} is not JSON-serialisable")


def _load_store(path: Path) -> dict:
    if not path.is_file():
        return {"_format": STORE_FORMAT, "entities": {}}
    raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    if isinstance(raw, dict) and raw.get("_format") == STORE_FORMAT and isinstance(raw.get("entities"), dict):
        return raw
    # Legacy flat {key: row} store: one un-timestamped version per entity.
    return {"_format": STORE_FORMAT, "entities": {str(k): [{"ts": "", "data": v}] for k, v in (raw or {}).items()}}


def _feature_write(config, inputs, types):
    from datetime import datetime, timezone

    path = Path(str(_cfg(config, "persist_path", "") or "workspace/artifacts/feature_store.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    store = _load_store(path)
    features = inputs.get("features")
    if features is None:
        raise ValueError("feature_store_write: features input is required")
    rows = list(features) if isinstance(features, (list, tuple)) else [features]
    keys_cfg = _cfg(config, "entity_keys", None)
    keys = ["id"] if keys_cfg is None else [str(k) for k in keys_cfg]
    ts_field = str(_cfg(config, "event_time_field", "") or "")
    now = datetime.now(timezone.utc).isoformat()
    written: list[str] = []
    for i, row in enumerate(rows):
        data = _dump(row)
        if not isinstance(data, dict):
            data = {"value": data}
        data = json.loads(json.dumps(data, default=_jsonable))
        if keys:
            missing = [k for k in keys if data.get(k) is None]
            if missing:
                raise ValueError(
                    f"feature_store_write: row {i} lacks entity key field(s) {missing}; "
                    "set entity_keys to fields present on every row, or [] to key by content hash"
                )
            key = "|".join(str(data[k]) for k in keys)
        else:
            key = "sha256:" + hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
        ts = str(data.get(ts_field)) if ts_field and data.get(ts_field) is not None else now
        store["entities"].setdefault(key, []).append({"ts": ts, "data": data})
        written.append(key)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(store, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    feature_set = "|".join(keys) if keys else "content_hash"
    return _T(
        types,
        "FeatureStoreRef",
        path=str(path),
        feature_set=feature_set,
        metadata={"rows_written": len(rows), "entities": len(store["entities"]), "keys": written[:100], "written_at": now},
    )



class FeatureStoreWriteNode(Node):
    """Light feature store write"""

    node_type: ClassVar[str] = "feature_store_write"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="feature_store_write",
        label="Feature Store Write",
        description="Light feature store write",
        category="MLOps",
        version="0.1.0",
        tags=["mlops"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "features": InputPort(name="features", data_type=object, required=True, description="list[FeatureArray]|list[EmbeddingVector]"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="FeatureStoreRef NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        persist_path: str = Field(default='workspace/artifacts/feature_store', title="Persist path", description="JSON store file path.")
        entity_keys: list[str] = Field(default_factory=lambda: ["id"], title="Entity keys", description="Row fields forming the entity key (missing field is an error). [] keys rows by content hash.")
        event_time_field: str = Field(default="", title="Event time field", description="Row field holding an ISO event time (used by feature_store_read as_of). Empty: write time.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'feature_store_write'
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
            result = FeatureStoreRef()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"feature_store_write: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _feature_write(self.config, inputs, _types)}
