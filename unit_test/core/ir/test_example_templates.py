"""Starter templates and UI-synced example graphs must pass registry Config validation.

When a node type is not installed in this environment (missing optional deps),
we still validate config keys against the PluginPackage AST Config schema so
extra_forbidden / unknown-field mismatches cannot slip through.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

from app.core.example_templates import discover_example_graphs, examples_dir, repo_root
from app.core.ir.loader import load_ir
from app.core.nodes.compat import CompatibilityChecker
from app.core.plugins.isolated_schema import (
    IsolatedNodeSpec,
    config_class_for_spec,
    specs_from_source,
)
from app.core.registry_runtime import get_registry


@lru_cache(maxsize=1)
def _plugin_package_specs() -> dict[str, IsolatedNodeSpec]:
    root = repo_root() / "PluginPackage"
    merged: dict[str, IsolatedNodeSpec] = {}
    if not root.is_dir():
        return merged
    for path in root.rglob("nodes.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        merged.update(specs_from_source(text, filename=str(path)))
    return merged


def _template_paths() -> list[Path]:
    return sorted((examples_dir() / "templates").glob("*.graph.json"))


def _config_and_ports(node_type: str):
    registry = get_registry()
    try:
        node_class = registry.get_class(node_type)
        return node_class.Config, node_class.input_ports, node_class.output_ports, "registry"
    except Exception:
        pass
    spec = _plugin_package_specs().get(node_type)
    if spec is None:
        pytest.fail(
            f"node_type {node_type!r} is not registered and has no PluginPackage Config"
        )
    cfg = config_class_for_spec(node_type, spec, None)
    return cfg, spec.input_ports, spec.output_ports, "ast"


def _validate_graph_like_api(path: Path) -> None:
    """IR load + Config.model_validate (API Run instantiates nodes the same way)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    graph = load_ir(data)
    ports_by_id: dict = {}
    for node in graph.nodes:
        config_cls, in_ports, out_ports, _src = _config_and_ports(node.node_type)
        try:
            config_cls.model_validate(dict(node.config or {}))
        except Exception as exc:
            pytest.fail(
                f"{path.name}: extra_forbidden/config error on {node.node_type} "
                f"id={node.id} via {_src}: {exc}"
            )
        ports_by_id[node.id] = (in_ports, out_ports, node.node_type)
    for edge in graph.edges:
        if edge.src_id not in ports_by_id or edge.dst_id not in ports_by_id:
            pytest.fail(f"{path.name}: edge references unknown node {edge.src_id!r} → {edge.dst_id!r}")
        src_in, src_out, src_type = ports_by_id[edge.src_id]
        dst_in, dst_out, dst_type = ports_by_id[edge.dst_id]
        if edge.src_port not in src_out:
            pytest.fail(
                f"{path.name}: {src_type} missing output port {edge.src_port!r}"
            )
        if edge.dst_port not in dst_in:
            pytest.fail(
                f"{path.name}: {dst_type} missing input port {edge.dst_port!r}"
            )
        src_dt = src_out[edge.src_port].data_type
        dst_dt = dst_in[edge.dst_port].data_type
        if not CompatibilityChecker.are_compatible(src_dt, dst_dt):
            pytest.fail(
                f"{path.name}: incompatible {edge.src_id}.{edge.src_port} "
                f"({src_type} produces {src_dt!r}) → {edge.dst_id}.{edge.dst_port} "
                f"({dst_type} expects {dst_dt!r})"
            )


@pytest.mark.parametrize("path", _template_paths(), ids=lambda p: p.name)
def test_starter_templates_validate_against_registry(path: Path) -> None:
    assert path.is_file()
    _validate_graph_like_api(path)


@pytest.mark.parametrize("item", discover_example_graphs(), ids=lambda d: d["id"])
def test_ui_loaded_example_templates_validate_against_registry(item: dict) -> None:
    _validate_graph_like_api(Path(item["path"]))


def test_speech_commands_e2e_train_graph_model_builder_config() -> None:
    path = repo_root() / "examples/06_speech_commands_e2e/pipeline_train_ml.graph.json"
    _validate_graph_like_api(path)
