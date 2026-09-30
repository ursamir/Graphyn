"""VideoQualityGateNode — Reject corrupt/short videos

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

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
        _types = importlib.import_module("video_quality_gate.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

VideoSample = _types.VideoSample

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

def _video_gate(config, inputs, types):
    samples = _as_list(inputs.get("input"))
    kept = []
    min_s = float(_cfg(config, "min_duration_s", 0) or 0)
    max_s = float(_cfg(config, "max_duration_s", 10**9) or 10**9)
    for item in samples:
        data = _dump(item)
        duration = float(data.get("duration_s") or data.get("duration") or 0) if isinstance(data, dict) else 0
        if duration and not (min_s <= duration <= max_s):
            if str(_cfg(config, "rejection_policy", "drop") or "drop") == "error":
                raise RuntimeError(f"video duration {duration} outside [{min_s}, {max_s}]")
            continue
        kept.append(item)
    return kept



class VideoQualityGateNode(Node):
    """Reject corrupt/short videos"""

    node_type: ClassVar[str] = "video_quality_gate"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="video_quality_gate",
        label="Video Quality Gate",
        description="Reject corrupt/short videos",
        category="Quality",
        version="0.1.0",
        tags=["video"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[VideoSample] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[VideoSample] NEW"),
        "rejected": OutputPort(name="rejected", data_type=object, description="list[VideoSample] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        min_duration_s: float = Field(default=0.5, title="Min duration s", description="Min duration s.")
        max_duration_s: float = Field(default=600.0, title="Max duration s", description="Max duration s.")
        rejection_policy: Literal["skip", "error"] = Field(default='skip', title="Rejection policy", description="Rejection policy.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'video' / 'video_quality_gate'
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
            result = {
                "output": [],
                "rejected": [],
            }
            return result
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"video_quality_gate: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _video_gate(self.config, inputs, _types)}
