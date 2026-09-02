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
    assert builder.output_ports["output"].data_type is ModelArtifact
    assert trainer.input_ports["model"].data_type is ModelArtifact
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



def _specs(rel: str) -> dict:
    path = repo_root() / rel
    return specs_from_source(path.read_text(encoding="utf-8"), filename=str(path))


def test_isolated_trainer_dataset_port_is_dataset_artifact() -> None:
    trainer = _specs("PluginPackage/Common/trainer/nodes.py")["trainer"]
    assert trainer.input_ports["dataset"].data_type is DatasetArtifact
    builder = _specs("PluginPackage/Common/dataset_builder/nodes.py")["dataset_builder"]
    assert CompatibilityChecker.are_compatible(
        builder.output_ports["output"].data_type,
        trainer.input_ports["dataset"].data_type,
    )


def test_isolated_realtime_inference_ports_are_platform_lists() -> None:
    from typing import get_args, get_origin

    from app.models.feature_array import FeatureArray
    from app.models.prediction_result import PredictionResult

    inf = _specs("PluginPackage/Common/realtime_inference/nodes.py")["realtime_inference"]
    in_dt = inf.input_ports["input"].data_type
    out_dt = inf.output_ports["output"].data_type
    assert get_origin(in_dt) is list
    assert get_args(in_dt) == (FeatureArray,)
    assert get_origin(out_dt) is list
    assert get_args(out_dt) == (PredictionResult,)
    frontend = _specs("PluginPackage/Audio/feature_frontend/nodes.py")["feature_frontend"]
    assert CompatibilityChecker.are_compatible(
        frontend.output_ports["output"].data_type,
        inf.input_ports["input"].data_type,
    )


def test_isolated_edge_optimizer_ports_are_platform_artifacts() -> None:
    from app.models.deployment_artifact import DeploymentArtifact

    edge = _specs("PluginPackage/Common/edge_optimizer/nodes.py")["edge_optimizer"]
    assert edge.input_ports["input"].data_type is ModelArtifact
    assert edge.output_ports["output"].data_type is DeploymentArtifact
    evaluator = _specs("PluginPackage/Common/evaluator/nodes.py")["evaluator"]
    assert CompatibilityChecker.are_compatible(
        evaluator.output_ports["output"].data_type,
        edge.input_ports["input"].data_type,
    )


_ISOLATED_PACKAGES = (
    ("PluginPackage/Common/trainer", "trainer", ("trainer", "model_builder")),
    ("PluginPackage/Common/evaluator", "evaluator", ("evaluator",)),
    ("PluginPackage/Common/edge_optimizer", "edge-optimizer", ("edge_optimizer",)),
    ("PluginPackage/Common/realtime_inference", "realtime-inference", ("realtime_inference",)),
)


def test_isolated_stub_config_and_ports_match_ast(tmp_path: Path, fresh_registry) -> None:
    """Host stubs must expose real Config fields and platform port types."""
    from app.core.plugins.isolated_schema import config_class_for_spec, ports_for_spec
    from app.core.plugins.loader import PluginLoader
    from app.core.plugins.manifest import load_manifest
    from app.core.plugins.venv_manager import PluginVenvManager as _VenvMgr
    from unit_test.core.plugins.test_dep_isolation import _mock_ensure

    loader = PluginLoader(fresh_registry)
    loaded: list[str] = []
    try:
        with patch.object(_VenvMgr, "ensure", side_effect=_mock_ensure):
            for rel, plugin_name, node_types in _ISOLATED_PACKAGES:
                plugin_dir = repo_root() / rel
                loader.load(plugin_dir)
                loaded.append(plugin_name)
                manifest = load_manifest(plugin_dir)
                ast_specs = {
                    k: v
                    for path in (plugin_dir / ep for ep in manifest.entry_points)
                    if path.is_file()
                    for k, v in specs_from_source(
                        path.read_text(encoding="utf-8"), filename=str(path)
                    ).items()
                }
                for node_type in node_types:
                    spec = ast_specs[node_type]
                    cls = fresh_registry.get_class(node_type)
                    ast_fields = {name for name, _t, _d in spec.config_fields}
                    stub_fields = set(cls.Config.model_fields) - set(
                        getattr(cls.Config.__bases__[0], "model_fields", {})
                    )
                    # NodeConfig may add shared fields; require every AST field present.
                    missing = ast_fields - set(cls.Config.model_fields)
                    assert not missing, f"{node_type} stub missing Config fields: {missing}"
                    in_ports, out_ports = ports_for_spec(spec)
                    assert set(cls.input_ports) == set(in_ports)
                    assert set(cls.output_ports) == set(out_ports)
                    for name, port in cls.input_ports.items():
                        assert port.data_type == in_ports[name].data_type
                    for name, port in cls.output_ports.items():
                        assert port.data_type == out_ports[name].data_type
                    # extra_forbidden: a real graph knob must not fail
                    payload = {name: default for name, _t, default in spec.config_fields}
                    if node_type == "realtime_inference":
                        payload["model_path"] = "workspace/models/model.tflite"
                    cls.Config.model_validate(payload)
                    cfg_cls = config_class_for_spec(node_type, spec, None)
                    cfg_cls.model_validate(payload)
    finally:
        for name in loaded:
            get_runtime_registry().unregister_plugin(name)


def test_isolated_loader_sees_evaluator_as_isolated(tmp_path: Path, fresh_registry) -> None:
    """Host loader must stub evaluator without pip-installing TensorFlow."""
    from app.core.plugins.loader import PluginLoader
    from app.core.plugins.venv_manager import PluginVenvManager as _VenvMgr
    from unit_test.core.plugins.test_dep_isolation import _mock_ensure

    captured: dict = {}

    def capture_ensure(plugin_name, requirements, **kwargs):
        captured["name"] = plugin_name
        captured["reqs"] = list(requirements)
        return _mock_ensure(plugin_name, requirements, **kwargs)

    loader = PluginLoader(fresh_registry)
    plugin_dir = repo_root() / "PluginPackage/Common/evaluator"
    with patch.object(_VenvMgr, "ensure", side_effect=capture_ensure):
        types = loader.load(plugin_dir)
    try:
        assert "evaluator" in types
        cls = fresh_registry.get_class("evaluator")
        assert getattr(cls, "_graphyn_isolated", False) is True
        expected = {
            "output_path",
            "plot_confusion_matrix",
            "plot_training_curves",
            "compute_roc",
            "compute_fairness",
            "fairness_attribute_key",
        }
        missing = expected - set(cls.Config.model_fields)
        assert not missing, missing
        assert cls.output_ports["output"].data_type is ModelArtifact
        assert cls.input_ports["model_artifact"].data_type is ModelArtifact
        assert cls.input_ports["dataset"].data_type is DatasetArtifact
        assert captured["name"] == "evaluator"
        assert any(r.startswith("numpy") for r in captured["reqs"])
        assert any("scikit-learn" in r for r in captured["reqs"])
        assert any(r.startswith("tensorflow") for r in captured["reqs"])
        assert any(r.startswith("keras") for r in captured["reqs"])
        assert not any(
            r.split("[")[0].split(">")[0].split("=")[0].strip().lower() == "torch"
            for r in captured["reqs"]
        )
    finally:
        get_runtime_registry().unregister_plugin("evaluator")
