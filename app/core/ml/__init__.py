# app/core/ml/__init__.py
"""
Bounded Context:  ML host helpers
Responsibility:   TensorFlow device policy and the shared LLM client.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "chat_completion": "app.core.ml.llm_client",
    "configure_tf_gpu_sharing": "app.core.ml.tf_runtime",
    "configure_tf_stable_defaults": "app.core.ml.tf_runtime",
    "resolve_api_key": "app.core.ml.llm_client",
    "resolve_base_url": "app.core.ml.llm_client",
    "resolve_llm_endpoint": "app.core.ml.llm_client",
    "select_keras_device": "app.core.ml.tf_runtime",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
