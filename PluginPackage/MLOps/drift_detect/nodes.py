"""DriftDetectNode — Feature/prediction drift

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import math

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
from pydantic import Field

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.dataset_artifact import DatasetArtifact
from app.models.feature_array import FeatureArray

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("drift_detect.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DriftReport = _types.DriftReport

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


def _to_2d(arr: Any) -> np.ndarray:
    a = np.asarray(arr, dtype=np.float64)
    if a.ndim == 0:
        a = a.reshape(1, 1)
    elif a.ndim == 1:
        a = a.reshape(-1, 1)
    elif a.ndim > 2:
        a = a.reshape(a.shape[0], -1)
    return a


def _matrix(obj: Any, split: str = "all") -> tuple[np.ndarray, list[str]]:
    """Coerce an input into a ``[n_samples, n_features]`` float matrix + feature names."""
    if obj is None:
        raise ValueError("drift_detect: input is None")
    # DatasetArtifact (or any object/dict with X_<split> arrays).
    data = obj if isinstance(obj, dict) else None
    getter = (lambda k: data.get(k)) if data is not None else (lambda k: getattr(obj, k, None))
    split_arrays = {sp: getter(f"X_{sp}") for sp in _SPLITS}
    if any(v is not None for v in split_arrays.values()):
        wanted = _SPLITS if split == "all" else (split,)
        parts = []
        for sp in wanted:
            v = split_arrays.get(sp)
            if v is None:
                continue
            a = np.asarray(v)
            if a.size == 0:
                continue
            parts.append(_to_2d(a))
        if not parts:
            raise ValueError(f"drift_detect: dataset has no non-empty X arrays for split={split!r}")
        m = np.concatenate(parts, axis=0)
        return m, [f"f{i}" for i in range(m.shape[1])]
    if isinstance(obj, np.ndarray):
        m = _to_2d(obj)
        return m, [f"f{i}" for i in range(m.shape[1])]
    # FeatureArray-like: .data [T, F]
    if not isinstance(obj, (dict, list, tuple)) and getattr(obj, "data", None) is not None:
        m = _to_2d(getattr(obj, "data"))
        return m, [f"f{i}" for i in range(m.shape[1])]
    if isinstance(obj, dict):
        for key in ("values", "features", "payload", "vector", "embedding", "data", "X"):
            if key in obj:
                return _matrix(obj[key], split)
        # Column mapping: {name: [values...]}
        cols = {k: v for k, v in obj.items() if isinstance(v, (list, tuple, np.ndarray))}
        if cols:
            names = sorted(cols)
            lengths = {len(np.asarray(cols[n]).reshape(-1)) for n in names}
            if len(lengths) != 1:
                raise ValueError("drift_detect: column mapping has unequal column lengths")
            m = np.stack([np.asarray(cols[n], dtype=np.float64).reshape(-1) for n in names], axis=1)
            return m, names
        raise ValueError("drift_detect: dict input has no array-like values")
    if isinstance(obj, (list, tuple)):
        items = list(obj)
        if not items:
            raise ValueError("drift_detect: input is empty")
        if all(isinstance(i, dict) and "data" not in i and "X_train" not in i for i in items):
            names = sorted({k for i in items for k, v in i.items()
                            if isinstance(v, (int, float, np.number)) and not isinstance(v, bool)})
            if not names:
                raise ValueError("drift_detect: record list has no numeric fields")
            m = np.array([[float(i.get(n, np.nan)) if i.get(n) is not None else np.nan for n in names]
                          for i in items], dtype=np.float64)
            return m, names
        if all(isinstance(i, (int, float, np.number)) and not isinstance(i, bool) for i in items):
            return _to_2d(items), ["f0"]
        if all(isinstance(i, (list, tuple, np.ndarray)) for i in items):
            try:
                m = _to_2d(np.asarray(items, dtype=np.float64))
            except ValueError as exc:
                raise ValueError(f"drift_detect: ragged nested list input ({exc})") from exc
            return m, [f"f{i}" for i in range(m.shape[1])]
        # List of FeatureArray / DatasetArtifact-like: stack rows.
        mats = [_matrix(i, split)[0] for i in items]
        widths = {mm.shape[1] for mm in mats}
        if len(widths) != 1:
            raise ValueError(f"drift_detect: items have inconsistent feature counts {sorted(widths)}")
        m = np.concatenate(mats, axis=0)
        return m, [f"f{i}" for i in range(m.shape[1])]
    if isinstance(obj, (int, float, np.number)) and not isinstance(obj, bool):
        return _to_2d([obj]), ["f0"]
    dumped = _dump(obj)
    if dumped is not obj:
        return _matrix(dumped, split)
    raise TypeError(f"drift_detect: unsupported input type {type(obj).__name__}")


def _psi_1d(ref: np.ndarray, cur: np.ndarray, bins: int) -> float:
    """PSI with bin edges from reference quantiles plus out-of-range tail bins."""
    qs = np.quantile(ref, np.linspace(0.0, 1.0, bins + 1))
    lo, hi = float(qs[0]), float(qs[-1])
    # Interior quantile edges plus explicit below-min / above-max tail bins, so a
    # shift outside the reference range (or a constant reference) is visible.
    inner = np.unique(np.concatenate([qs[1:-1], [lo, np.nextafter(hi, np.inf)]]))
    r_idx = np.searchsorted(inner, ref, side="right")
    c_idx = np.searchsorted(inner, cur, side="right")
    nb = inner.size + 1
    eps = 1e-4
    r = np.maximum(np.bincount(r_idx, minlength=nb) / ref.size, eps)
    c = np.maximum(np.bincount(c_idx, minlength=nb) / cur.size, eps)
    return float(np.sum((c - r) * np.log(c / r)))


def _ks_1d(ref: np.ndarray, cur: np.ndarray) -> tuple[float, float]:
    """Two-sample Kolmogorov-Smirnov statistic + asymptotic p-value (numpy only)."""
    a, b = np.sort(ref), np.sort(cur)
    grid = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, grid, side="right") / a.size
    cdf_b = np.searchsorted(b, grid, side="right") / b.size
    d = float(np.max(np.abs(cdf_a - cdf_b)))
    en = math.sqrt(a.size * b.size / (a.size + b.size))
    lam = (en + 0.12 + 0.11 / en) * d
    if lam < 1e-12:
        return d, 1.0
    p = 2.0 * sum(((-1) ** (k - 1)) * math.exp(-2.0 * k * k * lam * lam) for k in range(1, 101))
    return d, float(min(1.0, max(0.0, p)))


def _drift(config, inputs, types):
    method = str(_cfg(config, "method", "psi") or "psi").lower()
    if method not in ("psi", "ks"):
        raise ValueError(f"drift_detect: unsupported method {method!r} (supported: psi, ks)")
    thr_raw = _cfg(config, "threshold", 0.2)
    threshold = 0.2 if thr_raw is None else float(thr_raw)
    bins_raw = _cfg(config, "bins", 10)
    bins = 10 if bins_raw is None else int(bins_raw)
    if bins < 2:
        raise ValueError("drift_detect: bins must be >= 2")
    split = str(_cfg(config, "split", "all") or "all")

    ref, names = _matrix(inputs.get("reference"), split)
    cur, cur_names = _matrix(inputs.get("current"), split)
    if ref.shape[0] == 0 or cur.shape[0] == 0:
        raise ValueError("drift_detect: reference and current must be non-empty")
    if ref.shape[1] != cur.shape[1]:
        raise ValueError(f"drift_detect: feature count mismatch (reference={ref.shape[1]}, current={cur.shape[1]})")
    if names != cur_names:
        if sorted(names) == sorted(cur_names):
            cur = cur[:, [cur_names.index(n) for n in names]]
        elif all(n[:1] == "f" and n[1:].isdigit() for n in names + cur_names):
            pass  # positional feature names from arrays
        else:
            raise ValueError(f"drift_detect: feature names differ ({names} vs {cur_names})")

    per_feature: dict[str, float] = {}
    p_values: dict[str, float] = {}
    skipped: list[str] = []
    for j, name in enumerate(names):
        r = ref[:, j][np.isfinite(ref[:, j])]
        c = cur[:, j][np.isfinite(cur[:, j])]
        if r.size == 0 or c.size == 0:
            skipped.append(name)
            continue
        if method == "psi":
            per_feature[name] = _psi_1d(r, c, bins)
        else:
            d, p = _ks_1d(r, c)
            per_feature[name] = d
            p_values[name] = p
    if not per_feature:
        raise ValueError("drift_detect: no feature had finite values in both reference and current")

    score = max(per_feature.values())
    drifted_features = [n for n, v in per_feature.items() if v >= threshold]
    scores: dict[str, Any] = {
        "method": method,
        "score": score,
        method: score,
        "aggregate": "max",
        "threshold": threshold,
        "per_feature": per_feature,
        "drifted_features": drifted_features,
        "n_features": len(names),
        "n_reference": int(ref.shape[0]),
        "n_current": int(cur.shape[0]),
    }
    if p_values:
        scores["p_values"] = p_values
    if skipped:
        scores["skipped_features"] = skipped
    return _T(types, "DriftReport", drifted=bool(drifted_features), scores=scores)



class DriftDetectNode(Node):
    """Feature/prediction drift"""

    node_type: ClassVar[str] = "drift_detect"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="drift_detect",
        label="Drift Detect",
        description="Feature/prediction drift",
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
        "reference": InputPort(name="reference", data_type=object, required=True, description="DatasetArtifact|list[FeatureArray]"),
        "current": InputPort(name="current", data_type=object, required=True, description="DatasetArtifact|list[FeatureArray]"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="DriftReport NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        method: Literal["psi", "ks"] = Field(default="psi", title="Method", description="psi: population stability index on reference-quantile bins; ks: two-sample KS statistic.")
        threshold: float = Field(default=0.2, title="Threshold", description="A feature drifts when its score >= threshold (psi value or KS D).")
        bins: int = Field(default=10, title="Bins", description="PSI quantile bins (reference-derived).")
        split: Literal["all", "train", "val", "test"] = Field(default="all", title="Split", description="DatasetArtifact split(s) to compare.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'drift_detect'
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
            result = DriftReport()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"drift_detect: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _drift(self.config, inputs, _types)}
