"""DatasetDiffNode — Diff two DatasetArtifacts

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import hashlib
from collections import Counter

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any
from pydantic import Field

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.dataset_artifact import DatasetArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("dataset_diff.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DatasetDiffReport = _types.DatasetDiffReport

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

_SPLITS = ("train", "val", "test")


def _canon(obj: Any, h: "hashlib._Hash") -> None:
    """Feed a type-tagged, length-prefixed canonical encoding of ``obj`` into ``h``."""
    def put(tag: bytes, payload: bytes) -> None:
        h.update(tag)
        h.update(len(payload).to_bytes(8, "big"))
        h.update(payload)

    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    if obj is None:
        put(b"N", b"")
    elif isinstance(obj, bool):
        put(b"B", b"1" if obj else b"0")
    elif isinstance(obj, np.ndarray):
        a = np.ascontiguousarray(obj)
        put(b"A", f"{a.dtype.str}|{a.shape}".encode())
        put(b"D", a.tobytes())
    elif isinstance(obj, np.generic):
        _canon(obj.item(), h)
    elif isinstance(obj, int):
        put(b"I", str(obj).encode())
    elif isinstance(obj, float):
        put(b"F", repr(obj).encode())
    elif isinstance(obj, str):
        put(b"S", obj.encode("utf-8"))
    elif isinstance(obj, bytes):
        put(b"Y", obj)
    elif isinstance(obj, dict):
        keys = sorted(obj, key=str)
        put(b"M", str(len(keys)).encode())
        for k in keys:
            put(b"K", str(k).encode("utf-8"))
            _canon(obj[k], h)
    elif isinstance(obj, (list, tuple)):
        put(b"L", str(len(obj)).encode())
        for item in obj:
            _canon(item, h)
    else:
        put(b"O", f"{type(obj).__name__}:{obj!r}".encode("utf-8"))


def _hash(obj: Any) -> str:
    h = hashlib.sha256()
    _canon(obj, h)
    return h.hexdigest()


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _is_array_dataset(obj: Any) -> bool:
    return any(_get(obj, f"X_{sp}") is not None for sp in _SPLITS)


def _array_splits(obj: Any) -> dict[str, dict[str, Any]]:
    """Per split: summary + multiset of row hashes (X row + label)."""
    out: dict[str, dict[str, Any]] = {}
    for sp in _SPLITS:
        X = _get(obj, f"X_{sp}")
        y = _get(obj, f"y_{sp}")
        X = np.zeros((0,), dtype=np.float32) if X is None else np.asarray(X)
        y = np.zeros((0,), dtype=np.int32) if y is None else np.asarray(y)
        n = int(X.shape[0]) if X.ndim >= 1 else 0
        if y.size and y.shape[0] != n:
            raise ValueError(f"dataset_diff: split {sp!r} has {n} X rows but {y.shape[0]} labels")
        rows: list[str] = []
        for i in range(n):
            rows.append(_hash([X[i], y[i] if y.size else None]))
        out[sp] = {
            "summary": {
                "n_rows": n,
                "X_shape": list(X.shape),
                "X_dtype": X.dtype.str,
                "y_shape": list(y.shape),
                "y_dtype": y.dtype.str,
                "content_hash": _hash([X, y]),
            },
            "rows": rows,
            "keys": None,
        }
    return out


def _records_of(obj: Any) -> dict[str, list]:
    data = obj.model_dump() if hasattr(obj, "model_dump") else obj
    if isinstance(data, dict):
        for key in ("records", "rows", "samples", "items", "data"):
            if isinstance(data.get(key), list):
                return {"all": data[key]}
        if data and all(isinstance(v, list) for v in data.values()):
            return {str(k): v for k, v in data.items()}
        raise TypeError("dataset_diff: dict input has no records/rows/samples list or split->list mapping")
    if isinstance(data, (list, tuple)):
        return {"all": list(data)}
    raise TypeError(f"dataset_diff: unsupported input type {type(obj).__name__}")


def _record_splits(obj: Any, hash_fields: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for sp, rows in _records_of(obj).items():
        row_hashes: list[str] = []
        keys: dict[str, str] | None = {} if hash_fields else None
        for i, row in enumerate(rows):
            rec = row.model_dump() if hasattr(row, "model_dump") else row
            content = _hash(rec)
            row_hashes.append(content)
            if keys is not None:
                if not isinstance(rec, dict):
                    raise ValueError(f"dataset_diff: hash_fields set but row {i} of split {sp!r} is not a record")
                missing = [f for f in hash_fields if f not in rec]
                if missing:
                    raise ValueError(f"dataset_diff: row {i} of split {sp!r} lacks hash_fields {missing}")
                key = _hash([rec[f] for f in hash_fields])
                if key in keys:
                    raise ValueError(f"dataset_diff: duplicate key {[rec[f] for f in hash_fields]!r} in split {sp!r}")
                keys[key] = content
        out[sp] = {
            "summary": {"n_rows": len(rows), "content_hash": _hash(row_hashes)},
            "rows": row_hashes,
            "keys": keys,
        }
    return out


def _splits(obj: Any, hash_fields: list[str]) -> tuple[dict[str, dict[str, Any]], list[str] | None]:
    if obj is None:
        raise ValueError("dataset_diff: input is None")
    if _is_array_dataset(obj):
        if hash_fields:
            raise ValueError("dataset_diff: hash_fields apply to record datasets, not X/y array datasets")
        labels = _get(obj, "labels")
        return _array_splits(obj), (list(labels) if isinstance(labels, (list, tuple)) else None)
    return _record_splits(obj, hash_fields), None


def _dataset_diff(config, inputs, types):
    raw_fields = _cfg(config, "hash_fields", None) or []
    if isinstance(raw_fields, str):
        raw_fields = [f.strip() for f in raw_fields.split(",") if f.strip()]
    hash_fields = [str(f) for f in raw_fields]
    left, left_labels = _splits(inputs.get("left"), hash_fields)
    right, right_labels = _splits(inputs.get("right"), hash_fields)

    added = removed = changed = 0
    per_split: dict[str, Any] = {}
    for sp in sorted(set(left) | set(right)):
        L = left.get(sp) or {"summary": None, "rows": [], "keys": {} if hash_fields else None}
        R = right.get(sp) or {"summary": None, "rows": [], "keys": {} if hash_fields else None}
        if hash_fields:
            lk, rk = L["keys"] or {}, R["keys"] or {}
            a = sum(1 for k in rk if k not in lk)
            r = sum(1 for k in lk if k not in rk)
            c = sum(1 for k in lk if k in rk and lk[k] != rk[k])
        else:
            lc, rc = Counter(L["rows"]), Counter(R["rows"])
            a = sum((rc - lc).values())
            r = sum((lc - rc).values())
            c = 0
        added, removed, changed = added + a, removed + r, changed + c
        equal = L["summary"] == R["summary"] and a == 0 and r == 0 and c == 0
        per_split[sp] = {"left": L["summary"], "right": R["summary"], "added": a, "removed": r,
                         "changed": c, "equal": equal}

    labels_equal = left_labels == right_labels
    equal = all(v["equal"] for v in per_split.values()) and labels_equal
    report = {
        "added": added,
        "removed": removed,
        "changed": changed,
        "details": {
            "equal": equal,
            "row_identity": "hash_fields" if hash_fields else "content",
            "hash_fields": hash_fields,
            "labels_equal": labels_equal,
            "splits": per_split,
        },
    }
    if bool(_cfg(config, "fail_on_drift", False)) and not equal:
        raise RuntimeError(
            f"dataset_diff: drift detected added={added} removed={removed} changed={changed} "
            f"labels_equal={labels_equal}"
        )
    return _T(types, "DatasetDiffReport", **report) if hasattr(types, "DatasetDiffReport") else report



class DatasetDiffNode(Node):
    """Diff two DatasetArtifacts"""

    node_type: ClassVar[str] = "dataset_diff"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="dataset_diff",
        label="Dataset Diff",
        description="Diff two DatasetArtifacts",
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
        "left": InputPort(name="left", data_type=object, required=True, description="DatasetArtifact"),
        "right": InputPort(name="right", data_type=object, required=True, description="DatasetArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="DatasetDiffReport NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        hash_fields: list[str] = Field(default_factory=list, title="Hash fields", description="Record key fields identifying a row; enables changed-row detection. Empty: rows compared by content hash.")
        fail_on_drift: bool = Field(default=False, title="Fail on drift", description="Fail on drift.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'dataset_diff'
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
            result = DatasetDiffReport()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"dataset_diff: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _dataset_diff(self.config, inputs, _types)}
