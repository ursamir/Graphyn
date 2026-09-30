"""WakewordDataGenNode — Promote data_generator→plugin

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import math
import random
import re
import struct
import wave

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.audio_sample import AudioSample

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("wakeword_data_gen.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

def _wakeword_data(config, inputs, types):
    phrases = list(_cfg(config, "phrases", ["yes", "no"]) or ["yes"])
    rate = int(_cfg(config, "sample_rate", 16000) or 16000)
    out = Path(str(_cfg(config, "output_dir", "workspace/artifacts/wakeword") or "workspace/artifacts/wakeword"))
    out.mkdir(parents=True, exist_ok=True)
    written = []
    rng = random.Random(0)
    for phrase in phrases:
        samples = []
        for ch in phrase.lower():
            freq = 200 + (ord(ch) % 40) * 20
            for n in range(int(rate * 0.05)):
                samples.append(int(16000 * math.sin(2 * math.pi * freq * n / rate) * (0.4 + 0.1 * rng.random())))
        path = out / f"{re.sub(r'[^a-z0-9]+', '_', phrase.lower())}.wav"
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(struct.pack("<" + "h" * len(samples), *samples))
        written.append(str(path))
    return {"files": written, "sample_rate": rate}



class WakewordDataGenNode(Node):
    """Promote data_generator→plugin"""

    node_type: ClassVar[str] = "wakeword_data_gen"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="wakeword_data_gen",
        label="Wakeword Data Gen",
        description="Promote data_generator→plugin",
        category="Input",
        version="0.1.0",
        tags=["wakeword"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {}

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[AudioSample]"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        phrases: list = Field(default_factory=lambda: [])
        sample_rate: int = Field(default=16000, title="Sample rate", description="Sample rate.")
        output_dir: str = Field(default='workspace/datasets/wakeword', title="Output dir", description="Output dir.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'wakeword' / 'wakeword_data_gen'
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
            raise ImportError(f"wakeword_data_gen: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _wakeword_data(self.config, inputs, _types)}
