"""text_stats_plugin.nodes — TextStatsNode.

Counts words, characters, and sentences in DataSample.source text fields.
Registered automatically by AutoDiscovery via plugin.toml entry_points.
"""
from __future__ import annotations

from typing import ClassVar

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.data_sample import DataSample


class TextStatsConfig(NodeConfig):
    add_word_count: bool = True
    add_char_count: bool = True
    add_sentence_count: bool = True


class TextStatsNode(Node):
    """Count words, characters, and sentences in DataSample.source text.

    Adds stats to DataSample.metadata:
      - word_count, char_count, sentence_count
    """

    node_type: ClassVar[str] = "text_stats"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="text_stats",
        label="Text Stats",
        description="Count words, characters, and sentences in DataSample text.",
        category="Text Processing",
        version="1.0.0",
        tags=["text", "statistics", "nlp"],
    )
    input_ports:  ClassVar[dict] = {"input":  InputPort(name="input",  data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(TextStatsConfig):
        pass

    def process(self, samples: list) -> list:
        out = []
        for sample in samples:
            text = sample.source or ""
            meta = dict(sample.metadata)
            if self.config.add_word_count:
                meta["word_count"] = len(text.split())
            if self.config.add_char_count:
                meta["char_count"] = len(text)
            if self.config.add_sentence_count:
                meta["sentence_count"] = text.count(".") + text.count("!") + text.count("?")
            out.append(DataSample(id=sample.id, source=sample.source, metadata=meta))
        return out
