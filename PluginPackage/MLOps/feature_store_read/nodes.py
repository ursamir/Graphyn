"""FeatureStoreReadNode — Light feature store read

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

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
        _types = importlib.import_module("feature_store_read.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

FeatureStoreRef = _types.FeatureStoreRef

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj

def _as_list(obj: Any) -> list:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, tuple):
        return list(obj)
    return [obj]

def _parse_ts(value: str):
    from datetime import datetime, timezone

    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _versions(entry: Any) -> list[dict]:
    # format 2: list of {"ts", "data"}; legacy: the row itself
    if isinstance(entry, list) and all(isinstance(v, dict) and "data" in v for v in entry):
        return entry
    return [{"ts": "", "data": entry}]


def _feature_read(config, inputs, types):
    dumped = _dump(inputs.get("store"))
    ref_path = dumped.get("path") if isinstance(dumped, dict) else (dumped if isinstance(dumped, str) else None)
    path = Path(str(ref_path or _cfg(config, "persist_path", "") or ""))
    if not str(path) or not path.is_file():
        raise FileNotFoundError(f"feature store not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    entities = raw.get("entities") if isinstance(raw, dict) and raw.get("_format") == 2 else raw
    if not isinstance(entities, dict):
        raise ValueError(f"feature_store_read: malformed store {path}")
    as_of_raw = str(_cfg(config, "as_of", "") or "").strip()
    as_of = _parse_ts(as_of_raw) if as_of_raw else None

    def pick(entry: Any) -> Any:
        versions = _versions(entry)
        if as_of is None:
            return versions[-1]["data"]
        best, best_ts = None, None
        for v in versions:
            ts = _parse_ts(v["ts"]) if v.get("ts") else None
            if ts is not None and ts > as_of:
                continue
            # un-timestamped legacy rows sort before any timestamped row
            if best is None or (ts is not None and (best_ts is None or ts >= best_ts)):
                best, best_ts = v, ts
        return None if best is None else best["data"]

    keys = [str(k) for k in _as_list(inputs.get("keys"))]
    selected = keys if keys else list(entities)
    missing = [k for k in selected if k not in entities]
    if missing:
        log.info("feature_store_read: %d key(s) not in store: %s", len(missing), missing[:10])
    rows = []
    for k in selected:
        if k in entities:
            row = pick(entities[k])
            if row is not None:
                rows.append(row)
    return rows



class FeatureStoreReadNode(Node):
    """Light feature store read"""

    node_type: ClassVar[str] = "feature_store_read"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="feature_store_read",
        label="Feature Store Read",
        description="Light feature store read",
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
        "store": InputPort(name="store", data_type=object, required=True, description="FeatureStoreRef NEW"),
        "keys": InputPort(name="keys", data_type=object, required=True, description="list[str]"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[FeatureArray]"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        persist_path: str = Field(default='workspace/artifacts/feature_store', title="Persist path", description="Persist path.")
        as_of: str = Field(default='', title="As of", description="ISO-8601 timestamp: return each entity's latest version written at/before this time. Empty: latest.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'feature_store_read'
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
            result = []
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"feature_store_read: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _feature_read(self.config, inputs, _types)}
