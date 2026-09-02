# app/core/plugins/hydrate.py
"""
Bounded Context:  BC3 / BC5 — Isolated plugin execution + cache restore
Responsibility:   Rehydrate JSON/pickle dicts into Pydantic PortDataType models.
Owns:             hydrate_platform_models(), coerce_node_inputs()
Public Surface:   hydrate_platform_models, coerce_node_inputs
Must NOT:         Import from app.api or app.domain. Must not touch RestrictedUnpickler.
Dependencies:     stdlib typing, pydantic PortDataType (via duck-typing model_validate)
Reason To Change: New platform port types need cache/IPC restore, or list-port rules change.

PipelineCache serializes Pydantic via model_dump(mode="json"). Isolated workers
then pickle.load a dict, not ModelArtifact/DatasetArtifact. This helper is the
single coerce path used by the isolated worker and by cache restore.
"""
from __future__ import annotations

from typing import Any, get_args, get_origin

_SKIP_TYPES = {dict, list, tuple, str, int, float, bool, bytes, object, type(None)}


def _is_pydantic_model_type(tp: Any) -> bool:
    if tp is None or not isinstance(tp, type) or tp in _SKIP_TYPES:
        return False
    return callable(getattr(tp, "model_validate", None))


def _platform_types() -> tuple[type, ...]:
    """Known app.models PortDataType classes, distinctive types first."""
    try:
        import app.models as models
    except Exception:  # pragma: no cover
        return ()
    names = (
        "ModelArtifact",
        "DatasetArtifact",
        "DeploymentArtifact",
        "TFLiteArtifact",
        "FeatureArray",
        "PredictionResult",
        "AudioSample",
        "DataSample",
        "TensorBatch",
    )
    out: list[type] = []
    for name in names:
        obj = getattr(models, name, None)
        if _is_pydantic_model_type(obj):
            out.append(obj)
    return tuple(out)


def _distinctive_match(payload: dict[str, Any], cls: type) -> bool:
    """True when *payload* looks like a dumped instance of *cls*, not a generic dict."""
    name = getattr(cls, "__name__", "")
    keys = payload.keys()
    if name == "ModelArtifact":
        return "model_path" in keys and "labels" in keys
    if name == "DatasetArtifact":
        return "n_classes" in keys and "labels" in keys
    if name == "DeploymentArtifact":
        return "artifact_path" in keys and "model_format" in keys
    if name == "TFLiteArtifact":
        return "tflite_path" in keys or (
            "model_path" in keys and "quantization" in keys and "model_format" not in keys
        )
    return False


def _validate(cls: type, payload: dict[str, Any]) -> Any:
    try:
        return cls.model_validate(payload)
    except Exception:
        return payload


def hydrate_platform_models(obj: Any, expected_type: Any = None) -> Any:
    """Coerce *obj* to *expected_type* when that type is a Pydantic/PortDataType.

    ``expected_type=None`` infers ModelArtifact / DatasetArtifact / etc. from
    distinctive keys (used by pipeline cache restore). List expected types
    hydrate each element.
    """
    if obj is None:
        return obj

    origin = get_origin(expected_type)
    if origin in (list, tuple):
        inner = get_args(expected_type)[0] if get_args(expected_type) else None
        if isinstance(obj, list):
            seq = [hydrate_platform_models(v, inner) for v in obj]
            return seq if origin is list else origin(seq)
        if isinstance(obj, tuple):
            return tuple(hydrate_platform_models(v, inner) for v in obj)
        inner = get_args(expected_type)[0] if get_args(expected_type) else None
        return hydrate_platform_models(obj, inner)

    if _is_pydantic_model_type(expected_type):
        if isinstance(obj, expected_type):
            return obj
        if isinstance(obj, dict):
            return _validate(expected_type, obj)
        return obj

    # Untyped restore (cache JSON): infer then recurse into nested dict/list.
    if expected_type is None:
        if isinstance(obj, dict):
            for cls in _platform_types():
                if _distinctive_match(obj, cls):
                    hydrated = _validate(cls, obj)
                    if type(hydrated) is cls:
                        return hydrated
            return {k: hydrate_platform_models(v, None) for k, v in obj.items()}
        if isinstance(obj, list):
            return [hydrate_platform_models(v, None) for v in obj]
        if isinstance(obj, tuple):
            return tuple(hydrate_platform_models(v, None) for v in obj)
    return obj


def coerce_node_inputs(inputs: Any, node_cls: Any) -> Any:
    """Hydrate each port value to ``node_cls.input_ports[name].data_type``."""
    if not isinstance(inputs, dict):
        return inputs
    ports = getattr(node_cls, "input_ports", None) or {}
    out: dict[str, Any] = {}
    for name, value in inputs.items():
        port = ports.get(name)
        if port is None:
            out[name] = value
            continue
        dt = getattr(port, "data_type", None)
        cardinality = getattr(port, "cardinality", "single")
        origin = get_origin(dt)
        inner = get_args(dt)[0] if origin in (list, tuple) and get_args(dt) else dt
        if cardinality == "multi" or origin is list:
            if isinstance(value, list):
                out[name] = [hydrate_platform_models(v, inner) for v in value]
            else:
                out[name] = hydrate_platform_models(value, inner)
        else:
            out[name] = hydrate_platform_models(value, dt)
    return out
