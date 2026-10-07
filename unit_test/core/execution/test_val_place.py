"""VAL-PLACE: mode=worker requires worker id; mode=pool requires pool."""
from __future__ import annotations

from app.core.execution.validation import validate_graph_ir_result
from app.core.ir.models import GraphIR, IRMetadata, IRNode, IRPlacement


class _EmptyRegistry:
    def get_class(self, node_type: str):
        raise KeyError(node_type)

    def list_nodes(self):
        return []


def _graph_with_placement(placement: IRPlacement | None) -> GraphIR:
    return GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="val-place-smoke", seed=42),
        nodes=[
            IRNode(
                id="n0",
                node_type="python_code",
                config={},
                placement=placement,
            )
        ],
        edges=[],
    )


def test_val_place_worker_without_id_is_error():
    g = _graph_with_placement(IRPlacement(mode="worker", worker=None))
    # Unknown type still errors; ensure VAL-PLACE also present when type known.
    # Use a tiny fake registry that accepts python_code with empty Config.
    class Cfg:
        model_fields = {}

        @classmethod
        def model_validate(cls, data):
            return data

    class Node:
        Config = Cfg
        def __init__(self, config=None, seed=0):
            pass

    class Reg:
        def get_class(self, node_type: str):
            return Node

        def list_nodes(self):
            return []

    result = validate_graph_ir_result(g, Reg())
    codes = [e["code"] for e in result["errors"]]
    assert "VAL-PLACE" in codes, result


def test_val_place_pool_without_name_is_error():
    class Cfg:
        model_fields = {}

        @classmethod
        def model_validate(cls, data):
            return data

    class Node:
        Config = Cfg
        def __init__(self, config=None, seed=0):
            pass

    class Reg:
        def get_class(self, node_type: str):
            return Node

        def list_nodes(self):
            return []

    g = _graph_with_placement(IRPlacement(mode="pool", pool=None))
    result = validate_graph_ir_result(g, Reg())
    codes = [e["code"] for e in result["errors"]]
    assert "VAL-PLACE" in codes, result


def test_val_place_auto_ok():
    class Cfg:
        model_fields = {}

        @classmethod
        def model_validate(cls, data):
            return data

    class Node:
        Config = Cfg
        def __init__(self, config=None, seed=0):
            pass

    class Reg:
        def get_class(self, node_type: str):
            return Node

        def list_nodes(self):
            return []

    g = _graph_with_placement(IRPlacement(mode="auto", tags=("gpu",), pool="gpu-lab"))
    result = validate_graph_ir_result(g, Reg())
    codes = [e["code"] for e in result["errors"]]
    assert "VAL-PLACE" not in codes, result
