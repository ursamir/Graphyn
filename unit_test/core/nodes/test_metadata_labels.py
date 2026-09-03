"""Display and cache-key node types for isolated stubs."""
from types import SimpleNamespace

from app.core.nodes.metadata import human_node_label, stable_node_type


def test_human_node_label_edge_optimizer():
    assert human_node_label("edge_optimizer") == "Edge Optimizer"
    assert human_node_label("Isolated_edge_optimizer") == "Edge Optimizer"


def test_stable_node_type_prefers_declared_attribute():
    class Isolated_edge_optimizer:
        node_type = "edge_optimizer"

    assert stable_node_type(Isolated_edge_optimizer()) == "edge_optimizer"


def test_stable_node_type_uses_metadata_when_class_attr_empty():
    node = SimpleNamespace(
        node_type="",
        metadata=SimpleNamespace(node_type="segmenter"),
    )
    assert stable_node_type(node) == "segmenter"


def test_stable_node_type_strips_isolated_class_prefix():
    class Isolated_edge_optimizer:
        pass

    assert stable_node_type(Isolated_edge_optimizer()) == "edge_optimizer"
