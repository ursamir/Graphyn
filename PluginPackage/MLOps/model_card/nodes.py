"""ModelCardNode — Generate model card md/json

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

from app.models.model_artifact import ModelArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("model_card.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ModelCardArtifact = _types.ModelCardArtifact

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

def _out_path(config: Any, default_name: str) -> Path:
    raw = _cfg(config, "output_path") or _cfg(config, "output_dir") or _cfg(config, "persist_path")
    path = Path(str(raw or f"workspace/artifacts/proposed/{default_name}"))
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path.mkdir(parents=True, exist_ok=True)
    return path

def _model_card(config, inputs, types):
    model = _dump(inputs.get("model"))
    ev = _dump(inputs.get("eval"))
    path = _out_path(config, "model_card.md")
    if path.is_dir():
        path = path / "model_card.md"
    body = "# Model card\n\n"
    body += "## Model\n\n```json\n" + json.dumps(model, default=str, indent=2)[:8000] + "\n```\n\n"
    body += "## Evaluation\n\n```json\n" + json.dumps(ev, default=str, indent=2)[:8000] + "\n```\n"
    content = {"markdown": body, "model": model, "evaluation": ev}
    path.write_text(body, encoding="utf-8")
    return _T(types, "ModelCardArtifact", path=str(path), content=content) if hasattr(types, "ModelCardArtifact") else {"path": str(path), "content": content}



class ModelCardNode(Node):
    """Generate model card md/json"""

    node_type: ClassVar[str] = "model_card"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="model_card",
        label="Model Card",
        description="Generate model card md/json",
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
        "model": InputPort(name="model", data_type=object, required=True, description="ModelArtifact"),
        "eval": InputPort(name="eval", data_type=object | None, required=False, description="ModelArtifact optional"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ModelCardArtifact NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        output_path: str = Field(default='workspace/artifacts/model_cards', title="Output path", description="Output path.")
        include_confusion: bool = Field(default=True, title="Include confusion", description="Include confusion.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'model_card'
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
            result = ModelCardArtifact()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"model_card: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _model_card(self.config, inputs, _types)}
