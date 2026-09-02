
"""MCP tests: register a dummy node so GRAPHYN_SKIP_PLUGIN_LOAD=1 still works."""
from __future__ import annotations

from typing import ClassVar

import pytest

from app.core.nodes import registry
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort


class _McpDummyNode(Node):
    node_type: ClassVar[str] = "audio_conditioner"
    input_ports: ClassVar[dict] = {
        "input": InputPort(name="input", data_type=object | None, required=False),
    }
    output_ports: ClassVar[dict] = {
        "output": OutputPort(name="output", data_type=object),
    }
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="audio_conditioner",
        label="Audio Conditioner",
        description="Test stand-in when plugins are not loaded.",
        category="Preprocessing",
        version="1.0.0",
        tags=["test"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
    )

    class Config(NodeConfig):
        target_sample_rate: int = 16000
        mono: bool = True

    def process(self, inputs):
        return {"output": inputs.get("input") if isinstance(inputs, dict) else inputs}


class _McpSegmenter(_McpDummyNode):
    node_type: ClassVar[str] = "segmenter"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="segmenter",
        label="Segmenter",
        description="Test stand-in when plugins are not loaded.",
        category="Processing",
        version="1.0.0",
        tags=["test"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
    )

    class Config(NodeConfig):
        pass


@pytest.fixture(scope="module", autouse=True)
def _register_mcp_dummy_nodes():
    if "audio_conditioner" not in registry:
        registry.register("audio_conditioner", _McpDummyNode, _McpDummyNode.metadata)
    if "segmenter" not in registry:
        registry.register("segmenter", _McpSegmenter, _McpSegmenter.metadata)
    try:
        from app.models.audio_sample import AudioSample
        registry.type_catalogue.register(AudioSample)
    except Exception:
        pass
    yield
