"""Isolated stub ports must resolve platform types without importing plugins."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from app.core.example_templates import repo_root
from app.core.nodes.compat import CompatibilityChecker
from app.core.plugins.isolated_schema import specs_from_source
from app.core.plugins.runtime_registry import get_runtime_registry
from app.models.dataset_artifact import DatasetArtifact
from app.models.model_artifact import ModelArtifact


def test_trainer_ast_output_is_model_artifact_without_importing_plugin() -> None:
    trainer_mod = "PluginPackage.Common.trainer.nodes"
    sys.modules.pop(trainer_mod, None)
    path = repo_root() / "PluginPackage/Common/trainer/nodes.py"
    specs = specs_from_source(path.read_text(encoding="utf-8"), filename=str(path))
    assert trainer_mod not in sys.modules
    trainer = specs["trainer"]
    assert trainer.output_ports["output"].data_type is ModelArtifact
    evaluator_path = repo_root() / "PluginPackage/Common/evaluator/nodes.py"
    evaluator = specs_from_source(
        evaluator_path.read_text(encoding="utf-8"), filename=str(evaluator_path)
    )["evaluator"]
    assert CompatibilityChecker.are_compatible(
        trainer.output_ports["output"].data_type,
        evaluator.input_ports["model_artifact"].data_type,
    )
    builder = specs["model_builder"]
    assert CompatibilityChecker.are_compatible(
        builder.output_ports["output"].data_type,
        trainer.input_ports["model"].data_type,
    )
    edge_path = repo_root() / "PluginPackage/Common/edge_optimizer/nodes.py"
    edge = specs_from_source(edge_path.read_text(encoding="utf-8"), filename=str(edge_path))[
        "edge_optimizer"
    ]
    assert CompatibilityChecker.are_compatible(
        trainer.output_ports["output"].data_type,
        edge.input_ports["input"].data_type,
    )


def test_unknown_plugin_local_port_type_stays_object() -> None:
    source = '''
from typing import ClassVar
from app.core.nodes.ports import InputPort, OutputPort

class LocalType:
    pass

class Demo:
    node_type: ClassVar[str] = "demo"
    input_ports = {
        "input": InputPort(name="input", data_type=LocalType, required=True),
    }
    output_ports = {
        "output": OutputPort(name="output", data_type=LocalType),
        "named": OutputPort(name="named", data_type=app.models.model_artifact.ModelArtifact),
    }
'''
    specs = specs_from_source(source)
    demo = specs["demo"]
    assert demo.input_ports["input"].data_type is object
    assert demo.output_ports["output"].data_type is object
    assert demo.output_ports["named"].data_type is ModelArtifact


def test_isolated_stub_trainer_output_is_model_artifact(tmp_path: Path, fresh_registry) -> None:
    from app.core.plugins.loader import PluginLoader
    from app.core.plugins.venv_manager import PluginVenvManager as _VenvMgr
    from unit_test.core.plugins.test_dep_isolation import _isolated_toml, _mock_ensure

    extra = '''
from typing import ClassVar
from app.core.nodes.config import NodeConfig
from app.core.nodes.ports import InputPort, OutputPort
from app.models.dataset_artifact import DatasetArtifact
from app.models.model_artifact import ModelArtifact

class TrainerNode:
    node_type: ClassVar[str] = "trainer"
    input_ports = {
        "model": InputPort(name="model", data_type=object, required=True),
        "dataset": InputPort(name="dataset", data_type=object, required=True),
    }
    output_ports = {
        "output": OutputPort(name="output", data_type=ModelArtifact),
    }
    class Config(NodeConfig):
        backend: str = "auto"
'''
    plugin_dir = _isolated_toml(
        tmp_path, name="iso-trainer", node_types='["trainer"]', extra_nodes_py=extra
    )
    loader = PluginLoader(fresh_registry)
    with patch.object(_VenvMgr, "ensure", side_effect=_mock_ensure):
        loader.load(plugin_dir)
    try:
        cls = fresh_registry.get_class("trainer")
        assert cls.output_ports["output"].data_type is ModelArtifact
        from app.core.nodes.ports import InputPort

        evaluator_in = InputPort(name="model_artifact", data_type=ModelArtifact)
        assert CompatibilityChecker.are_compatible(
            cls.output_ports["output"].data_type, evaluator_in.data_type
        )
    finally:
        get_runtime_registry().unregister_plugin("iso-trainer")

def test_dataset_builder_ast_output_is_dataset_artifact_without_importing_plugin() -> None:
    builder_mod = "PluginPackage.Common.dataset_builder.nodes"
    sys.modules.pop(builder_mod, None)
    path = repo_root() / "PluginPackage/Common/dataset_builder/nodes.py"
    specs = specs_from_source(path.read_text(encoding="utf-8"), filename=str(path))
    assert builder_mod not in sys.modules
    builder = specs["dataset_builder"]
    assert builder.output_ports["output"].data_type is DatasetArtifact
    trainer_path = repo_root() / "PluginPackage/Common/trainer/nodes.py"
    trainer = specs_from_source(
        trainer_path.read_text(encoding="utf-8"), filename=str(trainer_path)
    )["model_builder"]
    assert CompatibilityChecker.are_compatible(
        builder.output_ports["output"].data_type,
        trainer.input_ports["input"].data_type,
    )

